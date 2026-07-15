"""
GECA Brands Manager - Backend API
Gestión de marcas, submarcas y contextos para detección en video deportivo.
Integración con CVAT para consulta de datasets.
Credenciales CVAT configurables desde la app.
"""

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import hashlib
import secrets
import os
import httpx

# --- Config ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://geca:geca_secret@geca_db:5432/geca_brands")
SECRET_KEY = os.getenv("SECRET_KEY", "geca-dev-secret-key-change-in-production")

# CVAT auth token cache
cvat_token: Optional[str] = None

# --- Database Setup ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ==============================================
#  MODELS
# ==============================================

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(20), default="annotator")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Context(Base):
    __tablename__ = "contexts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    subbrands = relationship("SubBrand", back_populates="context")


class Brand(Base):
    __tablename__ = "brands"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    logo_url = Column(Text, nullable=True)
    color = Column(String(7), default="#6c5ce7")
    client = Column(String(100), nullable=True)
    audio_aliases = Column(Text, nullable=True)  # comma-separated aliases for audio detection
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    subbrands = relationship("SubBrand", back_populates="brand", cascade="all, delete-orphan")


class SubBrand(Base):
    __tablename__ = "subbrands"
    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    context_id = Column(Integer, ForeignKey("contexts.id"), nullable=False)
    cvat_label = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    min_training_images = Column(Integer, default=200)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    brand = relationship("Brand", back_populates="subbrands")
    context = relationship("Context", back_populates="subbrands")


class AppSetting(Base):
    """Configuraciones de la app (CVAT credentials, etc.)"""
    __tablename__ = "app_settings"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ==============================================
#  PYDANTIC SCHEMAS
# ==============================================

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "annotator"

