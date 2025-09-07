# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
import secrets

from ..database import SessionLocal
from .. import models
from ..schemas import UserCreate, ForgotRequest, ResetRequest

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == user.username).first():
        raise HTTPException(status_code=409, detail="Username already registered")
    hashed = pwd_context.hash(user.password)
    new_user = models.User(username=user.username, password=hashed, role=user.role)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User created successfully", "id": new_user.id}

# (opsional) login minimal
@router.post("/login")
def login(payload: UserCreate, db: Session = Depends(get_db)):
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
