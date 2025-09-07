# app/models.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from datetime import datetime, timedelta
from .database import Base

class User(Base):
    __tablename__ = "users"
    id       = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)  # hash
    role     = Column(String(50), nullable=False, default="officer")
    # contoh role: 'officer', 'manager', 'squad_leader', dst.

class Terminal(Base):
    __tablename__ = "terminals"
    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(100), nullable=False)
    # bisa tambahkan kolom latitude/longitude kalau perlu nanti
    form_schema = Column(JSON)  # simpan struktur form inspeksi per terminal

class Inspection(Base):
    __tablename__ = "inspections"
    id           = Column(Integer, primary_key=True, index=True)
    terminal_id  = Column(Integer, ForeignKey("terminals.id"), nullable=False)
    inspector_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    data         = Column(JSON)  # hasil inspeksi dalam bentuk JSON

class PasswordReset(Base):
    __tablename__ = "password_resets"
    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    token      = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.utcnow() + timedelta(minutes=30))
