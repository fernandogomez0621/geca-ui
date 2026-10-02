"""GPU Worker for YOLO training, inference, and video annotation"""
from fastapi import FastAPI
from pydantic import BaseModel
import os, json, time, subprocess, threading
import numpy as np
import cv2
import torch

app = FastAPI()

# Configuracion de YOLO: todo lo que escribe va a carpetas con permiso de escritura.
# /app es el codigo montado desde el servidor y el contenedor no puede escribir ahi.
import os
for _d in ("/mnt/shared/runs", "/tmp/ultralytics_weights", "/tmp/Ultralytics"):
    try:
        os.makedirs(_d, exist_ok=True)
    except Exception as _e:
        print(f"Aviso: no se pudo crear {_d}: {_e}")
try:
    from ultralytics import settings
    settings.update({"runs_dir": "/mnt/shared/runs", "datasets_dir": "/mnt/shared/datasets",
                     "weights_dir": "/tmp/ultralytics_weights"})
except Exception as _e:
    print(f"Aviso: no se pudo configurar ultralytics: {_e}")
# Cualquier archivo relativo que cree YOLO (ej. descargas) ira a /tmp, que siempre es escribible
try:
    os.chdir("/tmp")
except Exception:
    pass
SHARED = os.getenv("SHARED_DIR", "/mnt/shared")
tasks = {}  # task_id -> progress dict


class TrainRequest(BaseModel):
    dataset_name: str
    model_base: str = "yolo26m.pt"
    experiment_name: str = ""
    epochs: int = 100
    batch: int = 4
    patience: int = 50
    imgsz: int = 1280
    freeze: int = 0
    fliplr: float = 0.0
    profile: str = "estandar"   # pocos | medio | estandar
    lr0: float = 0.01
    cos_lr: bool = False
    mixup: float = 0.0
    copy_paste: float = 0.0
    scale: float = 0.5
    cls: float = 0.5


class InferenceRequest(BaseModel):
    model_name: str
    video_path: str
    fps_process: int = 10
    conf: float = 0.25
    batch_size: int = 32
    imgsz: int = 0              # 0 = usar la resolucion con la que se entreno el modelo
    smooth_seconds: float = 1.0 # huecos <= a este tiempo se consideran presencia continua
    review_frames: int = 60     # frames dificiles a guardar para reetiquetar (0 = desactivado)
    min_seconds: float = 0.3    # apariciones mas cortas se descartan (falsos positivos aislados)


class VideoRequest(BaseModel):
    model_name: str
    video_path: str
    resolution: int = 480
    conf: float = 0.25
    batch_size: int = 32
    crf: int = 28
    imgsz: int = 0
    hold_seconds: float = 0.5   # mantiene la caja visible si el modelo la pierde brevemente


# Perfiles de aumento de datos pensados para transmisiones deportivas:
# - sin volteo horizontal (los logos tienen texto)
# - variaciones de iluminacion (dia/noche, estadios distintos, LEDs encendidos)
# - variaciones de escala/posicion/perspectiva (zoom y paneos de camara)
# - mosaic para que el modelo vea logos en contextos y tamanos muy distintos
AUG_PROFILES = {
    "pocos": dict(mosaic=1.0, close_mosaic=20, scale=0.7, translate=0.25, degrees=3.0,
                  perspective=0.0005, shear=2.0, hsv_h=0.02, hsv_s=0.7, hsv_v=0.5,
                  cos_lr=True, warmup_epochs=5),
    "medio": dict(mosaic=1.0, close_mosaic=15, scale=0.6, translate=0.2, degrees=2.0,
                  perspective=0.0003, shear=1.0, hsv_h=0.015, hsv_s=0.7, hsv_v=0.45,
                  cos_lr=True, warmup_epochs=3),
    "estandar": dict(mosaic=1.0, close_mosaic=10, scale=0.5, translate=0.2, degrees=2.0,
                     perspective=0.0, shear=0.0, hsv_h=0.015, hsv_s=0.7, hsv_v=0.4,
                     cos_lr=False, warmup_epochs=3),
}


def resolve_imgsz(model, requested):
    """Usa la resolucion de entrenamiento del modelo si no se especifica."""
    if requested and requested > 0:
        return int(requested)
    try:
        ta = (getattr(model, "ckpt", None) or {}).get("train_args", {}) or {}
        v = ta.get("imgsz", 640)
        return int(v[0] if isinstance(v, (list, tuple)) else v)
    except Exception:
        return 640


