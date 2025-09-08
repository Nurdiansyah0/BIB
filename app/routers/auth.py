# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
import secrets

from ..database import SessionLocal
from .. import models
from ..schemas import UserCreate, ForgotRequest, ResetRequest, LoginRequest
from ..deps import get_current_user

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _canonical_master_role(r: str | None) -> str:
    if not r:
        return "officer"
    n = r.strip().lower().replace("_", " ")
    if n in {"superadmin", "super admin", "administrator", "admin"}:
        return "administrator"
    if n in {"teamleader", "team leader"}: return "team leader"
    if n in {"group head", "grup head", "grouphead", "gruphead"}: return "grup head" if "grup" in n else "group head"
    if n in {"squad leader", "squad_leader"}: return "squad leader"
    return n


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == user.username).first():
        raise HTTPException(status_code=409, detail="Username already registered")
    # Force default role for auth users
    assigned_role = "officer"
    hashed = pwd_context.hash(user.password)
    new_user = models.User(username=user.username, password=hashed, role=assigned_role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    # Upsert into master_users using provided email (optional)
    email = (getattr(user, "email", None) or "").strip()
    if email:
        if not db.query(models.MasterUser).filter(models.MasterUser.email == email).first():
            db.add(models.MasterUser(
                email=email,
                nama_lengkap=user.username,
                departemen="Umum",
                role=_canonical_master_role(assigned_role),
            ))
            db.commit()
    return {"message": "User created successfully", "id": new_user.id}

# (opsional) login minimal
@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not pwd_context.verify(payload.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"message": "Login ok", "role": user.role}

@router.post("/password/forgot")
def forgot(req: ForgotRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == req.username).first()
    if not user:
        return {"message": "Jika akun terdaftar, token telah dikirim."}
    token = secrets.token_urlsafe(24)
    pr = models.PasswordReset(user_id=user.id, token=token, expires_at=datetime.utcnow() + timedelta(minutes=30))
    db.add(pr); db.commit()
    # DEV: tampilkan token untuk pengujian. PRODUKSI: kirim via email/SMS.
    return {"message": "Token reset dibuat.", "token": token}

@router.post("/password/reset")
def reset(req: ResetRequest, db: Session = Depends(get_db)):
    pr = db.query(models.PasswordReset).filter(models.PasswordReset.token == req.token).first()
    if not pr or pr.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Token tidak valid/kadaluarsa")
    user = db.query(models.User).filter(models.User.id == pr.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    user.password = pwd_context.hash(req.new_password)
    db.delete(pr); db.commit()
    return {"message": "Password berhasil direset"}


@router.get("/me")
def me(user: models.User = Depends(get_current_user)):
    return {"username": user.username, "role": user.role}
