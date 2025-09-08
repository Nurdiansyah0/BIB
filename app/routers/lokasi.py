from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from ..database import SessionLocal
from .. import models
from ..deps import get_db, get_current_user, require_superadmin

router = APIRouter()


@router.get("/lokasi")
def list_lokasi(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.query(models.Lokasi).order_by(models.Lokasi.nama_lokasi.asc()).all()
    return [
        {
            "id_lokasi": r.id_lokasi,
            "nama_lokasi": r.nama_lokasi,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "radius_m": r.radius_m,
        }
        for r in rows
    ]


@router.post("/lokasi", status_code=status.HTTP_201_CREATED)
def create_lokasi(nama_lokasi: str, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    nama = (nama_lokasi or "").strip()
    if not nama:
        raise HTTPException(status_code=400, detail="nama_lokasi wajib diisi")
    if db.query(models.Lokasi).filter(models.Lokasi.nama_lokasi == nama).first():
        raise HTTPException(status_code=409, detail="Lokasi sudah ada")
    row = models.Lokasi(nama_lokasi=nama)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id_lokasi": row.id_lokasi, "nama_lokasi": row.nama_lokasi}


@router.put("/lokasi/{id_lokasi}")
def update_lokasi(id_lokasi: int, nama_lokasi: str | None = None, latitude: float | None = None, longitude: float | None = None, radius_m: int | None = None, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    row = db.query(models.Lokasi).filter(models.Lokasi.id_lokasi == id_lokasi).first()
    if not row:
        raise HTTPException(status_code=404, detail="Lokasi tidak ditemukan")
    if nama_lokasi is not None:
        nama = (nama_lokasi or "").strip()
        if not nama:
            raise HTTPException(status_code=400, detail="nama_lokasi wajib diisi")
        if db.query(models.Lokasi).filter(models.Lokasi.nama_lokasi == nama, models.Lokasi.id_lokasi != id_lokasi).first():
            raise HTTPException(status_code=409, detail="Nama lokasi sudah digunakan")
        row.nama_lokasi = nama
    if latitude is not None:
        row.latitude = float(latitude)
    if longitude is not None:
        row.longitude = float(longitude)
    if radius_m is not None:
        row.radius_m = int(radius_m)
    db.commit()
    return {"id_lokasi": row.id_lokasi, "nama_lokasi": row.nama_lokasi, "latitude": row.latitude, "longitude": row.longitude, "radius_m": row.radius_m}


@router.delete("/lokasi/{id_lokasi}")
def delete_lokasi(id_lokasi: int, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    row = db.query(models.Lokasi).filter(models.Lokasi.id_lokasi == id_lokasi).first()
    if not row:
        raise HTTPException(status_code=404, detail="Lokasi tidak ditemukan")
    db.delete(row)
    db.commit()
    return {"message": "deleted"}


@router.get("/lokasi/{id_lokasi}/areas")
def list_areas(id_lokasi: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.query(models.Area).filter(models.Area.id_lokasi == id_lokasi).order_by(models.Area.nama_area.asc()).all()
    return [{"id_area": r.id_area, "nama_area": r.nama_area} for r in rows]


@router.get("/lokasi/{id_lokasi}/items")
def list_items_by_lokasi(id_lokasi: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    # Items under a lokasi via join
    rows = (
        db.query(models.Item)
        .join(models.Area, models.Item.id_area == models.Area.id_area)
        .filter(models.Area.id_lokasi == id_lokasi)
        .order_by(models.Item.nama_item.asc())
        .all()
    )
    return [{"id_item": r.id_item, "nama_item": r.nama_item} for r in rows]


@router.get("/area/{id_area}/items")
def list_items(id_area: int, db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    rows = db.query(models.Item).filter(models.Item.id_area == id_area).order_by(models.Item.nama_item.asc()).all()
    return [{"id_item": r.id_item, "nama_item": r.nama_item} for r in rows]
