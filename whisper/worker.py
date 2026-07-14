"""
GECA Whisper Worker
Extrae audio, transcribe con Faster-Whisper y busca menciones de marcas.
Usa word-level timestamps para medir duracion precisa de menciones.
Corre en GPU.
"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import subprocess
import threading
import json
import os
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher

app = FastAPI(title="GECA Whisper Worker", version="1.1.0")

AUDIO_DIR = os.getenv("AUDIO_DIR", "/mnt/shared/audio")

# Track jobs
jobs: dict[str, dict] = {}


class TranscribeRequest(BaseModel):
    video_path: str
    aliases: dict = {}
    brand_names: list[str] = []


def normalize(text: str) -> str:
    """Normalize text: lowercase, remove accents, remove punctuation"""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fuzzy_match(text: str, term: str, threshold: float = 0.82) -> bool:
    """Check if term appears in text with fuzzy matching"""
    text_n = normalize(text)
    term_n = normalize(term)

    if term_n in text_n:
        return True

    words = text_n.split()
    term_words = term_n.split()
    term_len = len(term_words)

    for i in range(len(words) - term_len + 1):
        window = " ".join(words[i:i + term_len])
        ratio = SequenceMatcher(None, window, term_n).ratio()
        if ratio >= threshold:
            return True

    return False


def find_word_timestamps(words: list, term: str) -> dict:
    """
    Find the precise start/end timestamps of a term within the word list.
    Returns {"start": float, "end": float, "duration": float} or None.
    """
    term_n = normalize(term)
    term_parts = term_n.split()
    num_parts = len(term_parts)

    if not words or not term_parts:
        return None

    # Build normalized word list
    norm_words = [normalize(w.get("word", "")) for w in words]

    # Sliding window search
    best_match = None
    best_ratio = 0

    for i in range(len(norm_words) - num_parts + 1):
        window = " ".join(norm_words[i:i + num_parts])

        # Exact match
        if window == term_n:
            return {
                "start": round(words[i].get("start", 0), 2),
                "end": round(words[i + num_parts - 1].get("end", 0), 2),
                "duration": round(words[i + num_parts - 1].get("end", 0) - words[i].get("start", 0), 2),
            }

        # Fuzzy match
        ratio = SequenceMatcher(None, window, term_n).ratio()
        if ratio > best_ratio and ratio >= 0.80:
            best_ratio = ratio
            best_match = {
                "start": round(words[i].get("start", 0), 2),
                "end": round(words[i + num_parts - 1].get("end", 0), 2),
                "duration": round(words[i + num_parts - 1].get("end", 0) - words[i].get("start", 0), 2),
            }

    return best_match


def format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def process_video(video_path: str, aliases: dict, brand_names: list[str], job_key: str):
    """Main processing function - runs in background thread"""
    video_stem = os.path.splitext(os.path.basename(video_path))[0]
    output_dir = os.path.join(AUDIO_DIR, video_stem)
    os.makedirs(output_dir, exist_ok=True)

    status_file = os.path.join(output_dir, "status.json")

    def update_status(phase: str, progress: int = 0, message: str = ""):
        status = {"status": "running", "phase": phase, "progress": progress, "message": message}
        jobs[job_key] = status
        with open(status_file, "w") as f:
            json.dump(status, f)

    try:
        # === PHASE 1: Extract audio ===
        update_status("audio", 0, "Extrayendo audio del video...")
        audio_path = os.path.join(output_dir, "audio.wav")

        if not os.path.exists(audio_path):
            cmd = [
                "ffmpeg", "-i", video_path,
                "-vn", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1",
                "-y", audio_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                update_status("error", 0, f"Error extrayendo audio: {result.stderr[:200]}")
                return

        update_status("audio", 100, "Audio extraido")

        # === PHASE 2: Transcribe ===
        update_status("transcribe", 0, "Cargando modelo Whisper...")

        from faster_whisper import WhisperModel

        model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")

        update_status("transcribe", 5, "Transcribiendo audio...")

        segments, info = model.transcribe(
            audio_path,
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=1000),
        )

        # Iterate over generator for real-time progress
        transcription = []
        segments_with_words = []  # Keep words for brand matching
        duration = info.duration or 1
        count = 0

        for seg in segments:
            # Segment-level data (for transcription view)
            seg_data = {
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "start_fmt": format_time(seg.start),
                "end_fmt": format_time(seg.end),
                "text": seg.text.strip(),
            }
            transcription.append(seg_data)

            # Word-level data (for precise brand matching)
            words = []
            if seg.words:
                for w in seg.words:
                    words.append({
                        "word": w.word.strip(),
                        "start": round(w.start, 2),
                        "end": round(w.end, 2),
                    })
            segments_with_words.append({
                "text": seg.text.strip(),
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "words": words,
            })

            count += 1
            progress = min(95, int((seg.end / duration) * 85) + 10)
            update_status("transcribe", progress, f"Transcribiendo... {format_time(seg.end)} / {format_time(duration)}")

        # Save transcription (segment-level, without words to keep file small)
        with open(os.path.join(output_dir, "transcription.json"), "w", encoding="utf-8") as f:
            json.dump({
                "segments": transcription,
                "language": info.language,
                "duration": info.duration
            }, f, ensure_ascii=False, indent=2)

        update_status("transcribe", 100, f"Transcripcion completada: {len(transcription)} segmentos")

        # === PHASE 3: Find brand mentions with precise timestamps ===
        update_status("brands", 0, "Buscando menciones de marcas...")

        mentions_by_brand = {}
        total_mentions = 0
        total_mention_duration = 0

        for seg in segments_with_words:
            text = seg["text"]
            words = seg["words"]

            for brand_name, brand_info in aliases.items():
                for term in brand_info.get("terms", []):
                    if fuzzy_match(text, term):
                        if brand_name not in mentions_by_brand:
                            mentions_by_brand[brand_name] = {
                                "brand_id": brand_info.get("brand_id"),
                                "color": brand_info.get("color", "#6c5ce7"),
                                "count": 0,
                                "total_duration": 0,
                                "mentions": [],
                            }

                        # Get precise word-level timestamps
                        word_ts = find_word_timestamps(words, term)

                        if word_ts:
                            mention_start = word_ts["start"]
                            mention_end = word_ts["end"]
                            mention_duration = word_ts["duration"]
                        else:
                            # Fallback: use segment timestamps but estimate ~1s per mention
                            mention_start = seg["start"]
                            mention_end = min(seg["start"] + 1.0, seg["end"])
                            mention_duration = mention_end - mention_start

                        mentions_by_brand[brand_name]["count"] += 1
                        mentions_by_brand[brand_name]["total_duration"] += mention_duration
                        mentions_by_brand[brand_name]["mentions"].append({
                            "start": mention_start,
                            "end": mention_end,
                            "start_fmt": format_time(mention_start),
                            "end_fmt": format_time(mention_end),
                            "duration": round(mention_duration, 2),
                            "text": text,
                            "matched_term": term,
                            "precision": "word" if word_ts else "estimated",
                        })
                        total_mentions += 1
                        total_mention_duration += mention_duration
                        break  # Only count once per segment per brand

        # Round totals
        for brand_name in mentions_by_brand:
            mentions_by_brand[brand_name]["total_duration"] = round(
                mentions_by_brand[brand_name]["total_duration"], 2
            )

        # Save mentions
        result = {
            "video": os.path.basename(video_path),
            "duration": info.duration,
            "total_mentions": total_mentions,
            "total_mention_duration": round(total_mention_duration, 2),
            "mention_coverage_pct": round(total_mention_duration / info.duration * 100, 2) if info.duration else 0,
            "brands": mentions_by_brand,
            "processed_at": datetime.utcnow().isoformat(),
        }

        with open(os.path.join(output_dir, "brand_mentions.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # Final status
        final = {
            "status": "done",
            "phase": "done",
            "progress": 100,
            "total_mentions": total_mentions,
            "total_duration": round(total_mention_duration, 2),
            "segments": len(transcription),
        }
        jobs[job_key] = final
        with open(status_file, "w") as f:
            json.dump(final, f)

        # Free GPU memory
        del model

    except Exception as e:
        error_status = {"status": "error", "phase": "error", "progress": 0, "message": str(e)}
        jobs[job_key] = error_status
        with open(status_file, "w") as f:
            json.dump(error_status, f)


# ==============================================
#  ENDPOINTS
# ==============================================

@app.get("/health")
def health():
    return {"status": "ok", "service": "geca-whisper"}


@app.post("/transcribe")
def transcribe(req: TranscribeRequest):
    video_stem = os.path.splitext(os.path.basename(req.video_path))[0]

    if video_stem in jobs and jobs[video_stem].get("status") == "running":
        return {"status": "already_running", "job": jobs[video_stem]}

    mentions_file = os.path.join(AUDIO_DIR, video_stem, "brand_mentions.json")
    if os.path.exists(mentions_file):
        import shutil
        old_dir = os.path.join(AUDIO_DIR, video_stem)
        if os.path.exists(old_dir):
            shutil.rmtree(old_dir)

    thread = threading.Thread(
        target=process_video,
        args=(req.video_path, req.aliases, req.brand_names, video_stem),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "video": video_stem}


@app.get("/status/{video_stem}")
def get_status(video_stem: str):
    if video_stem in jobs:
        return jobs[video_stem]

    status_file = os.path.join(AUDIO_DIR, video_stem, "status.json")
    if os.path.exists(status_file):
        with open(status_file) as f:
            return json.load(f)

    return {"status": "not_started"}