class UserOut(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserOut

class LoginRequest(BaseModel):
    username: str
    password: str

class ContextCreate(BaseModel):
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None

class ContextOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    icon: Optional[str]
    created_at: datetime
    class Config:
        from_attributes = True

class BrandCreate(BaseModel):
    name: str
    display_name: str
    logo_url: Optional[str] = None
    color: str = "#6c5ce7"
    client: Optional[str] = None
    audio_aliases: Optional[str] = None

class BrandUpdate(BaseModel):
    display_name: Optional[str] = None
    logo_url: Optional[str] = None
    color: Optional[str] = None
    client: Optional[str] = None
    audio_aliases: Optional[str] = None
    is_active: Optional[bool] = None

class BrandOut(BaseModel):
    id: int
    name: str
    display_name: str
    logo_url: Optional[str]
    color: str
    client: Optional[str]
    audio_aliases: Optional[str]
    is_active: bool
    created_at: datetime
    subbrands: list = []
    class Config:
        from_attributes = True

class SubBrandCreate(BaseModel):
    brand_id: int
    context_id: int
    cvat_label: str
    description: Optional[str] = None
    min_training_images: int = 200

class SubBrandUpdate(BaseModel):
    description: Optional[str] = None
    min_training_images: Optional[int] = None
    is_active: Optional[bool] = None

class CvatConfigIn(BaseModel):
    cvat_url: str
    cvat_host: str
    cvat_username: str
    cvat_password: str


# ==============================================
#  APP SETUP
# ==============================================

app = FastAPI(title="GECA Brands Manager", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

active_tokens: dict[str, int] = {}
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# ==============================================
#  DEPENDENCIES
# ==============================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    if not token or token not in active_tokens:
        raise HTTPException(status_code=401, detail="No autenticado")
    user = db.query(User).filter(User.id == active_tokens[token]).first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    return user

def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    return user

def get_setting(db: Session, key: str) -> Optional[str]:
    s = db.query(AppSetting).filter(AppSetting.key == key).first()
    return s.value if s else None

def set_setting(db: Session, key: str, value: str):
    s = db.query(AppSetting).filter(AppSetting.key == key).first()
    if s:
        s.value = value
        s.updated_at = datetime.utcnow()
    else:
        db.add(AppSetting(key=key, value=value))

def get_cvat_config(db: Session) -> dict:
    return {
        "cvat_url": get_setting(db, "cvat_url") or "",
        "cvat_host": get_setting(db, "cvat_host") or "",
        "cvat_username": get_setting(db, "cvat_username") or "",
        "cvat_password": get_setting(db, "cvat_password") or "",
    }


# ==============================================
#  STARTUP
# ==============================================

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(
            username="admin",
            email="admin@geca.com",
            password_hash=hash_password("admin123"),
            role="admin",
        ))

    if db.query(Context).count() == 0:
        db.add_all([
            Context(name="camiseta", description="Logo en camiseta de jugador", icon="👕"),
            Context(name="valla", description="Valla publicitaria lateral", icon="🏗️"),
            Context(name="anillo", description="Anillo LED perimetral del estadio", icon="💡"),
            Context(name="grada", description="Publicidad en gradas/asientos", icon="🏟️"),
            Context(name="cesped", description="Logo pintado en el césped", icon="🌱"),
            Context(name="pantalla", description="Pantalla gigante del estadio", icon="📺"),
        ])

    db.commit()
    db.close()


# ==============================================
#  AUTH ENDPOINTS
# ==============================================

@app.post("/api/auth/login", response_model=Token)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or user.password_hash != hash_password(data.password):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Usuario desactivado")
    token = secrets.token_hex(32)
    active_tokens[token] = user.id
    return Token(access_token=token, token_type="bearer", user=UserOut.model_validate(user))

@app.post("/api/auth/logout")
def logout(token: str = Depends(oauth2_scheme)):
    if token in active_tokens:
        del active_tokens[token]
    return {"status": "ok"}

@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


# ==============================================
#  USER ENDPOINTS
# ==============================================

@app.get("/api/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return db.query(User).all()

@app.post("/api/users", response_model=UserOut)
def create_user(data: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Username ya existe")
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Email ya existe")
    user = User(username=data.username, email=data.email, password_hash=hash_password(data.password), role=data.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ==============================================
#  CONTEXT ENDPOINTS
# ==============================================

@app.get("/api/contexts", response_model=list[ContextOut])
def list_contexts(db: Session = Depends(get_db)):
    return db.query(Context).all()

@app.post("/api/contexts", response_model=ContextOut)
def create_context(data: ContextCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if db.query(Context).filter(Context.name == data.name).first():
        raise HTTPException(400, "Contexto ya existe")
    ctx = Context(**data.model_dump())
    db.add(ctx)
    db.commit()
    db.refresh(ctx)
    return ctx

@app.delete("/api/contexts/{context_id}")
def delete_context(context_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    ctx = db.query(Context).filter(Context.id == context_id).first()
    if not ctx:
        raise HTTPException(404, "Contexto no encontrado")
    db.delete(ctx)
    db.commit()
    return {"status": "deleted"}


# ==============================================
#  BRAND ENDPOINTS
# ==============================================

@app.get("/api/brands", response_model=list[BrandOut])
def list_brands(db: Session = Depends(get_db)):
    brands = db.query(Brand).all()
    result = []
    for b in brands:
        bd = BrandOut.model_validate(b)
        bd.subbrands = [{"id": sb.id, "cvat_label": sb.cvat_label, "context": sb.context.name if sb.context else None, "context_icon": sb.context.icon if sb.context else None, "is_active": sb.is_active} for sb in b.subbrands]
        result.append(bd)
    return result

@app.get("/api/brands/{brand_id}", response_model=BrandOut)
def get_brand(brand_id: int, db: Session = Depends(get_db)):
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(404, "Marca no encontrada")
    bd = BrandOut.model_validate(brand)
    bd.subbrands = [{"id": sb.id, "cvat_label": sb.cvat_label, "context": sb.context.name if sb.context else None, "context_icon": sb.context.icon if sb.context else None, "description": sb.description, "min_training_images": sb.min_training_images, "is_active": sb.is_active} for sb in brand.subbrands]
    return bd

@app.post("/api/brands", response_model=BrandOut)
def create_brand(data: BrandCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if db.query(Brand).filter(Brand.name == data.name).first():
        raise HTTPException(400, "Marca ya existe")
    brand = Brand(**data.model_dump())
    db.add(brand)
    db.commit()
    db.refresh(brand)
    bd = BrandOut.model_validate(brand)
    bd.subbrands = []
    return bd

@app.put("/api/brands/{brand_id}", response_model=BrandOut)
def update_brand(brand_id: int, data: BrandUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(404, "Marca no encontrada")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(brand, key, value)
    db.commit()
    db.refresh(brand)
    return get_brand(brand_id, db)

@app.delete("/api/brands/{brand_id}")
def delete_brand(brand_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(404, "Marca no encontrada")
    db.delete(brand)
    db.commit()
    return {"status": "deleted"}


# ==============================================
#  SUBBRAND ENDPOINTS
# ==============================================

@app.get("/api/subbrands")
def list_subbrands(brand_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(SubBrand)
    if brand_id:
        query = query.filter(SubBrand.brand_id == brand_id)
    return [{
        "id": sb.id, "brand_id": sb.brand_id, "context_id": sb.context_id,
        "cvat_label": sb.cvat_label, "description": sb.description,
        "min_training_images": sb.min_training_images, "is_active": sb.is_active,
        "created_at": sb.created_at.isoformat() if sb.created_at else None,
        "brand_name": sb.brand.display_name if sb.brand else None,
        "context_name": sb.context.name if sb.context else None,
        "context_icon": sb.context.icon if sb.context else None,
    } for sb in query.all()]

@app.post("/api/subbrands")
def create_subbrand(data: SubBrandCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not db.query(Brand).filter(Brand.id == data.brand_id).first():
        raise HTTPException(400, "Marca no existe")
    if not db.query(Context).filter(Context.id == data.context_id).first():
        raise HTTPException(400, "Contexto no existe")
    if db.query(SubBrand).filter(SubBrand.cvat_label == data.cvat_label).first():
        raise HTTPException(400, f"Label '{data.cvat_label}' ya existe")
    sb = SubBrand(**data.model_dump())
    db.add(sb)
    db.commit()
    db.refresh(sb)
    return {"id": sb.id, "cvat_label": sb.cvat_label, "status": "created"}

@app.delete("/api/subbrands/{subbrand_id}")
def delete_subbrand(subbrand_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sb = db.query(SubBrand).filter(SubBrand.id == subbrand_id).first()
    if not sb:
        raise HTTPException(404, "Submarca no encontrada")
    db.delete(sb)
    db.commit()
    return {"status": "deleted"}


# ==============================================
#  CVAT SETTINGS ENDPOINTS
# ==============================================

@app.get("/api/settings/cvat")
def get_cvat_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cfg = get_cvat_config(db)
    # Don't send password to frontend, just indicate if it's set
    return {
        "cvat_url": cfg["cvat_url"],
        "cvat_host": cfg["cvat_host"],
        "cvat_username": cfg["cvat_username"],
        "has_password": bool(cfg["cvat_password"]),
        "configured": bool(cfg["cvat_url"] and cfg["cvat_username"] and cfg["cvat_password"]),
    }

@app.post("/api/settings/cvat")
def save_cvat_settings(data: CvatConfigIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    global cvat_token
    cvat_token = None  # Reset cached token

    set_setting(db, "cvat_url", data.cvat_url)
    set_setting(db, "cvat_host", data.cvat_host)
    set_setting(db, "cvat_username", data.cvat_username)
    set_setting(db, "cvat_password", data.cvat_password)
    db.commit()
    return {"status": "saved"}

@app.post("/api/settings/cvat/test")
async def test_cvat_connection(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cfg = get_cvat_config(db)
    if not cfg["cvat_url"] or not cfg["cvat_username"]:
        return {"connected": False, "error": "CVAT no configurado"}
    try:
        async with httpx.AsyncClient(base_url=cfg["cvat_url"], timeout=10, headers={"Host": cfg["cvat_host"]}) as client:
            resp = await client.post("/api/auth/login", json={
                "username": cfg["cvat_username"],
                "password": cfg["cvat_password"],
            })
            if resp.status_code == 200:
                return {"connected": True, "message": "Conexión exitosa"}
            return {"connected": False, "error": f"Error de autenticación ({resp.status_code})"}
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ==============================================
#  CVAT INTEGRATION
# ==============================================

async def get_cvat_client() -> Optional[httpx.AsyncClient]:
    """Creates an authenticated CVAT API client using DB settings"""
    global cvat_token

    db = SessionLocal()
    cfg = get_cvat_config(db)
    db.close()

    if not cfg["cvat_url"] or not cfg["cvat_username"]:
        return None

    headers = {"Host": cfg["cvat_host"]} if cfg["cvat_host"] else {}

    if not cvat_token:
        try:
            async with httpx.AsyncClient(base_url=cfg["cvat_url"], timeout=15, headers=headers) as tmp:
                resp = await tmp.post("/api/auth/login", json={
                    "username": cfg["cvat_username"],
                    "password": cfg["cvat_password"],
                })
                if resp.status_code == 200:
                    cvat_token = resp.json().get("key")
        except Exception:
            return None

    if cvat_token:
        headers["Authorization"] = f"Token {cvat_token}"

    return httpx.AsyncClient(base_url=cfg["cvat_url"], timeout=30, headers=headers)


@app.get("/api/cvat/labels/{cvat_label}")
async def get_cvat_label_stats(cvat_label: str, user: User = Depends(get_current_user)):
    client = await get_cvat_client()
    if not client:
        return {"label": cvat_label, "total_images": 0, "status": "not_configured", "samples": []}
    try:
        async with client:
            # Get labels to find which tasks have this label
            labels_resp = await client.get("/api/labels", params={"page_size": 500})
            if labels_resp.status_code != 200:
                return {"label": cvat_label, "total_images": 0, "status": "cvat_error", "samples": []}

            matching_tasks = []
            for l in labels_resp.json().get("results", []):
                if l["name"] == cvat_label and l.get("task_id"):
                    matching_tasks.append(l["task_id"])

            total_images = 0
            for task_id in matching_tasks:
                # Get task size (number of frames/images)
                task_resp = await client.get(f"/api/tasks/{task_id}")
                if task_resp.status_code == 200:
                    total_images += task_resp.json().get("size", 0)

            db = SessionLocal()
            sb = db.query(SubBrand).filter(SubBrand.cvat_label == cvat_label).first()
            min_images = sb.min_training_images if sb else 200
            db.close()

            return {
                "label": cvat_label,
                "total_images": total_images,
                "min_required": min_images,
                "ready_to_train": total_images >= min_images,
                "progress_pct": min(100, round(total_images / min_images * 100)) if min_images > 0 else 0,
            }
    except Exception as e:
        return {"label": cvat_label, "total_images": 0, "status": f"error: {str(e)}", "samples": []}


@app.get("/api/cvat/tasks")
async def list_cvat_tasks(user: User = Depends(get_current_user)):
    client = await get_cvat_client()
    if not client:
        return {"tasks": [], "status": "not_configured"}
    try:
        async with client:
            resp = await client.get("/api/tasks", params={"page_size": 100})
            if resp.status_code != 200:
                return {"tasks": [], "status": f"cvat_error_{resp.status_code}"}

            labels_resp = await client.get("/api/labels", params={"page_size": 500})
            labels_by_task = {}
            if labels_resp.status_code == 200:
                for l in labels_resp.json().get("results", []):
                    tid = l.get("task_id")
                    if tid:
                        labels_by_task.setdefault(tid, []).append(l["name"])

            return {"tasks": [{
                "id": t["id"],
                "name": t["name"],
                "status": t.get("status", "unknown"),
                "size": t.get("size", 0),
                "labels": labels_by_task.get(t["id"], []),
                "created_date": t.get("created_date"),
            } for t in resp.json().get("results", [])]}
    except Exception as e:
        return {"tasks": [], "status": f"error: {str(e)}"}


# ==============================================
#  BRAND MAP & STATS
# ==============================================

@app.get("/api/brand-map")
def get_brand_map(db: Session = Depends(get_db)):
    subbrands = db.query(SubBrand).filter(SubBrand.is_active == True).all()
    return {"brand_map": {
        sb.cvat_label: {"brand": sb.brand.display_name, "brand_id": sb.brand.id, "context": sb.context.name, "context_id": sb.context.id, "color": sb.brand.color}
        for sb in subbrands
    }}

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "total_brands": db.query(Brand).filter(Brand.is_active == True).count(),
        "total_subbrands": db.query(SubBrand).filter(SubBrand.is_active == True).count(),
        "total_contexts": db.query(Context).count(),
        "total_users": db.query(User).filter(User.is_active == True).count(),
    }


# ==============================================
#  VIDEOS ENDPOINTS
# ==============================================

VIDEOS_DIR = os.getenv("VIDEOS_DIR", "/mnt/shared/videos")
FRAMES_DIR = os.getenv("FRAMES_DIR", "/mnt/shared/frames")

# Track extraction jobs in memory
extraction_jobs: dict[str, dict] = {}

def get_video_info(filepath: str) -> dict:
    """Get video file info including duration if ffprobe available"""
    stat = os.stat(filepath)
    size_bytes = stat.st_size
    name = os.path.basename(filepath)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if size_bytes >= 1_000_000_000:
        size_str = f"{size_bytes / 1_000_000_000:.1f} GB"
    elif size_bytes >= 1_000_000:
        size_str = f"{size_bytes / 1_000_000:.1f} MB"
    else:
        size_str = f"{size_bytes / 1_000:.1f} KB"

    info = {
        "name": name,
        "path": filepath,
        "size_bytes": size_bytes,
        "size": size_str,
        "extension": ext,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "duration_secs": 0,
        "duration": "—",
    }

    try:
        import subprocess
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", filepath],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            import json as _json
            data = _json.loads(result.stdout)
            duration_secs = float(data.get("format", {}).get("duration", 0))
            hours = int(duration_secs // 3600)
            minutes = int((duration_secs % 3600) // 60)
            seconds = int(duration_secs % 60)
            info["duration_secs"] = round(duration_secs)
            info["duration"] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    except Exception:
        pass

    # Check if frames exist
    video_stem = os.path.splitext(name)[0]
    frames_path = os.path.join(FRAMES_DIR, video_stem)
    if os.path.isdir(frames_path):
        frame_files = [f for f in os.listdir(frames_path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        info["frames_count"] = len(frame_files)
        info["frames_folder"] = video_stem
    else:
        info["frames_count"] = 0
        info["frames_folder"] = None

    # Check extraction status
    if name in extraction_jobs:
        info["extraction_status"] = extraction_jobs[name]

    return info


def extract_frames_worker(video_path: str, output_dir: str, interval: float, job_key: str):
    """Background worker to extract frames from video"""
    import cv2
    import math

    try:
        extraction_jobs[job_key] = {"status": "running", "progress": 0, "total": 0, "extracted": 0}
        os.makedirs(output_dir, exist_ok=True)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            extraction_jobs[job_key] = {"status": "error", "message": "No se pudo abrir el video"}
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)

        if fps <= 0:
            fps = 25.0

        duration_sec = total_frames / fps if total_frames > 0 else 0
        num_capturas = math.floor(duration_sec / interval) + 1 if duration_sec > 0 else 0

        extraction_jobs[job_key]["total"] = num_capturas

        guardadas = 0
        for idx in range(num_capturas):
            t = idx * interval
            target_frame = int(round(t * fps))

            if total_frames > 0 and target_frame >= total_frames:
                break

            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ok, frame = cap.read()

            if not ok or frame is None:
                recovered = False
                for delta in (-1, 1, -2, 2):
                    alt = target_frame + delta
                    if alt < 0 or (total_frames and alt >= total_frames):
                        continue
                    cap.set(cv2.CAP_PROP_POS_FRAMES, alt)
                    ok2, frame2 = cap.read()
                    if ok2 and frame2 is not None:
                        frame = frame2
                        recovered = True
                        break
                if not recovered:
                    break

            out_name = f"{guardadas + 1:04d}.png"
            cv2.imwrite(os.path.join(output_dir, out_name), frame)
            guardadas += 1
            extraction_jobs[job_key]["extracted"] = guardadas
            extraction_jobs[job_key]["progress"] = round(guardadas / num_capturas * 100)

        cap.release()
        extraction_jobs[job_key] = {"status": "done", "extracted": guardadas, "total": num_capturas, "progress": 100}

    except Exception as e:
        extraction_jobs[job_key] = {"status": "error", "message": str(e)}


@app.get("/api/videos")
def list_videos(user: User = Depends(get_current_user)):
    if not os.path.exists(VIDEOS_DIR):
        return {"videos": [], "status": "folder_not_found", "path": VIDEOS_DIR}

    video_extensions = {".mp4", ".ts", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".mts", ".m2ts"}
    videos = []
    for entry in sorted(os.listdir(VIDEOS_DIR)):
        filepath = os.path.join(VIDEOS_DIR, entry)
        if os.path.isfile(filepath):
            ext = os.path.splitext(entry)[1].lower()
            if ext in video_extensions:
                videos.append(get_video_info(filepath))

    return {"videos": videos, "total": len(videos), "path": VIDEOS_DIR}


@app.get("/api/videos/{filename}/info")
def get_video_detail(filename: str, user: User = Depends(get_current_user)):
    filepath = os.path.join(VIDEOS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Video no encontrado")
    return get_video_info(filepath)


class ExtractRequest(BaseModel):
    interval: float = 10.0

@app.post("/api/videos/{filename}/extract")
def extract_frames(filename: str, data: ExtractRequest, user: User = Depends(get_current_user)):
    """Inicia extracción de frames en background"""
    import math
    filepath = os.path.join(VIDEOS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Video no encontrado")

    video_stem = os.path.splitext(filename)[0]
    output_dir = os.path.join(FRAMES_DIR, video_stem)

    # Check if already running
    if filename in extraction_jobs and extraction_jobs[filename].get("status") == "running":
        return {"status": "already_running", "job": extraction_jobs[filename]}

    # Estimate frames
    info = get_video_info(filepath)
    duration = info.get("duration_secs", 0)
    estimated = math.floor(duration / data.interval) + 1 if duration > 0 else 0

    # Start background thread
    import threading
    thread = threading.Thread(
        target=extract_frames_worker,
        args=(filepath, output_dir, data.interval, filename),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "estimated_frames": estimated, "interval": data.interval, "output_dir": video_stem}


@app.get("/api/videos/{filename}/extract/status")
def get_extraction_status(filename: str, user: User = Depends(get_current_user)):
    if filename in extraction_jobs:
        return extraction_jobs[filename]
    # Check if frames folder exists
    video_stem = os.path.splitext(filename)[0]
    frames_path = os.path.join(FRAMES_DIR, video_stem)
    if os.path.isdir(frames_path):
        count = len([f for f in os.listdir(frames_path) if f.lower().endswith(('.png', '.jpg'))])
        return {"status": "done", "extracted": count}
    return {"status": "not_started"}


@app.get("/api/frames/{folder}")
def list_frames(folder: str, page: int = 1, per_page: int = 20, user: User = Depends(get_current_user)):
    """Lista frames extraídos con paginación y thumbnails"""
    frames_path = os.path.join(FRAMES_DIR, folder)
    if not os.path.isdir(frames_path):
        raise HTTPException(404, "Carpeta de frames no encontrada")

    all_frames = sorted([f for f in os.listdir(frames_path) if f.lower().endswith(('.png', '.jpg', '.jpeg')) and 'thumbs' not in f])
    total = len(all_frames)
    start = (page - 1) * per_page
    end = start + per_page
    page_frames = all_frames[start:end]

    # Auto-generate thumbs for this page if missing
    thumb_dir = os.path.join(frames_path, "thumbs")
    os.makedirs(thumb_dir, exist_ok=True)
    for f in page_frames:
        thumb_name = f.rsplit('.', 1)[0] + '.jpg'
        thumb_path = os.path.join(thumb_dir, thumb_name)
        if not os.path.exists(thumb_path):
            try:
                import cv2
                img = cv2.imread(os.path.join(frames_path, f))
                if img is not None:
                    h, w = img.shape[:2]
                    new_w, new_h = 320, int(320 * h / w)
                    img = cv2.resize(img, (new_w, new_h))
                    cv2.imwrite(thumb_path, img, [cv2.IMWRITE_JPEG_QUALITY, 75])
            except Exception:
                pass

    return {
        "folder": folder,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": math.ceil(total / per_page) if total > 0 else 0,
        "frames": [{
            "name": f,
            "url": f"/api/frames/{folder}/{f}",
            "thumb_url": f"/api/frames/{folder}/thumbs/{f.rsplit('.', 1)[0]}.jpg",
        } for f in page_frames],
    }


from fastapi.responses import FileResponse
import math

@app.get("/api/frames/{folder}/thumbs/{thumb_name}")
def get_frame_thumb(folder: str, thumb_name: str):
    """Sirve un thumbnail de frame"""
    filepath = os.path.join(FRAMES_DIR, folder, "thumbs", thumb_name)
    if not os.path.exists(filepath):
        # Fallback to original
        orig = thumb_name.rsplit('.', 1)[0] + '.png'
        filepath = os.path.join(FRAMES_DIR, folder, orig)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Thumb no encontrado")
    return FileResponse(filepath)


@app.get("/api/frames/{folder}/{frame_name}")
def get_frame_image(folder: str, frame_name: str):
    """Sirve una imagen de frame"""
    filepath = os.path.join(FRAMES_DIR, folder, frame_name)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Frame no encontrado")
    return FileResponse(filepath)


@app.delete("/api/frames/{folder}/{frame_name}")
def delete_frame(folder: str, frame_name: str, user: User = Depends(get_current_user)):
    """Elimina un frame individual"""
    filepath = os.path.join(FRAMES_DIR, folder, frame_name)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Frame no encontrado")
    os.remove(filepath)
    return {"deleted": frame_name}


class DeleteBatchRequest(BaseModel):
    frames: list[str] = []

@app.post("/api/frames/{folder}/delete-batch")
def delete_frames_batch(folder: str, data: DeleteBatchRequest, user: User = Depends(get_current_user)):
    """Elimina multiples frames"""
    frames_path = os.path.join(FRAMES_DIR, folder)
    deleted = 0
    for f in data.frames:
        fp = os.path.join(frames_path, f)
        if os.path.exists(fp):
            os.remove(fp)
            deleted += 1
    remaining = len([f for f in os.listdir(frames_path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]) if os.path.isdir(frames_path) else 0
    return {"deleted": deleted, "remaining": remaining}


class CreateCvatTaskRequest(BaseModel):
    task_name: str
    labels: list[str] = []

@app.post("/api/frames/{folder}/create-cvat-task")
async def create_cvat_task_from_frames(folder: str, data: CreateCvatTaskRequest, user: User = Depends(get_current_user)):
    """Crea una tarea en CVAT y sube los frames directamente (servidor a servidor via ZIP)"""
    frames_path = os.path.join(FRAMES_DIR, folder)
    if not os.path.isdir(frames_path):
        raise HTTPException(404, "Carpeta de frames no encontrada")

    frame_files = sorted([f for f in os.listdir(frames_path) if f.lower().endswith(('.png', '.jpg', '.jpeg')) and f != 'thumbs'])
    if not frame_files:
        return {"status": "error", "message": "No hay frames en la carpeta"}

    # Get CVAT config
    db = SessionLocal()
    cfg = get_cvat_config(db)
    db.close()
    if not cfg["cvat_url"] or not cfg["cvat_username"]:
        return {"status": "error", "message": "CVAT no configurado"}

    try:
        headers = {"Host": cfg["cvat_host"]} if cfg["cvat_host"] else {}

        # 1. Login to CVAT
        async with httpx.AsyncClient(base_url=cfg["cvat_url"], timeout=30, headers=headers) as client:
            resp = await client.post("/api/auth/login", json={
                "username": cfg["cvat_username"],
                "password": cfg["cvat_password"],
            })
            if resp.status_code != 200:
                return {"status": "error", "message": "No se pudo autenticar con CVAT"}
            token = resp.json().get("key")

        # 2. Create task with labels
        auth_headers = {**headers, "Authorization": f"Token {token}"}
        labels_payload = [{"name": l, "attributes": []} for l in data.labels] if data.labels else []

        async with httpx.AsyncClient(base_url=cfg["cvat_url"], timeout=60, headers=auth_headers) as client:
            resp = await client.post("/api/tasks", json={
                "name": data.task_name,
                "labels": labels_payload,
            })
            if resp.status_code not in (200, 201):
                return {"status": "error", "message": f"Error creando tarea: {resp.text[:200]}"}
            task_id = resp.json()["id"]

        # 3. Create ZIP of all frames
        import zipfile, io, tempfile
        zip_path = os.path.join(tempfile.gettempdir(), f"cvat_upload_{folder}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
            for fname in frame_files:
                fpath = os.path.join(frames_path, fname)
                zf.write(fpath, fname)

        # 4. Upload ZIP to CVAT (single request)
        with open(zip_path, "rb") as zf:
            zip_data = zf.read()

        async with httpx.AsyncClient(base_url=cfg["cvat_url"], timeout=600, headers=auth_headers) as client:
            resp = await client.post(
                f"/api/tasks/{task_id}/data",
                data={"image_quality": 70},
                files={"client_files[0]": (f"{folder}.zip", zip_data, "application/zip")},
            )
            if resp.status_code not in (200, 201, 202):
                return {"status": "error", "message": f"Error subiendo frames: {resp.status_code} {resp.text[:200]}"}

        # 5. Cleanup
        os.remove(zip_path)

        return {
            "status": "ok",
            "task_id": task_id,
            "task_name": data.task_name,
            "frames_uploaded": len(frame_files),
            "labels": data.labels,
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==============================================
#  AUDIO PROCESSING ENDPOINTS
# ==============================================

AUDIO_DIR = os.getenv("AUDIO_DIR", "/mnt/shared/audio")
WHISPER_URL = os.getenv("WHISPER_URL", "http://geca_whisper:8001")


@app.get("/api/brands/aliases")
def get_all_aliases(db: Session = Depends(get_db)):
    """Returns all brand aliases for whisper brand matching"""
    brands = db.query(Brand).filter(Brand.is_active == True).all()
    aliases_map = {}
    for b in brands:
        terms = [b.name.lower(), b.display_name.lower()]
        if b.audio_aliases:
            for a in b.audio_aliases.split(","):
                a = a.strip().lower()
                if a:
                    terms.append(a)
        aliases_map[b.display_name] = {
            "brand_id": b.id,
            "color": b.color,
            "terms": list(set(terms)),
        }
    return {"aliases": aliases_map}


@app.post("/api/videos/{filename}/process-audio")
async def process_audio(filename: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Triggers audio extraction, transcription and brand matching"""
    filepath = os.path.join(VIDEOS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Video no encontrado")

    # Get brand aliases
    brands = db.query(Brand).filter(Brand.is_active == True).all()
    aliases_map = {}
    brand_names = []
    for b in brands:
        terms = [b.name.lower(), b.display_name.lower()]
        if b.audio_aliases:
            for a in b.audio_aliases.split(","):
                a = a.strip().lower()
                if a:
                    terms.append(a)
        aliases_map[b.display_name] = {"brand_id": b.id, "color": b.color, "terms": list(set(terms))}
        brand_names.append(b.display_name)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{WHISPER_URL}/transcribe", json={
                "video_path": filepath,
                "aliases": aliases_map,
                "brand_names": brand_names,
            })
            return resp.json()
    except Exception as e:
        return {"status": "error", "message": f"No se pudo conectar con el servicio whisper: {str(e)}"}


@app.get("/api/videos/{filename}/audio/status")
def get_audio_status(filename: str, user: User = Depends(get_current_user)):
    """Gets audio processing status"""
    video_stem = os.path.splitext(filename)[0]
    audio_dir = os.path.join(AUDIO_DIR, video_stem)

    # Check if results exist
    mentions_file = os.path.join(audio_dir, "brand_mentions.json")
    transcription_file = os.path.join(audio_dir, "transcription.json")
    status_file = os.path.join(audio_dir, "status.json")

    if os.path.exists(status_file):
        import json
        with open(status_file) as f:
            return json.load(f)

    if os.path.exists(mentions_file):
        return {"status": "done"}

    return {"status": "not_started"}


@app.get("/api/videos/{filename}/mentions")
def get_mentions(filename: str, user: User = Depends(get_current_user)):
    """Gets brand mentions from transcription"""
    video_stem = os.path.splitext(filename)[0]
    mentions_file = os.path.join(AUDIO_DIR, video_stem, "brand_mentions.json")

    if not os.path.exists(mentions_file):
        return {"mentions": [], "status": "not_processed"}

    import json
    with open(mentions_file) as f:
        return json.load(f)


@app.get("/api/videos/{filename}/transcription")
def get_transcription(
    filename: str,
    page: int = 1,
    per_page: int = 30,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    search: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    """Gets transcription with pagination and time/text filters"""
    video_stem = os.path.splitext(filename)[0]
    trans_file = os.path.join(AUDIO_DIR, video_stem, "transcription.json")

    if not os.path.exists(trans_file):
        return {"segments": [], "status": "not_processed", "total": 0}

    import json as _json
    with open(trans_file) as f:
        data = _json.load(f)

    segments = data.get("segments", [])

    # Filter by time
    if start_time is not None:
        segments = [s for s in segments if s["end"] >= start_time]
    if end_time is not None:
        segments = [s for s in segments if s["start"] <= end_time]

    # Filter by search text
    if search:
        search_lower = search.lower()
        segments = [s for s in segments if search_lower in s["text"].lower()]

    total = len(segments)
    total_pages = math.ceil(total / per_page) if total > 0 else 0
    start_idx = (page - 1) * per_page
    page_segments = segments[start_idx:start_idx + per_page]

    return {
        "segments": page_segments,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "language": data.get("language"),
        "duration": data.get("duration"),
    }


@app.get("/api/videos/{filename}/analytics")
def get_analytics(filename: str, user: User = Depends(get_current_user)):
    """Generates analytics data from transcription and mentions"""
    import json as _json

    video_stem = os.path.splitext(filename)[0]
    mentions_file = os.path.join(AUDIO_DIR, video_stem, "brand_mentions.json")
    trans_file = os.path.join(AUDIO_DIR, video_stem, "transcription.json")

    if not os.path.exists(mentions_file):
        return {"status": "not_processed"}

    with open(mentions_file) as f:
        mentions_data = _json.load(f)

    duration = 0
    total_segments = 0
    if os.path.exists(trans_file):
        with open(trans_file) as f:
            trans_data = _json.load(f)
        duration = trans_data.get("duration", 0)
        total_segments = len(trans_data.get("segments", []))

    brands = mentions_data.get("brands", {})

    # Summary
    total_mentions = mentions_data.get("total_mentions", 0)
    total_brands = len(brands)

    # Mentions per brand (for bar chart)
    brands_chart = []
    for name, info in sorted(brands.items(), key=lambda x: -x[1]["count"]):
        brands_chart.append({
            "name": name,
            "mentions": info["count"],
            "duration": info.get("total_duration", 0),
            "color": info.get("color", "#6c5ce7"),
        })

    # Timeline: mentions distributed in 5-minute intervals
    interval_minutes = 5
    timeline = []
    if duration > 0:
        num_intervals = math.ceil(duration / (interval_minutes * 60))
        for i in range(num_intervals):
            start = i * interval_minutes * 60
            end = (i + 1) * interval_minutes * 60
            h1 = int(start // 3600)
            m1 = int((start % 3600) // 60)
            label = f"{h1:02d}:{m1:02d}"
            interval_data = {"time": label, "total": 0}
            for bname, info in brands.items():
                count = sum(1 for m in info.get("mentions", []) if start <= m["start"] < end)
                interval_data[bname] = count
                interval_data["total"] += count
            timeline.append(interval_data)

    # Precise mention duration from word timestamps
    total_mention_duration = mentions_data.get("total_mention_duration", 0)
    if total_mention_duration == 0:
        # Fallback: sum from individual brands
        for bname, info in brands.items():
            total_mention_duration += info.get("total_duration", 0)
    coverage_pct = round(total_mention_duration / duration * 100, 2) if duration > 0 else 0

    # First and last mention per brand
    brand_details = []
    for name, info in brands.items():
        m_list = info.get("mentions", [])
        if m_list:
            brand_details.append({
                "name": name,
                "count": info["count"],
                "color": info.get("color", "#6c5ce7"),
                "total_duration": info.get("total_duration", 0),
                "avg_duration": round(info.get("total_duration", 0) / max(info["count"], 1), 2),
                "first_mention": m_list[0]["start_fmt"],
                "last_mention": m_list[-1]["start_fmt"],
                "avg_interval": round((m_list[-1]["start"] - m_list[0]["start"]) / max(len(m_list) - 1, 1)),
            })

    # Duration formatted
    dur_h = int(duration // 3600)
    dur_m = int((duration % 3600) // 60)
    dur_s = int(duration % 60)

    return {
        "video": filename,
        "duration": duration,
        "duration_fmt": f"{dur_h:02d}:{dur_m:02d}:{dur_s:02d}",
        "total_segments": total_segments,
        "total_mentions": total_mentions,
        "total_mention_duration": round(total_mention_duration, 2),
        "total_brands": total_brands,
        "coverage_pct": coverage_pct,
        "brands_chart": brands_chart,
        "timeline": timeline,
        "brand_names": list(brands.keys()),
        "brand_details": brand_details,
        "processed_at": mentions_data.get("processed_at"),
    }


# ==============================================
#  SQL SERVER SYNC
# ==============================================

SQLSERVER_HOST = os.getenv("SQLSERVER_HOST", "")
SQLSERVER_PORT = int(os.getenv("SQLSERVER_PORT", "1433"))
SQLSERVER_DB = os.getenv("SQLSERVER_DB", "")
SQLSERVER_USER = os.getenv("SQLSERVER_USER", "")
SQLSERVER_PASSWORD = os.getenv("SQLSERVER_PASSWORD", "")


def get_mssql_conn():
    """Get SQL Server connection"""
    if not SQLSERVER_HOST or not SQLSERVER_USER:
        return None
    try:
        import pymssql
        conn = pymssql.connect(
            server=SQLSERVER_HOST,
            port=SQLSERVER_PORT,
            user=SQLSERVER_USER,
            password=SQLSERVER_PASSWORD,
            database=SQLSERVER_DB,
            charset="utf8",
        )
        return conn
    except Exception as e:
        print(f"SQL Server connection error: {e}")
        return None


def sync_to_sqlserver(filename: str):
    """Sync audio processing results to SQL Server"""
    import json as _json

    conn = get_mssql_conn()
    if not conn:
        return {"status": "error", "message": "No SQL Server connection configured"}

    video_stem = os.path.splitext(filename)[0]
    mentions_file = os.path.join(AUDIO_DIR, video_stem, "brand_mentions.json")
    trans_file = os.path.join(AUDIO_DIR, video_stem, "transcription.json")

    if not os.path.exists(mentions_file):
        return {"status": "error", "message": "No audio results found for this video"}

    with open(mentions_file) as f:
        mentions_data = _json.load(f)

    trans_segments = []
    language = None
    if os.path.exists(trans_file):
        with open(trans_file) as f:
            trans_data = _json.load(f)
        trans_segments = trans_data.get("segments", [])
        language = trans_data.get("language")

    try:
        cursor = conn.cursor()

        # Get video info
        video_path = os.path.join(VIDEOS_DIR, filename)
        duration = mentions_data.get("duration", 0)
        size_bytes = os.path.getsize(video_path) if os.path.exists(video_path) else 0
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        dur_h = int((duration or 0) // 3600)
        dur_m = int(((duration or 0) % 3600) // 60)
        dur_s = int((duration or 0) % 60)
        duration_fmt = f"{dur_h:02d}:{dur_m:02d}:{dur_s:02d}"

        # 1. Upsert video
        cursor.execute("SELECT id FROM dbo.geca_videos WHERE filename = %s", (filename,))
        row = cursor.fetchone()
        if row:
            video_id = row[0]
            cursor.execute("""
                UPDATE dbo.geca_videos SET duration_secs=%s, duration_fmt=%s,
                file_size_bytes=%s, format=%s, language=%s WHERE id=%s
            """, (duration, duration_fmt, size_bytes, ext, language, video_id))
        else:
            cursor.execute("""
                INSERT INTO dbo.geca_videos (filename, duration_secs, duration_fmt, file_size_bytes, format, language)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (filename, duration, duration_fmt, size_bytes, ext, language))
            cursor.execute("SELECT SCOPE_IDENTITY()")
            video_id = int(cursor.fetchone()[0])

        # 2. Sync brands
        brand_id_map = {}
        for brand_name, info in mentions_data.get("brands", {}).items():
            cursor.execute("SELECT id FROM dbo.geca_brands WHERE display_name = %s", (brand_name,))
            row = cursor.fetchone()
            if row:
                brand_id_map[brand_name] = row[0]
            else:
                cursor.execute("""
                    INSERT INTO dbo.geca_brands (name, display_name, color)
                    VALUES (%s, %s, %s)
                """, (brand_name.lower().replace(" ", "_"), brand_name, info.get("color", "#6c5ce7")))
                cursor.execute("SELECT SCOPE_IDENTITY()")
                brand_id_map[brand_name] = int(cursor.fetchone()[0])

        # 3. Clear old data for this video
        cursor.execute("DELETE FROM dbo.geca_video_brand_summary WHERE video_id = %s", (video_id,))
        cursor.execute("DELETE FROM dbo.geca_audio_mentions WHERE video_id = %s", (video_id,))
        cursor.execute("DELETE FROM dbo.geca_transcription_segments WHERE video_id = %s", (video_id,))
        cursor.execute("DELETE FROM dbo.geca_audio_jobs WHERE video_id = %s", (video_id,))

        # 4. Insert audio job
        cursor.execute("""
            INSERT INTO dbo.geca_audio_jobs (video_id, status, phase, total_segments, total_mentions,
            total_mention_duration, coverage_pct, completed_at)
            VALUES (%s, 'done', 'done', %s, %s, %s, %s, GETDATE())
        """, (video_id, len(trans_segments), mentions_data.get("total_mentions", 0),
              mentions_data.get("total_mention_duration", 0),
              mentions_data.get("mention_coverage_pct", 0)))

        # 5. Insert transcription segments
        segment_id_map = {}
        for i, seg in enumerate(trans_segments):
            cursor.execute("""
                INSERT INTO dbo.geca_transcription_segments
                (video_id, segment_index, start_time, end_time, start_fmt, end_fmt, segment_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (video_id, i, seg["start"], seg["end"], seg["start_fmt"], seg["end_fmt"], seg["text"]))
            cursor.execute("SELECT SCOPE_IDENTITY()")
            segment_id_map[i] = int(cursor.fetchone()[0])

        # 6. Insert mentions
        for brand_name, info in mentions_data.get("brands", {}).items():
            brand_id = brand_id_map.get(brand_name)
            if not brand_id:
                continue
            for m in info.get("mentions", []):
                cursor.execute("""
                    INSERT INTO dbo.geca_audio_mentions
                    (video_id, brand_id, start_time, end_time, duration, start_fmt, end_fmt,
                     segment_text, matched_term, precision_type)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (video_id, brand_id, m["start"], m["end"], m.get("duration", 0),
                      m["start_fmt"], m["end_fmt"], m.get("text", ""),
                      m.get("matched_term", ""), m.get("precision", "word")))

        # 7. Insert brand summary
        for brand_name, info in mentions_data.get("brands", {}).items():
            brand_id = brand_id_map.get(brand_name)
            if not brand_id:
                continue
            m_list = info.get("mentions", [])
            if not m_list:
                continue
            total_dur = info.get("total_duration", 0)
            avg_dur = total_dur / len(m_list) if m_list else 0
            avg_interval = (m_list[-1]["start"] - m_list[0]["start"]) / max(len(m_list) - 1, 1) if len(m_list) > 1 else 0
            pct = (total_dur / duration * 100) if duration > 0 else 0

            cursor.execute("""
                INSERT INTO dbo.geca_video_brand_summary
                (video_id, brand_id, mention_count, total_duration, avg_duration,
                 first_mention_time, last_mention_time, first_mention_fmt, last_mention_fmt,
                 avg_interval, pct_of_video)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (video_id, brand_id, info["count"], total_dur, round(avg_dur, 2),
                  m_list[0]["start"], m_list[-1]["start"],
                  m_list[0]["start_fmt"], m_list[-1]["start_fmt"],
                  round(avg_interval, 2), round(pct, 2)))

        conn.commit()
        conn.close()
        return {"status": "ok", "video_id": video_id, "segments": len(trans_segments),
                "mentions": mentions_data.get("total_mentions", 0)}

    except Exception as e:
        conn.rollback()
        conn.close()
        return {"status": "error", "message": str(e)}


@app.post("/api/videos/{filename}/sync-sqlserver")
def sync_video_to_sqlserver(filename: str, user: User = Depends(get_current_user)):
    """Sync audio results to SQL Server"""
    return sync_to_sqlserver(filename)


@app.get("/api/sqlserver/status")
def sqlserver_status(user: User = Depends(get_current_user)):
    """Check SQL Server connection status"""
    conn = get_mssql_conn()
    if not conn:
        return {"connected": False, "message": "No SQL Server configured"}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DB_NAME() AS db, GETDATE() AS ts")
        row = cursor.fetchone()
        conn.close()
        return {"connected": True, "database": row[0], "server_time": str(row[1]),
                "host": SQLSERVER_HOST}
    except Exception as e:
        return {"connected": False, "message": str(e)}


# ==============================================
#  DATASETS MODULE
# ==============================================

DATASETS_DIR = os.getenv("DATASETS_DIR", "/mnt/shared/datasets")
MODELS_DIR = os.getenv("MODELS_DIR", "/mnt/shared/models")

# Ensure directories exist
for d in [os.path.join(DATASETS_DIR, "sources"), os.path.join(DATASETS_DIR, "ready"), MODELS_DIR]:
    os.makedirs(d, exist_ok=True)


class CreateDatasetRequest(BaseModel):
    name: str
    sources: list[str] = []
    tag: str = ""
    train_pct: float = 70.0
    val_pct: float = 20.0
    test_pct: float = 10.0


@app.post("/api/datasets/import-cvat/{task_id}")
async def import_cvat_dataset(task_id: int, user: User = Depends(get_current_user)):
    """Import dataset from CVAT task via API (server to server)"""
    db = SessionLocal()
    cfg = get_cvat_config(db)
    db.close()
    if not cfg["cvat_url"] or not cfg["cvat_username"]:
        return {"status": "error", "message": "CVAT no configurado"}

    try:
        headers = {"Host": cfg["cvat_host"]} if cfg["cvat_host"] else {}

        # 1. Login
        async with httpx.AsyncClient(base_url=cfg["cvat_url"], timeout=30, headers=headers) as client:
            resp = await client.post("/api/auth/login", json={
                "username": cfg["cvat_username"], "password": cfg["cvat_password"]
            })
            if resp.status_code != 200:
                return {"status": "error", "message": "No se pudo autenticar con CVAT"}
            token = resp.json().get("key")

        auth_headers = {**headers, "Authorization": f"Token {token}"}

        # 2. Get task info
        async with httpx.AsyncClient(base_url=cfg["cvat_url"], timeout=30, headers=auth_headers) as client:
            resp = await client.get(f"/api/tasks/{task_id}")
            if resp.status_code != 200:
                return {"status": "error", "message": f"Tarea {task_id} no encontrada"}
            task_info = resp.json()
            task_name = task_info["name"].replace(" ", "_")

        # 3. Request dataset export (new CVAT API)
        async with httpx.AsyncClient(base_url=cfg["cvat_url"], timeout=600, headers=auth_headers) as client:
            # Step 1: Start export
            resp = await client.post(f"/api/tasks/{task_id}/dataset/export", params={
                "format": "Ultralytics YOLO Detection 1.0", "save_images": "true"
            })
            if resp.status_code not in (200, 201, 202):
                return {"status": "error", "message": f"Error iniciando exportacion: {resp.status_code} {resp.text[:200]}"}

            rq_id = resp.json().get("rq_id", "")

            # Step 2: Poll until ready
            import asyncio
            for _ in range(60):
                await asyncio.sleep(3)
                resp = await client.get(f"/api/requests/{rq_id}")
                status = resp.json().get("status", "")
                if status == "finished":
                    break
                if status == "failed":
                    return {"status": "error", "message": "Exportacion fallida en CVAT"}

            if status != "finished":
                return {"status": "error", "message": "Timeout esperando exportacion"}

            # Step 3: Download - replace external host with internal
            result_url = resp.json().get("result_url", "")
            if cfg["cvat_host"] and cfg["cvat_host"] in result_url:
                result_url = result_url.replace(f"http://{cfg['cvat_host']}", "")
                result_url = result_url.replace(f"https://{cfg['cvat_host']}", "")

            resp = await client.get(result_url)
            if resp.status_code != 200:
                return {"status": "error", "message": f"Error descargando: {resp.status_code}"}

            zip_data = resp.content

        # 4. Save and extract
        import zipfile, io, shutil
        source_dir = os.path.join(DATASETS_DIR, "sources", task_name)
        if os.path.exists(source_dir):
            shutil.rmtree(source_dir)
        os.makedirs(source_dir, exist_ok=True)

        # Save ZIP
        zip_path = os.path.join(source_dir, "export.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_data)

        # Extract
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(source_dir)

        # 5. Reorganize: flatten train/val into single images/ and labels/
        img_dir = os.path.join(source_dir, "images")
        lbl_dir = os.path.join(source_dir, "labels")

        # Ultralytics format has images/train/, images/val/, labels/train/, labels/val/
        # Flatten into images/ and labels/ for combining later
        for subdir in ["train", "val", "test"]:
            for src_type, dst_dir in [("images", img_dir), ("labels", lbl_dir)]:
                sub_path = os.path.join(source_dir, src_type, subdir)
                if os.path.isdir(sub_path):
                    os.makedirs(dst_dir, exist_ok=True)
                    for f in os.listdir(sub_path):
                        src = os.path.join(sub_path, f)
                        dst = os.path.join(dst_dir, f)
                        if not os.path.exists(dst):
                            shutil.move(src, dst)
                    shutil.rmtree(sub_path, ignore_errors=True)
            # Clean empty parent dirs
            for src_type in ["images", "labels"]:
                sub_parent = os.path.join(source_dir, src_type)
                if os.path.isdir(sub_parent) and not os.listdir(sub_parent):
                    os.rmdir(sub_parent)

        # Read class names from data.yaml
        class_names = []
        yaml_path = os.path.join(source_dir, "data.yaml")
        if os.path.exists(yaml_path):
            import yaml
            with open(yaml_path) as f:
                yaml_data = yaml.safe_load(f)
                names = yaml_data.get("names", {})
                if isinstance(names, dict):
                    class_names = [names[k] for k in sorted(names.keys())]
                elif isinstance(names, list):
                    class_names = names

        # Fallback: read from obj.names
        if not class_names:
            names_file = os.path.join(source_dir, "obj.names")
            if os.path.exists(names_file):
                with open(names_file) as f:
                    class_names = [l.strip() for l in f if l.strip()]

        # Save metadata
        import json as _json
        meta = {
            "task_id": task_id,
            "task_name": task_info["name"],
            "class_names": class_names,
            "num_images": len([f for f in os.listdir(img_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]),
            "num_labels": len([f for f in os.listdir(lbl_dir) if f.endswith('.txt')]),
            "imported_at": datetime.utcnow().isoformat(),
        }
        with open(os.path.join(source_dir, "meta.json"), "w") as f:
            _json.dump(meta, f, indent=2)

        # Cleanup
        os.remove(zip_path)
        for d in ["obj_train_data", "train", "valid", "test"]:
            p = os.path.join(source_dir, d)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)

        return {"status": "ok", **meta}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/datasets")
def list_datasets(user: User = Depends(get_current_user)):
    """List all datasets (sources and ready)"""
    import json as _json

    sources = []
    sources_dir = os.path.join(DATASETS_DIR, "sources")
    if os.path.isdir(sources_dir):
        for name in sorted(os.listdir(sources_dir)):
            meta_path = os.path.join(sources_dir, name, "meta.json")
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    meta = _json.load(f)
                meta["folder"] = name
                meta["type"] = "source"
                sources.append(meta)
            else:
                img_dir = os.path.join(sources_dir, name, "images")
                n_imgs = len(os.listdir(img_dir)) if os.path.isdir(img_dir) else 0
                sources.append({"folder": name, "type": "source", "num_images": n_imgs})

    ready = []
    ready_dir = os.path.join(DATASETS_DIR, "ready")
    if os.path.isdir(ready_dir):
        for name in sorted(os.listdir(ready_dir)):
            meta_path = os.path.join(ready_dir, name, "meta.json")
            if os.path.exists(meta_path):
                with open(meta_path) as f:
                    meta = _json.load(f)
                meta["folder"] = name
                meta["type"] = "ready"
                ready.append(meta)

    return {"sources": sources, "ready": ready}


@app.get("/api/datasets/{dtype}/{name}/stats")
def get_dataset_stats(dtype: str, name: str, user: User = Depends(get_current_user)):
    """Get dataset statistics per split"""
    base = os.path.join(DATASETS_DIR, dtype, name)
    if not os.path.isdir(base):
        raise HTTPException(404, "Dataset no encontrado")

    import json as _json
    class_names = []
    meta_path = os.path.join(base, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            class_names = _json.load(f).get("class_names", [])

    yaml_path = os.path.join(base, "data.yaml")
    if os.path.exists(yaml_path):
        import yaml
        with open(yaml_path) as f:
            yaml_data = yaml.safe_load(f)
            names = yaml_data.get("names", {})
            if isinstance(names, dict):
                class_names = [names[k] for k in sorted(names.keys())]
            elif isinstance(names, list):
                class_names = names

    def count_labels(files):
        counts = {}
        total = 0
        imgs = 0
        for lf in files:
            has = False
            with open(lf) as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        cid = int(parts[0])
                        cn = class_names[cid] if cid < len(class_names) else f"class_{cid}"
                        counts[cn] = counts.get(cn, 0) + 1
                        total += 1
                        has = True
            if has:
                imgs += 1
        return counts, total, imgs

    lbl_dir = os.path.join(base, "labels")
    splits = {}
    all_files = []

    for split in ["train", "val", "test"]:
        sub = os.path.join(lbl_dir, split)
        if os.path.isdir(sub):
            files = [os.path.join(sub, f) for f in os.listdir(sub) if f.endswith('.txt')]
            all_files.extend(files)
            counts, total, imgs = count_labels(files)
            splits[split] = {
                "images": len(files), "annotations": total,
                "distribution": [{"class": c, "count": n} for c, n in sorted(counts.items(), key=lambda x: -x[1])],
            }

    if not splits:
        flat = [os.path.join(lbl_dir, f) for f in os.listdir(lbl_dir) if f.endswith('.txt')] if os.path.isdir(lbl_dir) else []
        all_files = flat

    total_counts, total_anns, total_imgs = count_labels(all_files)

    return {
        "total_images": len(all_files),
        "images_with_annotations": total_imgs,
        "total_annotations": total_anns,
        "class_names": class_names,
        "num_classes": len(class_names),
        "distribution": [{"class": c, "count": n} for c, n in sorted(total_counts.items(), key=lambda x: -x[1])],
        "splits": splits,
    }


@app.post("/api/datasets/create")
def create_final_dataset(data: CreateDatasetRequest, user: User = Depends(get_current_user)):
    """Create a final dataset from source datasets with train/val split"""
    import shutil, random, json as _json

    ready_dir = os.path.join(DATASETS_DIR, "ready", data.name)
    if os.path.exists(ready_dir):
        shutil.rmtree(ready_dir)

    # Create structure
    for split in ["train", "val", "test"]:
        os.makedirs(os.path.join(ready_dir, "images", split), exist_ok=True)
        os.makedirs(os.path.join(ready_dir, "labels", split), exist_ok=True)

    # Collect all image/label pairs from sources
    all_pairs = []
    all_class_names = []

    for src_name in data.sources:
        src_dir = os.path.join(DATASETS_DIR, "sources", src_name)
        img_dir = os.path.join(src_dir, "images")
        lbl_dir = os.path.join(src_dir, "labels")
        if not os.path.isdir(img_dir):
            continue

        # Read class names from this source
        meta_path = os.path.join(src_dir, "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                src_classes = _json.load(f).get("class_names", [])
                for c in src_classes:
                    if c not in all_class_names:
                        all_class_names.append(c)

        for img_f in sorted(os.listdir(img_dir)):
            if not img_f.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue
            lbl_f = img_f.rsplit('.', 1)[0] + '.txt'
            img_path = os.path.join(img_dir, img_f)
            lbl_path = os.path.join(lbl_dir, lbl_f)
            # Prefix with source name to avoid duplicates
            unique_name = f"{src_name}_{img_f}"
            all_pairs.append((img_path, lbl_path, unique_name))

    if not all_pairs:
        return {"status": "error", "message": "No hay imagenes en los sources seleccionados"}

    # Shuffle and split into train/val/test
    random.shuffle(all_pairs)
    train_count = int(len(all_pairs) * data.train_pct / 100)
    val_count = int(len(all_pairs) * data.val_pct / 100)
    train_pairs = all_pairs[:train_count]
    val_pairs = all_pairs[train_count:train_count + val_count]
    test_pairs = all_pairs[train_count + val_count:]

    # Copy files
    for pairs, split in [(train_pairs, "train"), (val_pairs, "val"), (test_pairs, "test")]:
        for img_path, lbl_path, unique_name in pairs:
            ext = img_path.rsplit('.', 1)[1]
            base_name = unique_name.rsplit('.', 1)[0]
            dst_img = os.path.join(ready_dir, "images", split, f"{base_name}.{ext}")
            dst_lbl = os.path.join(ready_dir, "labels", split, f"{base_name}.txt")
            shutil.copy2(img_path, dst_img)
            if os.path.exists(lbl_path):
                shutil.copy2(lbl_path, dst_lbl)

    # Create data.yaml (use "." as path so it works from any mount point)
    yaml_content = {
        "path": ".",
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {i: name for i, name in enumerate(all_class_names)},
        "nc": len(all_class_names),
    }

    import yaml
    with open(os.path.join(ready_dir, "data.yaml"), "w") as f:
        yaml.dump(yaml_content, f, default_flow_style=False, allow_unicode=True)

    # Save metadata with paths for both backend and jupyter
    meta = {
        "name": data.name,
        "tag": data.tag,
        "sources": data.sources,
        "train_pct": data.train_pct,
        "val_pct": data.val_pct,
        "test_pct": data.test_pct,
        "train_images": len(train_pairs),
        "val_images": len(val_pairs),
        "test_images": len(test_pairs),
        "total_images": len(all_pairs),
        "class_names": all_class_names,
        "num_classes": len(all_class_names),
        "created_at": datetime.utcnow().isoformat(),
        "data_yaml": os.path.join(ready_dir, "data.yaml"),
        "jupyter_yaml": ready_dir.replace("/mnt/shared", "/home/jovyan/shared") + "/data.yaml",
    }
    with open(os.path.join(ready_dir, "meta.json"), "w") as f:
        _json.dump(meta, f, indent=2)

    return {"status": "ok", **meta}


@app.delete("/api/datasets/{dtype}/{name}")
def delete_dataset(dtype: str, name: str, user: User = Depends(get_current_user)):
    """Delete a dataset"""
    import shutil
    path = os.path.join(DATASETS_DIR, dtype, name)
    if not os.path.isdir(path):
        raise HTTPException(404, "Dataset no encontrado")
    shutil.rmtree(path)
    return {"status": "deleted", "name": name}


@app.get("/api/models")
def list_models(user: User = Depends(get_current_user)):
    """List trained models"""
    models = []
    if os.path.isdir(MODELS_DIR):
        for f in sorted(os.listdir(MODELS_DIR)):
            if f.endswith('.pt'):
                fpath = os.path.join(MODELS_DIR, f)
                stat = os.stat(fpath)
                size_mb = stat.st_size / 1_000_000
                models.append({
                    "name": f,
                    "size_mb": round(size_mb, 1),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
    return {"models": models, "path": MODELS_DIR}