def fill_gaps(presence, max_gap):
    """Rellena huecos cortos (<= max_gap) entre dos detecciones de la misma marca."""
    out = list(presence)
    n = len(out)
    i = 0
    last_true = -1
    while i < n:
        if out[i]:
            if last_true >= 0 and 0 < i - last_true - 1 <= max_gap:
                for k in range(last_true + 1, i):
                    out[k] = True
            last_true = i
        i += 1
    return out


def remove_short(presence, min_len):
    """Elimina apariciones (rachas de True) mas cortas que min_len frames."""
    out = list(presence)
    n = len(out)
    i = 0
    while i < n:
        if out[i]:
            j = i
            while j < n and out[j]:
                j += 1
            if j - i < min_len:
                for k in range(i, j):
                    out[k] = False
            i = j
        else:
            i += 1
    return out


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0


@app.get("/health")
def health():
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A"
    return {"status": "ok", "gpu": gpu, "cuda": torch.cuda.is_available()}


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    return tasks.get(task_id, {"status": "not_found"})


# ============ TRAINING ============

@app.post("/train")
def start_training(req: TrainRequest):
    task_id = f"train_{int(time.time())}"
    tasks[task_id] = {"status": "starting", "type": "train", "progress": 0, "epoch": 0, "total_epochs": req.epochs}
    t = threading.Thread(target=run_training, args=(task_id, req), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "started"}


def run_training(task_id, req):
    try:
        from ultralytics import YOLO

        model_path = os.path.join(SHARED, "models", req.model_base)
        yaml_path = os.path.join(SHARED, "datasets", "ready", req.dataset_name, "data.yaml")
        runs_dir = os.path.join(SHARED, "runs", "detect")
        exp_name = req.experiment_name or f"{req.dataset_name}_v1"

        if not os.path.exists(model_path):
            tasks[task_id] = {"status": "error", "message": f"Modelo {req.model_base} no encontrado"}
            return
        if not os.path.exists(yaml_path):
            tasks[task_id] = {"status": "error", "message": f"Dataset {req.dataset_name} no encontrado"}
            return

        tasks[task_id].update({"status": "loading_model", "experiment": exp_name})

        model = YOLO(model_path)

        # Custom callback to track progress
        def on_train_epoch_end(trainer):
            try:
                epoch = trainer.epoch + 1
                metrics = trainer.metrics or {}
                box_loss = None
                cls_loss = None
                try:
                    if trainer.loss_items is not None:
                        loss = trainer.loss_items.cpu().numpy() if hasattr(trainer.loss_items, 'cpu') else trainer.loss_items
                        box_loss = round(float(loss[0]), 4) if len(loss) > 0 else None
                        cls_loss = round(float(loss[1]), 4) if len(loss) > 1 else None
                except Exception:
                    pass
                mAP50 = 0
                mAP50_95 = 0
                try:
                    mAP50 = round(float(metrics.get("metrics/mAP50(B)", 0)), 4)
                    mAP50_95 = round(float(metrics.get("metrics/mAP50-95(B)", 0)), 4)
                except Exception:
                    pass
                tasks[task_id].update({
                    "status": "training",
                    "epoch": epoch,
                    "total_epochs": req.epochs,
                    "progress": round(epoch / req.epochs * 100, 1),
                    "box_loss": box_loss,
                    "cls_loss": cls_loss,
                    "mAP50": mAP50,
                    "mAP50_95": mAP50_95,
                })
            except Exception:
                pass

        model.add_callback("on_train_epoch_end", on_train_epoch_end)

        tasks[task_id].update({"status": "training", "epoch": 0})

        aug = dict(AUG_PROFILES.get(req.profile, AUG_PROFILES["estandar"]))
        # Con optimizer='auto' YOLO ignora lr0; se fija el optimizador para que el LR elegido se respete
        optimizer = "SGD" if req.lr0 >= 0.005 else "AdamW"
        # Cache en RAM si el dataset cabe (acelera mucho con pocos datos)
        try:
            n_train = len(os.listdir(os.path.join(os.path.dirname(yaml_path), "images", "train")))
        except Exception:
            n_train = 0
        cache = "ram" if 0 < n_train <= 3000 else False
        tasks[task_id].update({"profile": req.profile, "imgsz": req.imgsz, "n_train": n_train})

        results = model.train(
            data=yaml_path, epochs=req.epochs, imgsz=req.imgsz,
            batch=req.batch if req.batch > 0 else -1,   # -1 = AutoBatch segun memoria de la GPU
            device=0, patience=req.patience, name=exp_name, project=runs_dir,
            exist_ok=True, plots=True, mixup=req.mixup, copy_paste=req.copy_paste,
            fliplr=req.fliplr, freeze=req.freeze if req.freeze > 0 else None,
            optimizer=optimizer, lr0=req.lr0, cls=req.cls, cache=cache,
            **aug,
        )

        # Save best model
        best_path = os.path.join(runs_dir, exp_name, "weights", "best.pt")
        output_name = f"geca_{exp_name}_best.pt"
        output_path = os.path.join(SHARED, "models", output_name)
        if os.path.exists(best_path):
            import shutil
            shutil.copy(best_path, output_path)

        # Get final metrics
        best_model = YOLO(best_path)
        metrics = best_model.val(project=runs_dir, name=exp_name + "_val", exist_ok=True)

        # Log to MLflow
        try:
            import mlflow
            mlflow.set_tracking_uri("http://geca_mlflow:5000")
            mlflow.set_experiment("GECA_Training")
            with mlflow.start_run(run_name=exp_name):
                mlflow.log_param("dataset", req.dataset_name)
                mlflow.log_param("model_base", req.model_base)
                mlflow.log_param("epochs", req.epochs)
                mlflow.log_param("batch", req.batch)
                mlflow.log_param("experiment", exp_name)
                mlflow.log_metric("mAP50", float(metrics.box.map50))
                mlflow.log_metric("mAP50-95", float(metrics.box.map))
                mlflow.log_metric("mAP75", float(metrics.box.map75))
                try:
                    mlflow.log_artifact(output_path)
                except Exception:
                    pass
        except Exception as e:
            print(f"MLflow logging failed: {e}")

        tasks[task_id] = {
            "status": "done", "type": "train", "progress": 100,
            "epoch": req.epochs, "total_epochs": req.epochs,
            "experiment": exp_name,
            "model_saved": output_name,
            "mAP50": round(float(metrics.box.map50), 4),
            "mAP50_95": round(float(metrics.box.map), 4),
        }

    except Exception as e:
        tasks[task_id] = {"status": "error", "type": "train", "message": str(e)}


