"""
GECA Whisper Worker
Extrae audio, transcribe con Faster-Whisper y busca menciones de marcas.
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

app = FastAPI(title="GECA Whisper Worker", version="1.0.0")

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

    # Exact substring match
    if term_n in text_n:
        return True

    # Fuzzy match on sliding windows
    words = text_n.split()
    term_words = term_n.split()
    term_len = len(term_words)

    for i in range(len(words) - term_len + 1):
        window = " ".join(words[i:i + term_len])
        ratio = SequenceMatcher(None, window, term_n).ratio()
        if ratio >= threshold:
            return True

    return False


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

        update_status("audio", 100, "Audio extraído")

        # === PHASE 2: Transcribe ===
        update_status("transcribe", 0, "Cargando modelo Whisper...")

        from faster_whisper import WhisperModel

        model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")

        # Use brand names as initial prompt to help Whisper recognize them
        initial_prompt = None
        if brand_names:
            initial_prompt = f"Emisión deportiva. Marcas: {', '.join(brand_names)}."

        update_status("transcribe", 10, "Transcribiendo audio...")

        segments, info = model.transcribe(
            audio_path,
            language="es",
            initial_prompt=initial_prompt,
            beam_size=5,
            word_timestamps=True,
        )

        # Collect all segments
        transcription = []
        segments_list = list(segments)
        total_segments = len(segments_list)

        for i, seg in enumerate(segments_list):
            transcription.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "start_fmt": format_time(seg.start),
                "end_fmt": format_time(seg.end),
                "text": seg.text.strip(),
            })
            if total_segments > 0:
                progress = 10 + int((i / total_segments) * 80)
                update_status("transcribe", progress, f"Transcribiendo... {i}/{total_segments} segmentos")

        # Save transcription
        with open(os.path.join(output_dir, "transcription.json"), "w", encoding="utf-8") as f:
            json.dump({"segments": transcription, "language": info.language, "duration": info.duration}, f, ensure_ascii=False, indent=2)

        update_status("transcribe", 100, f"Transcripción completada: {len(transcription)} segmentos")

        # === PHASE 3: Find brand mentions ===
        update_status("brands", 0, "Buscando menciones de marcas...")

        mentions_by_brand = {}
        total_mentions = 0

        for seg in transcription:
            text = seg["text"]
            for brand_name, brand_info in aliases.items():
                for term in brand_info.get("terms", []):
                    if fuzzy_match(text, term):
                        if brand_name not in mentions_by_brand:
                            mentions_by_brand[brand_name] = {
                                "brand_id": brand_info.get("brand_id"),
                                "color": brand_info.get("color", "#6c5ce7"),
                                "count": 0,
                                "mentions": [],
                            }
                        mentions_by_brand[brand_name]["count"] += 1
                        mentions_by_brand[brand_name]["mentions"].append({
                            "start": seg["start"],
                            "end": seg["end"],
                            "start_fmt": seg["start_fmt"],
                            "end_fmt": seg["end_fmt"],
                            "text": text,
                            "matched_term": term,
                        })
                        total_mentions += 1
                        break  # Only count once per segment per brand

        # Save mentions
        result = {
            "video": os.path.basename(video_path),
            "total_mentions": total_mentions,
            "brands": mentions_by_brand,
            "processed_at": datetime.utcnow().isoformat(),
        }

        with open(os.path.join(output_dir, "brand_mentions.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # Final status
        final = {"status": "done", "phase": "done", "progress": 100, "total_mentions": total_mentions, "segments": len(transcription)}
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

    # Check if already running
    if video_stem in jobs and jobs[video_stem].get("status") == "running":
        return {"status": "already_running", "job": jobs[video_stem]}

    # Check if already done
    mentions_file = os.path.join(AUDIO_DIR, video_stem, "brand_mentions.json")
    if os.path.exists(mentions_file):
        # Re-process (delete old results)
        import shutil
        old_dir = os.path.join(AUDIO_DIR, video_stem)
        if os.path.exists(old_dir):
            shutil.rmtree(old_dir)

    # Start background processing
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
