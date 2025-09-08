# app/routers/terminals.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from .. import models
from ..database import SessionLocal
from ..deps import get_current_user

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


@router.get("/terminals/{terminal_id}/options")
def get_field_options(
    terminal_id: int,
    field: List[str] = Query(..., description="Nama field, ulangi parameter untuk beberapa field"),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    term = db.query(models.Terminal).filter(models.Terminal.id == terminal_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Terminal tidak ditemukan")

    wanted = [f for f in field if isinstance(f, str) and f.strip()]
    if not wanted:
        raise HTTPException(status_code=400, detail="Parameter field diperlukan")

    out = {f: [] for f in wanted}
    seen = {f: set() for f in wanted}

    # First, serve known master data if requested
    if "Lokasi" in wanted or "ID_Lokasi" in wanted:
        loks = (
            db.query(models.Lokasi)
            .order_by(models.Lokasi.nama_lokasi.asc())
            .limit(limit)
            .all()
        )
        if "Lokasi" in wanted:
            for row in loks:
                name = row.nama_lokasi
                if name not in seen["Lokasi"] and len(out["Lokasi"]) < limit:
                    seen["Lokasi"].add(name)
                    out["Lokasi"].append(name)
        if "ID_Lokasi" in wanted:
            for row in loks:
                sid = str(row.id_lokasi)
                if sid not in seen["ID_Lokasi"] and len(out["ID_Lokasi"]) < limit:
                    seen["ID_Lokasi"].add(sid)
                    out["ID_Lokasi"].append(sid)

    # Pull recent inspections and aggregate unique values from data.row and data.fields (fallback)
    if "Item_Cek_ID" in wanted:
        items = db.query(models.Item).order_by(models.Item.id_item.asc()).limit(limit).all()
        for it in items:
            sid = str(it.id_item)
            if sid not in seen["Item_Cek_ID"] and len(out["Item_Cek_ID"]) < limit:
                seen["Item_Cek_ID"].add(sid)
                out["Item_Cek_ID"].append(sid)
    q = db.query(models.Inspection).filter(models.Inspection.terminal_id == terminal_id)
    # Iterate a reasonable number to avoid heavy scans
    for ins in q.order_by(models.Inspection.id.desc()).limit(5000).all():
        data = ins.data or {}
        row = data.get("row") if isinstance(data, dict) else None
        fields_map = data.get("fields") if isinstance(data, dict) else None
        for fname in wanted:
            if len(out[fname]) >= limit:
                continue
            val = None
            if isinstance(row, dict) and fname in row:
                val = row.get(fname)
            elif isinstance(fields_map, dict) and fname in fields_map:
                val = fields_map.get(fname)
            if val is None:
                continue
            sval = str(val)
            if sval not in seen[fname]:
                seen[fname].add(sval)
                out[fname].append(sval)

    return out
