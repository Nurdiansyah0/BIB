from fastapi import APIRouter, Request, Depends, HTTPException, status, Query, Path
from geopy.distance import distance
from sqlalchemy.orm import Session

from ..deps import get_db, get_current_user
from .. import models
from ..schemas import InspectionCreate, InspectionResponse, BulkInspectionCreate

router = APIRouter()

@router.post("/verify-location")
async def verify_location(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    user_lat = float(data.get('lat'))
    user_lon = float(data.get('lon'))
    lokasi_id = data.get('lokasi_id')
    lokasi_name = data.get('lokasi_name')

    lok = None
    if lokasi_id:
        lok = db.query(models.Lokasi).filter(models.Lokasi.id_lokasi == int(lokasi_id)).first()
    elif lokasi_name:
        lok = db.query(models.Lokasi).filter(models.Lokasi.nama_lokasi == str(lokasi_name)).first()

    if not lok:
        return {"valid": False, "detail": "Lokasi tidak ditemukan"}
    # Must check against None explicitly; 0.0 is a valid coordinate
    if not (lok.latitude is not None and lok.longitude is not None and (lok.radius_m or 0) > 0):
        # If no geofence configured, treat as invalid to enforce config
        return {"valid": False, "detail": "Geofence belum dikonfigurasi untuk lokasi ini"}

    dist_m = distance((user_lat, user_lon), (lok.latitude, lok.longitude)).meters
    valid = dist_m <= (lok.radius_m or 0)
    return {"valid": bool(valid), "distance_m": dist_m, "radius_m": lok.radius_m}


@router.post("/inspections", response_model=InspectionResponse, status_code=status.HTTP_201_CREATED)
def create_inspection(
    payload: InspectionCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    term = db.query(models.Terminal).filter(models.Terminal.id == payload.terminal_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Terminal tidak ditemukan")

    record = models.Inspection(
        terminal_id=payload.terminal_id,
        inspector_id=user.id,
        data={
            "lat": payload.lat,
            "lon": payload.lon,
            "fields": payload.data or {},
        },
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return InspectionResponse(id=record.id)


@router.post("/inspections/submit", response_model=InspectionResponse, status_code=status.HTTP_201_CREATED)
def create_inspection_alias(
    payload: InspectionCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return create_inspection(payload, db, user)


@router.post("/inspections/bulk-normalized")
def create_bulk_normalized(
    payload: BulkInspectionCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    # Verify lokasi exists and geofence
    lok = db.query(models.Lokasi).filter(models.Lokasi.id_lokasi == payload.lokasi_id).first()
    if not lok:
        raise HTTPException(status_code=404, detail="Lokasi tidak ditemukan")
    # Must check against None explicitly; 0.0 is a valid coordinate
    if not (lok.latitude is not None and lok.longitude is not None and (lok.radius_m or 0) > 0):
        raise HTTPException(status_code=400, detail="Geofence lokasi belum dikonfigurasi")
    try:
        d = distance((payload.lat, payload.lon), (lok.latitude, lok.longitude)).meters
    except Exception:
        raise HTTPException(status_code=400, detail="Koordinat tidak valid")
    if d > (lok.radius_m or 0):
        raise HTTPException(status_code=403, detail="Di luar jangkauan lokasi (geofence)")

    # Verify area under lokasi
    area = db.query(models.Area).filter(models.Area.id_area == payload.area_id).first()
    if not area or area.id_lokasi != lok.id_lokasi:
        raise HTTPException(status_code=400, detail="Area tidak valid untuk lokasi")

    # Resolve master user for current auth user
    master = db.query(models.MasterUser).filter(models.MasterUser.nama_lengkap == user.username).first()
    if not master:
        master = db.query(models.MasterUser).filter(models.MasterUser.email == 'admin@local').first()
        if not master:
            master = models.MasterUser(email='admin@local', nama_lengkap='Administrator', departemen='Umum', role='administrator')
            db.add(master); db.commit(); db.refresh(master)

    # Insert transactions
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    created = 0
    for it in payload.items:
        item = db.query(models.Item).filter(models.Item.id_item == it.item_id).first()
        if not item:
            continue
        if item.id_area != area.id_area:
            continue
        st = (it.status or '').strip() or 'Bagus'
        if st.lower() == 'rusak' and not (it.catatan and it.catatan.strip()):
            raise HTTPException(status_code=400, detail="Keterangan wajib untuk status Rusak")
        tx = models.InspeksiTx(
            ts_utc=ts,
            user_id=master.id_user,
            item_id=item.id_item,
            status=st,
            catatan=(it.catatan or '-') if st.lower() == 'rusak' else '-',
            latitude=payload.lat,
            longitude=payload.lon,
            shift=payload.shift,
        )
        db.add(tx); created += 1
    db.commit()
    return {"message": "ok", "created": created}


@router.get("/inspections")
def list_inspections(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    terminal_id: int | None = Query(None),
):
    q = db.query(models.Inspection)
    if terminal_id:
        q = q.filter(models.Inspection.terminal_id == terminal_id)
    items = q.offset(offset).limit(limit).all()

    # Enrich with related names
    def to_dict(x: models.Inspection):
        inspector = db.query(models.User).filter(models.User.id == x.inspector_id).first()
        term = db.query(models.Terminal).filter(models.Terminal.id == x.terminal_id).first()
        return {
            "id": x.id,
            "terminal_id": x.terminal_id,
            "terminal_name": getattr(term, "name", None),
            "inspector_id": x.inspector_id,
            "inspector_username": getattr(inspector, "username", None),
            "data": x.data,
        }

    return [to_dict(it) for it in items]


@router.get("/inspections/{inspection_id}")
def get_inspection(
    inspection_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    x = db.query(models.Inspection).filter(models.Inspection.id == inspection_id).first()
    if not x:
        raise HTTPException(status_code=404, detail="Inspection not found")
    inspector = db.query(models.User).filter(models.User.id == x.inspector_id).first()
    term = db.query(models.Terminal).filter(models.Terminal.id == x.terminal_id).first()
    return {
        "id": x.id,
        "terminal_id": x.terminal_id,
        "terminal_name": getattr(term, "name", None),
        "inspector_id": x.inspector_id,
        "inspector_username": getattr(inspector, "username", None),
        "data": x.data,
    }
