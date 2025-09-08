# app/deps.py
from typing import Optional
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, Request, status
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from .settings import SECRET_KEY, ALGORITHM
from .database import SessionLocal
from . import models

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token tidak valid") from e

def _wants_json(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    # Treat API paths or explicit JSON accept as JSON requests.
    # Do not treat "*/*" as JSON to allow HTML pages to redirect properly.
    return request.url.path.startswith("/api") or "application/json" in accept


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    token_cookie = request.cookies.get("access_token")
    if not token_cookie:
        # For API requests, return 401 JSON instead of redirect
        if _wants_json(request):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, detail="Silakan login terlebih dahulu")
    parts = token_cookie.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Format token tidak valid")

    payload = decode_token(parts[1])
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token tidak valid (tanpa sub)")

    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Pengguna tidak ditemukan")
    return user

def require_superadmin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "superadmin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden (superadmin only)")
    return user


def _normalize_role(name: str) -> str:
    if not name:
        return ""
    n = name.strip().lower().replace("_", " ")
    # Map synonyms to canonical
    if n in {"superadmin", "super admin", "administrator", "admin"}:
        return "administrator"
    if n in {"team leader", "teamleader"}:
        return "team leader"
    if n in {"group head", "grup head", "grouphead", "gruphead"}:
        return "group head"
    if n in {"squad leader", "squad_leader"}:
        return "squad leader"
    return n


def require_dashboard_access(user: models.User = Depends(get_current_user)) -> models.User:
    # Only allow team leader, manager, group head, administrator
    allowed = {"team leader", "manager", "group head", "administrator"}
    role = _normalize_role(user.role)
    if role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses dashboard dibatasi")
    return user
