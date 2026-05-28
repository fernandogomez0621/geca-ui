"""
GECA Brands Manager - Backend API
Gestión de marcas, submarcas y contextos para detección en video deportivo.
Integración con CVAT para consulta de datasets.
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import hashlib
import secrets
import os
import httpx

# --- Config ---
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://geca:geca_secret@geca_db:5433/geca_brands")
CVAT_URL = os.getenv("CVAT_URL", "http://cvat_server:8080")
SECRET_KEY = os.getenv("SECRET_KEY", "geca-dev-secret-key-change-in-production")

# --- Database Setup ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ==============================================
#  MODELS (SQLAlchemy)
# ==============================================

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(20), default="annotator")  # admin, annotator, viewer
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Context(Base):
    """Tipos de superficie donde aparece una marca"""
    __tablename__ = "contexts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)  # camiseta, valla, anillo, grada
    description = Column(Text, nullable=True)
    icon = Column(String(10), nullable=True)  # emoji
    created_at = Column(DateTime, default=datetime.utcnow)

    subbrands = relationship("SubBrand", back_populates="context")


class Brand(Base):
    """Marca principal (Coca-Cola, Nike, etc.)"""
    __tablename__ = "brands"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    logo_url = Column(Text, nullable=True)
    color = Column(String(7), default="#6c5ce7")  # hex color for UI
    client = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    subbrands = relationship("SubBrand", back_populates="brand", cascade="all, delete-orphan")


class SubBrand(Base):
    """Variante visual de una marca en un contexto específico"""
    __tablename__ = "subbrands"
    id = Column(Integer, primary_key=True, index=True)
    brand_id = Column(Integer, ForeignKey("brands.id"), nullable=False)
    context_id = Column(Integer, ForeignKey("contexts.id"), nullable=False)
    cvat_label = Column(String(100), unique=True, nullable=False)  # cocacola_camiseta
    description = Column(Text, nullable=True)
    min_training_images = Column(Integer, default=200)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    brand = relationship("Brand", back_populates="subbrands")
    context = relationship("Context", back_populates="subbrands")


# ==============================================
#  PYDANTIC SCHEMAS
# ==============================================

# --- Auth ---
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

# --- Context ---
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

# --- Brand ---
class BrandCreate(BaseModel):
    name: str
    display_name: str
    logo_url: Optional[str] = None
    color: str = "#6c5ce7"
    client: Optional[str] = None

class BrandUpdate(BaseModel):
    display_name: Optional[str] = None
    logo_url: Optional[str] = None
    color: Optional[str] = None
    client: Optional[str] = None
    is_active: Optional[bool] = None

class BrandOut(BaseModel):
    id: int
    name: str
    display_name: str
    logo_url: Optional[str]
    color: str
    client: Optional[str]
    is_active: bool
    created_at: datetime
    subbrands: list = []
    class Config:
        from_attributes = True

# --- SubBrand ---
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

class SubBrandOut(BaseModel):
    id: int
    brand_id: int
    context_id: int
    cvat_label: str
    description: Optional[str]
    min_training_images: int
    is_active: bool
    created_at: datetime
    brand: Optional[BrandOut] = None
    context: Optional[ContextOut] = None
    class Config:
        from_attributes = True


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

# Simple token store (in production use JWT)
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


# ==============================================
#  STARTUP
# ==============================================

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    # Create default admin if not exists
    if not db.query(User).filter(User.username == "admin").first():
        admin = User(
            username="admin",
            email="admin@geca.com",
            password_hash=hash_password("admin123"),
            role="admin",
        )
        db.add(admin)

    # Create default contexts if empty
    if db.query(Context).count() == 0:
        defaults = [
            Context(name="camiseta", description="Logo en camiseta de jugador", icon="👕"),
            Context(name="valla", description="Valla publicitaria lateral", icon="🏗️"),
            Context(name="anillo", description="Anillo LED perimetral del estadio", icon="💡"),
            Context(name="grada", description="Publicidad en gradas/asientos", icon="🏟️"),
            Context(name="cesped", description="Logo pintado en el césped", icon="🌱"),
            Context(name="pantalla", description="Pantalla gigante del estadio", icon="📺"),
        ]
        db.add_all(defaults)

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

    return Token(
        access_token=token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


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

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
    )
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
        brand_data = BrandOut.model_validate(b)
        brand_data.subbrands = [
            {
                "id": sb.id,
                "cvat_label": sb.cvat_label,
                "context": sb.context.name if sb.context else None,
                "context_icon": sb.context.icon if sb.context else None,
                "is_active": sb.is_active,
            }
            for sb in b.subbrands
        ]
        result.append(brand_data)
    return result


@app.get("/api/brands/{brand_id}", response_model=BrandOut)
def get_brand(brand_id: int, db: Session = Depends(get_db)):
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(404, "Marca no encontrada")
    brand_data = BrandOut.model_validate(brand)
    brand_data.subbrands = [
        {
            "id": sb.id,
            "cvat_label": sb.cvat_label,
            "context": sb.context.name if sb.context else None,
            "context_icon": sb.context.icon if sb.context else None,
            "description": sb.description,
            "min_training_images": sb.min_training_images,
            "is_active": sb.is_active,
        }
        for sb in brand.subbrands
    ]
    return brand_data


@app.post("/api/brands", response_model=BrandOut)
def create_brand(data: BrandCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if db.query(Brand).filter(Brand.name == data.name).first():
        raise HTTPException(400, "Marca ya existe")
    brand = Brand(**data.model_dump())
    db.add(brand)
    db.commit()
    db.refresh(brand)
    brand_data = BrandOut.model_validate(brand)
    brand_data.subbrands = []
    return brand_data


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

@app.get("/api/subbrands", response_model=list[SubBrandOut])
def list_subbrands(brand_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(SubBrand)
    if brand_id:
        query = query.filter(SubBrand.brand_id == brand_id)
    return query.all()


@app.post("/api/subbrands", response_model=SubBrandOut)
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
    return sb


@app.put("/api/subbrands/{subbrand_id}", response_model=SubBrandOut)
def update_subbrand(subbrand_id: int, data: SubBrandUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sb = db.query(SubBrand).filter(SubBrand.id == subbrand_id).first()
    if not sb:
        raise HTTPException(404, "Submarca no encontrada")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(sb, key, value)
    db.commit()
    db.refresh(sb)
    return sb


@app.delete("/api/subbrands/{subbrand_id}")
def delete_subbrand(subbrand_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sb = db.query(SubBrand).filter(SubBrand.id == subbrand_id).first()
    if not sb:
        raise HTTPException(404, "Submarca no encontrada")
    db.delete(sb)
    db.commit()
    return {"status": "deleted"}


# ==============================================
#  CVAT INTEGRATION ENDPOINTS
# ==============================================

@app.get("/api/cvat/labels/{cvat_label}")
async def get_cvat_label_stats(cvat_label: str, user: User = Depends(get_current_user)):
    """
    Consulta CVAT para obtener estadísticas de un label:
    - Cuántas imágenes tienen ese label anotado
    - Muestra de frames
    """
    try:
        async with httpx.AsyncClient(base_url=CVAT_URL, timeout=30) as client:
            # Get all tasks
            resp = await client.get("/api/tasks", params={"page_size": 100})
            if resp.status_code != 200:
                return {"label": cvat_label, "total_images": 0, "status": "cvat_unreachable", "samples": []}

            tasks = resp.json().get("results", [])
            total_images = 0
            sample_frames = []

            for task in tasks:
                task_id = task["id"]
                # Check if task has this label
                task_labels = [l["name"] for l in task.get("labels", [])]
                if cvat_label not in task_labels:
                    continue

                # Get annotations for this task
                jobs_resp = await client.get(f"/api/tasks/{task_id}/jobs", params={"page_size": 100})
                if jobs_resp.status_code != 200:
                    continue

                jobs = jobs_resp.json().get("results", [])
                for job in jobs:
                    job_id = job["id"]
                    ann_resp = await client.get(f"/api/jobs/{job_id}/annotations")
                    if ann_resp.status_code != 200:
                        continue

                    annotations = ann_resp.json()
                    # Count frames with this label
                    frames_with_label = set()
                    for shape in annotations.get("shapes", []):
                        if shape.get("label_id"):
                            # Match by label name from task labels
                            frames_with_label.add(shape.get("frame", 0))

                    total_images += len(frames_with_label)

                    # Get sample frame URLs (first 4)
                    if len(sample_frames) < 4:
                        for frame_num in list(frames_with_label)[:4 - len(sample_frames)]:
                            sample_frames.append({
                                "task_id": task_id,
                                "frame": frame_num,
                                "url": f"{CVAT_URL}/api/tasks/{task_id}/data?type=frame&number={frame_num}&quality=compressed",
                            })

            # Determine training readiness
            sb = None
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
                "samples": sample_frames,
            }

    except Exception as e:
        return {
            "label": cvat_label,
            "total_images": 0,
            "status": f"error: {str(e)}",
            "samples": [],
        }


@app.get("/api/cvat/tasks")
async def list_cvat_tasks(user: User = Depends(get_current_user)):
    """Lista las tareas de CVAT"""
    try:
        async with httpx.AsyncClient(base_url=CVAT_URL, timeout=30) as client:
            resp = await client.get("/api/tasks", params={"page_size": 100})
            if resp.status_code != 200:
                return {"tasks": [], "status": "cvat_unreachable"}
            data = resp.json()
            tasks = []
            for t in data.get("results", []):
                tasks.append({
                    "id": t["id"],
                    "name": t["name"],
                    "status": t.get("status", "unknown"),
                    "size": t.get("size", 0),
                    "labels": [l["name"] for l in t.get("labels", [])],
                    "created_date": t.get("created_date"),
                })
            return {"tasks": tasks}
    except Exception as e:
        return {"tasks": [], "status": f"error: {str(e)}"}


# ==============================================
#  BRAND MAP ENDPOINT (for detection pipeline)
# ==============================================

@app.get("/api/brand-map")
def get_brand_map(db: Session = Depends(get_db)):
    """
    Retorna el diccionario de mapeo submarca -> marca
    Para usar en el pipeline de detección
    """
    subbrands = db.query(SubBrand).filter(SubBrand.is_active == True).all()
    brand_map = {}
    for sb in subbrands:
        brand_map[sb.cvat_label] = {
            "brand": sb.brand.display_name,
            "brand_id": sb.brand.id,
            "context": sb.context.name,
            "context_id": sb.context.id,
            "color": sb.brand.color,
        }
    return {"brand_map": brand_map}


# ==============================================
#  STATS ENDPOINT
# ==============================================

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {
        "total_brands": db.query(Brand).filter(Brand.is_active == True).count(),
        "total_subbrands": db.query(SubBrand).filter(SubBrand.is_active == True).count(),
        "total_contexts": db.query(Context).count(),
        "total_users": db.query(User).filter(User.is_active == True).count(),
    }