# ============ INFERENCE ============

@app.post("/inference")
def start_inference(req: InferenceRequest):
    task_id = f"inference_{int(time.time())}"
    tasks[task_id] = {"status": "starting", "type": "inference", "current": 0, "total": 0}
    t = threading.Thread(target=run_inference, args=(task_id, req), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "started"}


def run_inference(task_id, req):
    try:
        from ultralytics import YOLO
        from collections import defaultdict
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        model_path = os.path.join(SHARED, "models", req.model_name)
        model = YOLO(model_path)
        class_names = model.names

        cap = cv2.VideoCapture(req.video_path)
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not video_fps or video_fps <= 0:
            video_fps = 25.0
        frame_interval = max(1, int(round(video_fps / req.fps_process)))
        # FPS realmente analizados (ej. video 25 fps con intervalo 2 -> 12.5 fps).
        # TODOS los tiempos se calculan con este valor, no con el FPS solicitado.
        eff_fps = video_fps / frame_interval
        total_to_process = -(-total_frames // frame_interval)
        video_name = os.path.splitext(os.path.basename(req.video_path))[0]

        tasks[task_id].update({"status": "processing", "total": total_to_process, "video": video_name,
                               "effective_fps": round(eff_fps, 3)})

        imgsz = resolve_imgsz(model, req.imgsz)
        class_det = defaultdict(int)
        class_fc = defaultdict(int)
        frame_sets = []   # clases presentes en cada frame muestreado (en orden)
        frame_counts = [] # cantidad de cajas por clase en cada frame muestreado
        lowconf = []      # True si el frame tiene detecciones dudosas (confianza cercana al umbral)
        processed = 0
        idx = 0
        batch = []

        def run_batch(b):
            nonlocal processed
            if not b: return
            for r in model(b, conf=req.conf, imgsz=imgsz, verbose=False):
                fc = set()
                cnt = defaultdict(int)
                for box in r.boxes:
                    cn = class_names.get(int(box.cls.item()), "?")
                    class_det[cn] += 1
                    cnt[cn] += 1
                    fc.add(cn)
                for cn in fc:
                    class_fc[cn] += 1
                frame_sets.append(fc)
                frame_counts.append(dict(cnt))
                lowconf.append(any(float(bx.conf.item()) < req.conf + 0.15 for bx in r.boxes))
            processed += len(b)
            tasks[task_id].update({"current": processed, "annotations": sum(class_det.values())})

        while True:
            ret, frame = cap.read()
            if not ret: break
            if idx % frame_interval == 0:
                batch.append(frame)
                if len(batch) >= req.batch_size:
                    run_batch(batch)
                    batch = []
            idx += 1
        run_batch(batch)
        cap.release()

        # Generate Excel
        output_dir = os.path.join(SHARED, "results")
        os.makedirs(output_dir, exist_ok=True)

        # Suavizado temporal: rellena huecos cortos donde el modelo perdio la marca momentaneamente
        # 1) rellena huecos cortos  2) descarta apariciones demasiado cortas (falsos positivos)
        max_gap = int(round(req.smooth_seconds * eff_fps))
        min_len = max(1, int(round(req.min_seconds * eff_fps))) if req.min_seconds > 0 else 1
        smoothed, discarded = {}, {}
        for cn in list(class_det):
            pres = [cn in s for s in frame_sets]
            filled = fill_gaps(pres, max_gap) if max_gap > 0 else pres
            final = remove_short(filled, min_len) if min_len > 1 else filled
            smoothed[cn] = final
            discarded[cn] = [k for k, (a, b) in enumerate(zip(filled, final)) if a and not b and pres[k]]

        duration_s = processed / eff_fps if eff_fps else 0
        metrics_list = []
        for cn in class_det:
            final = smoothed[cn]
            # detecciones y frames reales que sobreviven al filtro de duracion minima
            kept_raw = [k for k, v in enumerate(final) if v and cn in frame_sets[k]]
            td = sum(frame_counts[k].get(cn, 0) for k in kept_raw)
            fw_raw = len(kept_raw)
            fw = sum(final)
            if fw == 0:
                continue
            metrics_list.append({
                "Etiqueta": cn, "Total detecciones": td, "Frames con deteccion": fw,
                "Media cuando aparece": round(td / fw_raw, 6) if fw_raw else 0,
                "Media total": round(td / processed, 6) if processed else 0,
                "Tiempo pantalla (s)": round(fw / eff_fps, 1),
                "Porcentaje tiempo (%)": round(fw / processed * 100, 6) if processed else 0,
                "Frames recuperados": fw - fw_raw,
                "Frames descartados": len(discarded[cn]),
            })
        metrics_list.sort(key=lambda m: -m["Frames con deteccion"])

        # ---- Aprendizaje activo: frames dificiles para reetiquetar ----
        # Prioridad 1: frames donde el modelo PERDIO una marca que estaba antes y despues (rellenados)
        # Prioridad 2: frames con detecciones de confianza dudosa
        review_saved = 0
        review_folder = f"{video_name}_revision"
        try:
            if req.review_frames > 0 and frame_sets:
                missed = set()
                for cn, pres in smoothed.items():
                    for k, v in enumerate(pres):
                        if v and cn not in frame_sets[k]:
                            missed.add(k)
                fps_cand = set(k for ks in discarded.values() for k in ks) - missed
                low = [k for k, v in enumerate(lowconf) if v and k not in missed and k not in fps_cand]
                min_gap = max(1, int(2 * eff_fps))   # al menos 2 s entre frames elegidos
                chosen = []
                def pick(cands):
                    for k in cands:
                        if len(chosen) >= req.review_frames: return
                        if all(abs(k - x) >= min_gap for x in chosen):
                            chosen.append(k)
                pick(sorted(missed))
                pick(sorted(fps_cand))
                # repartir los dudosos a lo largo del video
                if low and len(chosen) < req.review_frames:
                    step_l = max(1, len(low) // max(1, (req.review_frames - len(chosen)) * 3))
                    pick(low[::step_l])
                chosen.sort()
                if chosen:
                    tasks[task_id].update({"status": "saving_review"})
                    import shutil
                    rdir = os.path.join(SHARED, "frames", review_folder)
                    shutil.rmtree(rdir, ignore_errors=True)
                    os.makedirs(rdir, exist_ok=True)
                    cap2 = cv2.VideoCapture(req.video_path)
                    for n, k in enumerate(chosen, 1):
                        oi = k * frame_interval
                        cap2.set(cv2.CAP_PROP_POS_FRAMES, oi)
                        ok, fr = cap2.read()
                        if not ok: continue
                        t = int(oi / video_fps) if video_fps else 0
                        cv2.imwrite(os.path.join(rdir, f"{n:04d}_{t//3600:02d}h{(t%3600)//60:02d}m{t%60:02d}s.png"), fr)
                        review_saved += 1
                    cap2.release()
                    try:
                        os.chmod(rdir, 0o777)
                    except Exception:
                        pass
        except Exception as e:
            # Un fallo aqui (ej. permisos) NUNCA debe hacer perder el Excel de la inferencia
            print(f"Aviso: no se pudieron guardar los frames dificiles: {e}")
            tasks[task_id].update({"review_error": str(e)})
            review_saved = 0

        # Segmentos continuos de aparicion por marca (para verificar)
        segments = []
        for cn, pres in smoothed.items():
            start = None
            for i, v in enumerate(pres + [False]):
                if v and start is None:
                    start = i
                elif not v and start is not None:
                    s, e = start / eff_fps, i / eff_fps
                    segments.append((cn, s, e))
                    start = None
        segments.sort(key=lambda x: (x[1], x[0]))

        wb = Workbook()
        ws = wb.active
        ws.title = "Métricas"
        hf = Font(bold=True, color="FFFFFF", size=11)
        hfill = PatternFill(start_color="2E3440", end_color="2E3440", fill_type="solid")
        b = Border(left=Side(style="thin", color="CCCCCC"), right=Side(style="thin", color="CCCCCC"),
                   top=Side(style="thin", color="CCCCCC"), bottom=Side(style="thin", color="CCCCCC"))
        headers = ["Etiqueta", "Total detecciones", "Frames con deteccion", "Media cuando aparece",
                   "Media total", "Tiempo pantalla (s)", "Porcentaje tiempo (%)", "Frames recuperados",
                   "Frames descartados"]
        for col, h in enumerate(headers, 1):
            c = ws.cell(row=1, column=col, value=h)
            c.font, c.fill, c.alignment, c.border = hf, hfill, Alignment(horizontal="center"), b
        for ri, m in enumerate(metrics_list, 2):
            for col, key in enumerate(headers, 1):
                c = ws.cell(row=ri, column=col, value=m[key])
                c.border = b
        ws.column_dimensions["A"].width = 20
        for col in "BCDEFG":
            ws.column_dimensions[col].width = 22
        ws.column_dimensions["H"].width = 20
        ws.column_dimensions["I"].width = 20

        # Hoja de segmentos
        ws2 = wb.create_sheet("Apariciones")
        h2 = ["Etiqueta", "Inicio", "Fin", "Duracion (s)"]
        for col, h in enumerate(h2, 1):
            cc = ws2.cell(row=1, column=col, value=h)
            cc.font, cc.fill, cc.alignment = hf, hfill, Alignment(horizontal="center")
        def fmt(t):
            t = int(t); return f"{t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}"
        for ri, (cn, s, e) in enumerate(segments, 2):
            ws2.cell(row=ri, column=1, value=cn)
            ws2.cell(row=ri, column=2, value=fmt(s))
            ws2.cell(row=ri, column=3, value=fmt(e))
            ws2.cell(row=ri, column=4, value=round(e - s, 1))
        for col in "ABCD":
            ws2.column_dimensions[col].width = 18

        # Hoja de configuracion usada
        ws3 = wb.create_sheet("Configuracion")
        for ri, (k, v) in enumerate([("Modelo", req.model_name), ("FPS solicitados", req.fps_process),
                                     ("FPS del video", round(video_fps, 3)), ("FPS efectivos analizados", round(eff_fps, 3)),
                                     ("Duracion analizada (s)", round(duration_s, 1)),
                                     ("Duracion minima aparicion (s)", req.min_seconds),
                                     ("Confianza", req.conf), ("Resolucion analisis (px)", imgsz),
                                     ("Suavizado (s)", req.smooth_seconds), ("Frames analizados", processed),
                                     ("Frames dificiles guardados", review_saved)], 1):
            ws3.cell(row=ri, column=1, value=k).font = Font(bold=True)
            ws3.cell(row=ri, column=2, value=v)
        ws3.column_dimensions["A"].width = 26
        ws3.column_dimensions["B"].width = 30

        excel_path = os.path.join(output_dir, f"{video_name}_metrics.xlsx")
        wb.save(excel_path)

        # Generate presencia chart
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        labels = [m["Etiqueta"] for m in metrics_list]
        pcts = [m["Porcentaje tiempo (%)"] for m in metrics_list]
        colors = ["#6c5ce7", "#00b894", "#e17055", "#ffd43b", "#3b82f6", "#ef4444", "#10b981", "#f59e0b"]
        fig, ax = plt.subplots(figsize=(10, max(3, len(labels) * 0.6)))
        bars = ax.barh(labels, pcts, color=[colors[i % len(colors)] for i in range(len(labels))])
        ax.set_xlabel("Tiempo en pantalla (%)")
        ax.set_title(f"Presencia de Marcas — {video_name}", fontweight="bold")
        ax.invert_yaxis()
        for bar, p in zip(bars, pcts):
            ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2, f"{p:.1f}%", va="center", fontsize=9)
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, f"{video_name}_presencia.png"), dpi=150, bbox_inches="tight")
        plt.close()

        # Log to MLflow
        try:
            import mlflow
            mlflow.set_tracking_uri("http://geca_mlflow:5000")
            mlflow.set_experiment("GECA_Inference")
            with mlflow.start_run(run_name=f"inference_{video_name}"):
                mlflow.log_param("video", video_name)
                mlflow.log_param("model", req.model_name)
                mlflow.log_param("fps", req.fps_process)
                mlflow.log_param("conf", req.conf)
                for m in metrics_list:
                    mlflow.log_metric(f"{m['Etiqueta']}_pct", m["Porcentaje tiempo (%)"])
                try:
                    mlflow.log_artifact(excel_path)
                except Exception:
                    pass
        except Exception as e:
            print(f"MLflow logging failed: {e}")

        tasks[task_id] = {
            "status": "done", "type": "inference", "current": processed, "total": total_to_process,
            "video": video_name, "annotations": sum(class_det.values()),
            "review_frames": review_saved, "review_folder": review_folder if review_saved else None,
            "review_error": tasks[task_id].get("review_error"),
            "excel": f"{video_name}_metrics.xlsx", "metrics": metrics_list,
        }

    except Exception as e:
        tasks[task_id] = {"status": "error", "type": "inference", "message": str(e)}


