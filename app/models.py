from app.database import Base
from sqlalchemy import Column, Integer, String, JSON

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password = Column(String)
    role = Column(String)  # 'inspector' atau 'manager'

class Terminal(Base):
    __tablename__ = "terminals"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    # Kolom geolokasi dihilangkan sementara
    form_schema = Column(JSON)  # Untuk menyimpan struktur form

class Inspection(Base):
    __tablename__ = "inspections"
    id = Column(Integer, primary_key=True)
    terminal_id = Column(Integer)
    inspector_id = Column(Integer)
    data = Column(JSON)  # Hasil inspeksi