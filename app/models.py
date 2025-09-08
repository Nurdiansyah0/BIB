# app/models.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, CheckConstraint, Float
from datetime import datetime, timedelta
from .database import Base

class User(Base):
    __tablename__ = "users"
    id       = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)  # hash
    role     = Column(String(50), nullable=False, default="officer")
    require_password_change = Column(Integer, nullable=False, default=0)  # bool (0/1) for SQLite
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


class Lokasi(Base):
    __tablename__ = "lokasi"
    id_lokasi = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nama_lokasi = Column(String(255), nullable=False, unique=True, index=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    radius_m = Column(Integer, nullable=True, default=200)


class MasterUser(Base):
    __tablename__ = "master_users"
    id_user = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    nama_lengkap = Column(String(255), nullable=False)
    departemen = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="officer")
    __table_args__ = (
        CheckConstraint(
            "role IN ('officer','squad leader','team leader','manager','grup head','administrator')",
            name="ck_master_users_role",
        ),
    )


class Area(Base):
    __tablename__ = "area"
    id_area = Column(Integer, primary_key=True, index=True, autoincrement=True)
    id_lokasi = Column(Integer, ForeignKey("lokasi.id_lokasi"), nullable=False)
    nama_area = Column(String(255), nullable=False)


class Item(Base):
    __tablename__ = "item"
    id_item = Column(Integer, primary_key=True, index=True, autoincrement=True)
    id_area = Column(Integer, ForeignKey("area.id_area"), nullable=False)
    nama_item = Column(String(255), nullable=False)


class InspeksiTx(Base):
    __tablename__ = "inspeksi"
    id_inspeksi = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ts_utc = Column(String(32), nullable=False)  # ISO UTC string
    user_id = Column(Integer, ForeignKey("master_users.id_user"), nullable=False)
    item_id = Column(Integer, ForeignKey("item.id_item"), nullable=False)
    status = Column(String(50), nullable=False)
    catatan = Column(String(1024))
    latitude = Column(JSON)  # allow null or numeric; use JSON to keep simple
    longitude = Column(JSON)
    shift = Column(String(16))
