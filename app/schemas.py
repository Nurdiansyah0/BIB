# app/schemas.py
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict, Any, List

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: Optional[EmailStr] = None
    password: str = Field(min_length=6)
    # role is ignored on registration; server assigns default
    role: str | None = None

class ForgotRequest(BaseModel):
    username: str

class ResetRequest(BaseModel):
    token: str
    new_password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class InspectionCreate(BaseModel):
    terminal_id: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    data: Dict[str, Any]

class InspectionResponse(BaseModel):
    id: int
    message: str = "ok"


class UserUpdate(BaseModel):
    role: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=6)


class TerminalCreate(BaseModel):
    name: str
    form_schema: Optional[Dict[str, Any]] = None


class TerminalUpdate(BaseModel):
    name: Optional[str] = None
    form_schema: Optional[Dict[str, Any]] = None


class BulkItem(BaseModel):
    item_id: int
    status: str
    catatan: Optional[str] = None


class BulkInspectionCreate(BaseModel):
    lokasi_id: int
    area_id: int
    shift: Optional[str] = None
    lat: float
    lon: float
    items: List[BulkItem]


class MasterUserBase(BaseModel):
    email: str
    nama_lengkap: str
    departemen: str
    role: str = Field(default="officer")


class MasterUserCreate(MasterUserBase):
    pass


class MasterUserUpdate(BaseModel):
    email: Optional[str] = None
    nama_lengkap: Optional[str] = None
    departemen: Optional[str] = None
    role: Optional[str] = None
