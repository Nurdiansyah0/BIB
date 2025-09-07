# app/routers/terminals.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from .. import models
from ..database import SessionLocal

router = APIRouter()

# dependency DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# GET /api/terminals → daftar terminal
@router.get("/terminals")
def list_terminals(db: Session = Depends(get_db)):
    terminals = db.query(models.Terminal).all()
    return [{"id": t.id, "name": t.name} for t in terminals]

# GET /api/terminals/{id} → detail terminal + schema
@router.get("/terminals/{terminal_id}")
def get_terminal(terminal_id: int, db: Session = Depends(get_db)):
    term = db.query(models.Terminal).filter(models.Terminal.id == terminal_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Terminal tidak ditemukan")
    return {
        "id": term.id,
        "name": term.name,
        "form_schema": term.form_schema,
    }