# ============ VIDEO ANOTADO ============

@app.post("/video-annotate")
def start_video_annotate(req: VideoRequest):
    task_id = f"video_{int(time.time())}"
    tasks[task_id] = {"status": "starting", "type": "video", "current": 0, "total": 0}
    t = threading.Thread(target=run_video_annotate, args=(task_id, req), daemon=True)
    t.start()
    return {"task_id": task_id, "status": "started"}


def run_video_annotate(task_id, req):
    try:
        from ultralytics import YOLO
        from collections import defaultdict

        model_path = os.path.join(SHARED, "models", req.model_name)
        model = YOLO(model_path)
        class_names = model.names

        cap = cv2.VideoCapture(req.video_path)
        orig_fps = cap.get(cv2.CAP_PROP_FPS)
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_name = os.path.splitext(os.path.basename(req.video_path))[0]

        ratio = min(1, req.resolution / orig_h)
        out_w = int(orig_w * ratio)
        out_w = out_w if out_w % 2 == 0 else out_w + 1
        out_h = int(orig_h * ratio)
        out_h = out_h if out_h % 2 == 0 else out_h + 1

        output_dir = os.path.join(SHARED, "results")
        os.makedirs(output_dir, exist_ok=True)
        temp_path = os.path.join(output_dir, f"{video_name}_temp.mp4")
        output_path = os.path.join(output_dir, f"{video_name}_anotado_{req.resolution}p.mp4")

        COLORS = [(108, 92, 231), (0, 184, 148), (225, 112, 85), (255, 212, 59),
                  (59, 130, 246), (239, 68, 68), (16, 185, 129), (245, 158, 11)]

        writer = cv2.VideoWriter(temp_path, cv2.VideoWriter_fourcc(*"mp4v"), orig_fps, (out_w, out_h))

        tasks[task_id].update({"status": "processing", "total": total_frames, "video": video_name})

        imgsz = resolve_imgsz(model, req.imgsz)
        hold_frames = int(round(req.hold_seconds * orig_fps))
        class_det = defaultdict(int)
        class_fc = defaultdict(int)
        processed = 0
        batch_frames = []
        tracks = []          # [{cid, box, conf, last}]
        frame_no = 0

        def draw_and_write(batch_list):
            nonlocal processed, tracks, frame_no
            if not batch_list: return
            results = model(batch_list, conf=req.conf, imgsz=imgsz, verbose=False)
            sx, sy = out_w / orig_w, out_h / orig_h
            for result, frame in zip(results, batch_list):
                out = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA) if ratio < 1 else frame.copy()
                dets = []
                for box in result.boxes:
                    dets.append((int(box.cls.item()), float(box.conf.item()),
                                 [float(v) for v in box.xyxy[0].cpu().numpy()]))
                # Asociar detecciones con cajas previas (misma clase, IoU > 0.3)
                used = set()
                for cid, cf, bx in dets:
                    best, best_iou = None, 0.3
                    for ti, t in enumerate(tracks):
                        if ti in used or t["cid"] != cid: continue
                        v = iou(bx, t["box"])
                        if v > best_iou: best, best_iou = ti, v
                    if best is None:
                        tracks.append({"cid": cid, "box": bx, "conf": cf, "last": frame_no})
                        used.add(len(tracks) - 1)
                    else:
                        t = tracks[best]
                        t["box"] = [0.6 * n + 0.4 * o for n, o in zip(bx, t["box"])]  # suaviza el temblor
                        t["conf"], t["last"] = cf, frame_no
                        used.add(best)
                # Descartar cajas perdidas hace mas de hold_frames
                tracks = [t for t in tracks if frame_no - t["last"] <= hold_frames]
                fc = set()
                for t in tracks:
                    cid = t["cid"]
                    x1, y1, x2, y2 = [int(v) for v in (t["box"][0] * sx, t["box"][1] * sy, t["box"][2] * sx, t["box"][3] * sy)]
                    color = COLORS[cid % len(COLORS)]
                    cn = class_names.get(cid, str(cid))
                    cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
                    label = f"{cn} {t['conf']:.0%}"
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
                    cv2.rectangle(out, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
                    cv2.putText(out, label, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                    if t["last"] == frame_no:
                        class_det[cn] += 1
                    fc.add(cn)
                for cn in fc:
                    class_fc[cn] += 1
                writer.write(out)
                frame_no += 1
            processed += len(batch_list)
            tasks[task_id].update({"current": processed, "progress": round(processed / total_frames * 100, 1)})

        while True:
            ret, frame = cap.read()
            if not ret: break
            batch_frames.append(frame)
            if len(batch_frames) >= req.batch_size:
                draw_and_write(batch_frames)
                batch_frames = []
        draw_and_write(batch_frames)
        cap.release()
        writer.release()

        # Compress to H.264
        tasks[task_id].update({"status": "compressing"})
        subprocess.run(["ffmpeg", "-i", temp_path, "-c:v", "libx264", "-crf", str(req.crf),
                        "-preset", "fast", "-movflags", "+faststart", "-y", output_path],
                       capture_output=True)
        if os.path.exists(temp_path):
            os.remove(temp_path)

        mb = os.path.getsize(output_path) / 1024 / 1024

        tasks[task_id] = {
            "status": "done", "type": "video", "current": total_frames, "total": total_frames,
            "progress": 100, "video": video_name,
            "output": f"{video_name}_anotado_{req.resolution}p.mp4",
            "size_mb": round(mb, 1),
        }

    except Exception as e:
        tasks[task_id] = {"status": "error", "type": "video", "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
