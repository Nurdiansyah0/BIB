from datetime import datetime, timedelta, timezone
import asyncio
from fastapi import APIRouter, WebSocket, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from ..deps import get_db, require_dashboard_access
from .. import models

router = APIRouter()


@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    await websocket.accept()
    while True:
        await websocket.send_json({"message": "Data updated"})
        # Prevent busy-looping the event loop
        await asyncio.sleep(2)


@router.get("/dashboard/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_dashboard_access),
):
    total = db.query(models.InspeksiTx).count()
    bagus = db.query(models.InspeksiTx).filter(models.InspeksiTx.status == 'Bagus').count()
    rusak = db.query(models.InspeksiTx).filter(models.InspeksiTx.status == 'Rusak').count()

    # Last 24h using lexicographic comparison on ISO string ts_utc
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
    last24 = db.query(models.InspeksiTx).filter(models.InspeksiTx.ts_utc >= cutoff).count()

    # Top lokasi by count
    q_loc = (
        db.query(models.Lokasi.nama_lokasi, func.count(models.InspeksiTx.id_inspeksi))
        .join(models.Area, models.Area.id_lokasi == models.Lokasi.id_lokasi)
        .join(models.Item, models.Item.id_area == models.Area.id_area)
        .join(models.InspeksiTx, models.InspeksiTx.item_id == models.Item.id_item)
        .group_by(models.Lokasi.id_lokasi)
        .order_by(func.count(models.InspeksiTx.id_inspeksi).desc())
        .limit(10)
        .all()
    )
    by_lokasi = [{"lokasi": n or "(tanpa nama)", "count": int(c)} for n, c in q_loc]

    # Worst items by Rusak
    q_worst = (
        db.query(models.Item.nama_item, func.count(models.InspeksiTx.id_inspeksi))
        .join(models.InspeksiTx, models.InspeksiTx.item_id == models.Item.id_item)
        .filter(models.InspeksiTx.status == 'Rusak')
        .group_by(models.Item.id_item)
        .order_by(func.count(models.InspeksiTx.id_inspeksi).desc())
        .limit(10)
        .all()
    )
    by_item_rusak = [{"item": n or "(tanpa nama)", "count": int(c)} for n, c in q_worst]

    return {
        "totals": {"total": total, "bagus": bagus, "rusak": rusak, "last24h": last24},
        "by_lokasi": by_lokasi,
        "by_item_rusak": by_item_rusak,
    }


@router.get("/dashboard/series")
def dashboard_series(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_dashboard_access),
):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    day_col = func.substr(models.InspeksiTx.ts_utc, 1, 10)

    day_labeled = day_col.label('day')
    rows = (
        db.query(day_labeled, models.InspeksiTx.status, func.count(models.InspeksiTx.id_inspeksi))
        .filter(models.InspeksiTx.ts_utc >= cutoff)
        .group_by(day_labeled, models.InspeksiTx.status)
        .order_by(day_labeled)
        .all()
    )
    # Aggregate per day
    data = {}
    for day, status, cnt in rows:
        d = data.setdefault(day, {"total": 0, "bagus": 0, "rusak": 0})
        d["total"] += int(cnt)
        if (status or '').lower() == 'bagus':
            d["bagus"] += int(cnt)
        elif (status or '').lower() == 'rusak':
            d["rusak"] += int(cnt)

    series = [
        {"day": k, "total": v["total"], "bagus": v["bagus"], "rusak": v["rusak"]}
        for k, v in sorted(data.items())
    ]
    return {"series": series}


@router.get("/dashboard/master-users")
def list_master_users_ro(
    q: str | None = Query(None, description="Cari email/nama/departemen"),
    role: str | None = Query(None, description="Filter per role"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: models.User = Depends(require_dashboard_access),
):
    qs = db.query(models.MasterUser)
    if role:
        qs = qs.filter(models.MasterUser.role == role)
    if q:
        qq = f"%{q.strip()}%"
        qs = qs.filter(
            or_(
                models.MasterUser.email.ilike(qq),
                models.MasterUser.nama_lengkap.ilike(qq),
                models.MasterUser.departemen.ilike(qq),
            )
        )
    rows = qs.order_by(models.MasterUser.id_user.asc()).offset(offset).limit(limit).all()
    return [
        {
            "id_user": r.id_user,
            "email": r.email,
            "nama_lengkap": r.nama_lengkap,
            "departemen": r.departemen,
            "role": r.role,
        }
        for r in rows
    ]
