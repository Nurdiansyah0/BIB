# app/routers/admin.py
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from passlib.context import CryptContext
import pandas as pd
import io, secrets, time, os

from .. import models
from ..deps import get_db, require_superadmin    # <- dari deps
from ..settings import templates                 # <- dari settings
from ..schemas import UserCreate, UserUpdate, TerminalCreate, TerminalUpdate, MasterUserCreate, MasterUserUpdate

# Split page routes from API routes to avoid exposing pages under /api
router = APIRouter()          # API endpoints (mounted under /api)
router_pages = APIRouter()    # Page endpoints (mounted without /api)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Pages (mounted without /api)
@router_pages.get("/admin/import", response_class=HTMLResponse)
def admin_import_page(request: Request, _: models.User = Depends(require_superadmin)):
    return templates.TemplateResponse("admin_import.html", {"request": request})

@router_pages.get("/admin/manage", response_class=HTMLResponse)
def admin_manage_page(request: Request, _: models.User = Depends(require_superadmin)):
    return templates.TemplateResponse("admin_manage.html", {"request": request})


# ===== Import XLSX/CSV preview & commit =====
IMPORT_CACHE: dict[str, dict] = {}
IMPORT_TTL_SEC = 30 * 60  # 30 minutes


def cleanup_cache():
    now = int(time.time())
    to_del = [k for k, v in IMPORT_CACHE.items() if now - v.get("ts", now) > IMPORT_TTL_SEC]
    for k in to_del:
        IMPORT_CACHE.pop(k, None)


def infer_schema_from_df(df: pd.DataFrame) -> dict:
    fields = []
    for col in df.columns.tolist():
        series = df[col].dropna()
        ftype = "text"
        if not series.empty:
            if pd.api.types.is_numeric_dtype(series):
                ftype = "number"
            else:
                # If low cardinality, treat as select
                unique_vals = series.astype(str).unique()
                if len(unique_vals) > 0 and len(unique_vals) <= 10:
                    fields.append({"name": col, "label": col, "type": "select", "options": unique_vals[:10].tolist()})
                    continue
        fields.append({"name": col, "label": col, "type": ftype})
    return {"fields": fields}


@router.post("/admin/import-xlsx")
def import_xlsx_preview(
    file: UploadFile = File(...),
    _: models.User = Depends(require_superadmin),
):
    cleanup_cache()
    filename = file.filename or "upload"
    ext = os.path.splitext(filename)[1].lower()
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File kosong")

    try:
        buf = io.BytesIO(content)
        if ext in (".csv", ".txt"):
            df = pd.read_csv(buf)
        elif ext in (".xlsx", ".xls"):
            try:
                df = pd.read_excel(buf)
            except Exception as e:
                raise HTTPException(status_code=400, detail="Gagal membaca Excel (butuh openpyxl untuk .xlsx)") from e
        else:
            raise HTTPException(status_code=400, detail="Format file tidak didukung. Unggah .csv atau .xlsx")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal memproses file: {e}")

    # Basic normalize: cast columns to string names
    df.columns = [str(c).strip() for c in df.columns]
    row_count = int(df.shape[0])
    columns = df.columns.tolist()
    preview_rows = df.head(20).fillna("").astype(object).astype(str).to_dict(orient="records")
    schema = infer_schema_from_df(df)

    token = secrets.token_urlsafe(24)
    IMPORT_CACHE[token] = {
        "ts": int(time.time()),
        "filename": filename,
        "row_count": row_count,
        "columns": columns,
        "preview": preview_rows,
        "schema": schema,
        # keep raw records (limit to reasonable number to avoid memory blowup)
        "rows": df.fillna("").astype(object).astype(str).to_dict(orient="records"),
    }

    return {
        "token": token,
        "filename": filename,
        "row_count": row_count,
        "columns": columns,
        "preview": preview_rows,
        "schema": schema,
    }


@router.post("/admin/commit-import")
def commit_import(
    token: str = Form(...),
    terminal_name: str = Form(...),
    mode: str = Form("create_or_update"),
    insert_rows: str = Form("false"),
    default_inspector_id: str | None = Form(None),
    inspector_username_col: str | None = Form(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_superadmin),
):
    cleanup_cache()
    payload = IMPORT_CACHE.get(token)
    if not payload:
        raise HTTPException(status_code=404, detail="Preview tidak ditemukan atau kadaluarsa")
    rows = payload.get("rows") or []
    schema = payload.get("schema")

    # Upsert terminal
    term = db.query(models.Terminal).filter(models.Terminal.name == terminal_name).first()
    if not term:
        if mode != "create_or_update":
            raise HTTPException(status_code=400, detail="Terminal tidak ada dan mode bukan create_or_update")
        term = models.Terminal(name=terminal_name, form_schema=schema)
        db.add(term)
        db.commit()
        db.refresh(term)
    else:
        # Update schema if provided
        term.form_schema = schema
        db.commit()

    # determine default inspector
    default_inspector = user
    if default_inspector_id:
        try:
            did = int(str(default_inspector_id).strip())
            cand = db.query(models.User).filter(models.User.id == did).first()
            if cand:
                default_inspector = cand
        except Exception:
            pass

    inserted = 0
    if (insert_rows or "").lower() in ("1", "true", "yes", "on"):
        limit = min(len(rows), 1000)
        for r in rows[:limit]:
            inspector_id = default_inspector.id
            if inspector_username_col:
                key = inspector_username_col.strip()
                if key and isinstance(r, dict) and key in r:
                    uname = str(r.get(key) or '').strip()
                    if uname:
                        found = db.query(models.User).filter(models.User.username == uname).first()
                        if found:
                            inspector_id = found.id
            rec = models.Inspection(terminal_id=term.id, inspector_id=inspector_id, data={"row": r})
            db.add(rec)
            inserted += 1
        db.commit()

    # one-time use token
    IMPORT_CACHE.pop(token, None)

    return {"message": "ok", "terminal_id": term.id, "inserted_rows": inserted}

# Users CRUD (prefix becomes /api/admin/...)
@router.get("/admin/users")
def list_users(db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    users = db.query(models.User).all()
    return [{"id": u.id, "username": u.username, "role": u.role} for u in users]


@router.post("/admin/users")
def create_user(payload: UserCreate, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    hashed = pwd_context.hash(payload.password)
    u = models.User(username=payload.username, password=hashed, role=payload.role)
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"id": u.id, "username": u.username, "role": u.role}


@router.put("/admin/users/{user_id}")
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    u = db.query(models.User).filter(models.User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.role is not None:
        u.role = payload.role
    if payload.password:
        u.password = pwd_context.hash(payload.password)
        # Enforce password change on next login
        try:
            u.require_password_change = 1
        except Exception:
            pass
    db.commit()
    return {"id": u.id, "username": u.username, "role": u.role}


@router.delete("/admin/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    u = db.query(models.User).filter(models.User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(u)
    db.commit()
    return {"message": "deleted"}


@router.post("/admin/users/{user_id}/reset-password-temp")
def reset_password_temp(user_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    u = db.query(models.User).filter(models.User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    import secrets, string
    alphabet = string.ascii_letters + string.digits
    temp = ''.join(secrets.choice(alphabet) for _ in range(12))
    u.password = pwd_context.hash(temp)
    try:
        u.require_password_change = 1
    except Exception:
        pass
    db.commit()
    return {"temporary_password": temp}


# Terminals CRUD
@router.get("/admin/terminals")
def list_terminals_admin(db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    terms = db.query(models.Terminal).all()
    return [{"id": t.id, "name": t.name, "form_schema": t.form_schema} for t in terms]


@router.post("/admin/terminals")
def create_terminal(payload: TerminalCreate, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    t = models.Terminal(name=payload.name, form_schema=payload.form_schema)
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "name": t.name, "form_schema": t.form_schema}


@router.put("/admin/terminals/{terminal_id}")
def update_terminal(terminal_id: int, payload: TerminalUpdate, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    t = db.query(models.Terminal).filter(models.Terminal.id == terminal_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Terminal not found")
    if payload.name is not None:
        t.name = payload.name
    if payload.form_schema is not None:
        t.form_schema = payload.form_schema
    db.commit()
    return {"id": t.id, "name": t.name, "form_schema": t.form_schema}


@router.delete("/admin/terminals/{terminal_id}")
def delete_terminal(terminal_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    t = db.query(models.Terminal).filter(models.Terminal.id == terminal_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Terminal not found")
    db.delete(t)
    db.commit()
    return {"message": "deleted"}


# DB maintenance
@router.post("/admin/db/vacuum")
def vacuum_db(db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    # Execute VACUUM for SQLite; harmless for others if not supported
    try:
        db.execute(text("VACUUM"))
        db.commit()
    except Exception:
        # Ignore if not supported in current backend
        pass
    return {"message": "ok"}


# ===== Master Users CRUD =====
@router.get("/admin/master-users")
def list_master_users(db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    rows = db.query(models.MasterUser).order_by(models.MasterUser.id_user.asc()).all()
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


@router.post("/admin/master-users", status_code=201)
def create_master_user(payload: MasterUserCreate, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    allowed_roles = {"officer","squad leader","team leader","manager","grup head","administrator"}
    if payload.role and payload.role not in allowed_roles:
        raise HTTPException(status_code=400, detail="Role tidak valid")
    if db.query(models.MasterUser).filter(models.MasterUser.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email sudah terdaftar")
    row = models.MasterUser(
        email=payload.email,
        nama_lengkap=payload.nama_lengkap,
        departemen=payload.departemen,
        role=payload.role,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id_user": row.id_user}


@router.put("/admin/master-users/{id_user}")
def update_master_user(id_user: int, payload: MasterUserUpdate, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    row = db.query(models.MasterUser).filter(models.MasterUser.id_user == id_user).first()
    if not row:
        raise HTTPException(status_code=404, detail="Master user tidak ditemukan")
    allowed_roles = {"officer","squad leader","team leader","manager","grup head","administrator"}
    if payload.email:
        # ensure uniqueness
        if db.query(models.MasterUser).filter(models.MasterUser.email == payload.email, models.MasterUser.id_user != id_user).first():
            raise HTTPException(status_code=409, detail="Email sudah digunakan")
        row.email = payload.email
    if payload.nama_lengkap is not None:
        row.nama_lengkap = payload.nama_lengkap
    if payload.departemen is not None:
        row.departemen = payload.departemen
    if payload.role is not None:
        if payload.role not in allowed_roles:
            raise HTTPException(status_code=400, detail="Role tidak valid")
        row.role = payload.role
    db.commit()
    return {"message": "ok"}


@router.delete("/admin/master-users/{id_user}")
def delete_master_user(id_user: int, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    row = db.query(models.MasterUser).filter(models.MasterUser.id_user == id_user).first()
    if not row:
        raise HTTPException(status_code=404, detail="Master user tidak ditemukan")
    db.delete(row)
    db.commit()
    return {"message": "deleted"}


# ===== Area CRUD =====
@router.get("/admin/areas")
def list_areas_admin(lokasi_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    rows = db.query(models.Area).filter(models.Area.id_lokasi == lokasi_id).order_by(models.Area.nama_area.asc()).all()
    return [{"id_area": r.id_area, "nama_area": r.nama_area} for r in rows]


@router.post("/admin/areas", status_code=201)
def create_area(lokasi_id: int, nama_area: str, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    nama = (nama_area or "").strip()
    if not nama:
        raise HTTPException(status_code=400, detail="nama_area wajib diisi")
    exists = db.query(models.Area).filter(models.Area.id_lokasi == lokasi_id, models.Area.nama_area == nama).first()
    if exists:
        raise HTTPException(status_code=409, detail="Area sudah ada")
    row = models.Area(id_lokasi=lokasi_id, nama_area=nama)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id_area": row.id_area}


@router.put("/admin/areas/{id_area}")
def update_area(id_area: int, nama_area: str, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    row = db.query(models.Area).filter(models.Area.id_area == id_area).first()
    if not row:
        raise HTTPException(status_code=404, detail="Area tidak ditemukan")
    nama = (nama_area or "").strip()
    if not nama:
        raise HTTPException(status_code=400, detail="nama_area wajib diisi")
    exists = db.query(models.Area).filter(models.Area.id_lokasi == row.id_lokasi, models.Area.nama_area == nama, models.Area.id_area != id_area).first()
    if exists:
        raise HTTPException(status_code=409, detail="Nama area sudah digunakan")
    row.nama_area = nama
    db.commit()
    return {"message": "ok"}


@router.delete("/admin/areas/{id_area}")
def delete_area(id_area: int, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    row = db.query(models.Area).filter(models.Area.id_area == id_area).first()
    if not row:
        raise HTTPException(status_code=404, detail="Area tidak ditemukan")
    db.delete(row)
    db.commit()
    return {"message": "deleted"}


# ===== Item CRUD =====
@router.get("/admin/items")
def list_items_admin(area_id: int, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    rows = db.query(models.Item).filter(models.Item.id_area == area_id).order_by(models.Item.nama_item.asc()).all()
    return [{"id_item": r.id_item, "nama_item": r.nama_item} for r in rows]


@router.post("/admin/items", status_code=201)
def create_item(area_id: int, nama_item: str, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    nama = (nama_item or "").strip()
    if not nama:
        raise HTTPException(status_code=400, detail="nama_item wajib diisi")
    exists = db.query(models.Item).filter(models.Item.id_area == area_id, models.Item.nama_item == nama).first()
    if exists:
        raise HTTPException(status_code=409, detail="Item sudah ada")
    row = models.Item(id_area=area_id, nama_item=nama)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id_item": row.id_item}


@router.put("/admin/items/{id_item}")
def update_item(id_item: int, nama_item: str, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    row = db.query(models.Item).filter(models.Item.id_item == id_item).first()
    if not row:
        raise HTTPException(status_code=404, detail="Item tidak ditemukan")
    nama = (nama_item or "").strip()
    if not nama:
        raise HTTPException(status_code=400, detail="nama_item wajib diisi")
    exists = db.query(models.Item).filter(models.Item.id_area == row.id_area, models.Item.nama_item == nama, models.Item.id_item != id_item).first()
    if exists:
        raise HTTPException(status_code=409, detail="Nama item sudah digunakan")
    row.nama_item = nama
    db.commit()
    return {"message": "ok"}


@router.delete("/admin/items/{id_item}")
def delete_item(id_item: int, db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    row = db.query(models.Item).filter(models.Item.id_item == id_item).first()
    if not row:
        raise HTTPException(status_code=404, detail="Item tidak ditemukan")
    db.delete(row)
    db.commit()
    return {"message": "deleted"}


@router.get("/admin/db-summary")
def db_summary(db: Session = Depends(get_db), _: models.User = Depends(require_superadmin)):
    return {
        "counts": {
            "users_auth": db.query(models.User).count(),
            "terminals": db.query(models.Terminal).count(),
            "inspections_legacy": db.query(models.Inspection).count(),
            "master_users": db.query(models.MasterUser).count(),
            "lokasi": db.query(models.Lokasi).count(),
            "area": db.query(models.Area).count(),
            "item": db.query(models.Item).count(),
            "inspeksi": db.query(models.InspeksiTx).count(),
        }
    }


# ===== Normalize legacy inspections into master tables =====
@router.post("/admin/normalize-inspections")
def normalize_inspections(
    terminal_id: int,
    create_transactions: bool = False,
    inspector_email: str | None = None,
    default_status: str = "Bagus",
    default_shift: str | None = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_superadmin),
):
    """Merge legacy inspections (JSON rows) into master Lokasi/Area/Item and optional transactions."""
    inspections = (
        db.query(models.Inspection)
        .filter(models.Inspection.terminal_id == terminal_id)
        .order_by(models.Inspection.id.asc())
        .all()
    )
    created_lokasi = created_area = created_item = created_tx = 0

    # Resolve master inspector if needed
    master_user = None
    if create_transactions:
        email = (inspector_email or "admin@local").strip().lower()
        master_user = db.query(models.MasterUser).filter(models.MasterUser.email == email).first()
        if not master_user:
            master_user = models.MasterUser(email=email, nama_lengkap="Administrator", departemen="Umum", role="administrator")
            db.add(master_user)
            db.commit(); db.refresh(master_user)

    from datetime import datetime, timezone

    for ins in inspections:
        payload = ins.data or {}
        row = {}
        if isinstance(payload, dict):
            if isinstance(payload.get("row"), dict):
                row = payload.get("row")
            elif isinstance(payload.get("fields"), dict):
                row = payload.get("fields")
        if not isinstance(row, dict):
            continue

        lokasi_name = str(row.get("Lokasi") or "").strip()
        # Expect human-readable area name from 'Area' and item id from 'Item_Cek_ID'
        area_name = str(row.get("Area") or "").strip()
        item_raw = row.get("Item_Cek_ID")
        item_str = str(item_raw or "").strip()
        if not lokasi_name or not area_name or not item_str:
            continue

        # Lokasi
        lokasi = db.query(models.Lokasi).filter(models.Lokasi.nama_lokasi == lokasi_name).first()
        if not lokasi:
            lokasi = models.Lokasi(nama_lokasi=lokasi_name)
            db.add(lokasi); db.commit(); db.refresh(lokasi); created_lokasi += 1
        # Area
        area = db.query(models.Area).filter(models.Area.id_lokasi == lokasi.id_lokasi, models.Area.nama_area == area_name).first()
        if not area:
            area = models.Area(id_lokasi=lokasi.id_lokasi, nama_area=area_name)
            db.add(area); db.commit(); db.refresh(area); created_area += 1
        # Item: prefer resolving by numeric id when provided; fallback to name
        item = None
        item_id_val = None
        try:
            item_id_val = int(item_str)
        except Exception:
            item_id_val = None
        if item_id_val is not None:
            item = db.query(models.Item).filter(models.Item.id_item == item_id_val).first()
        if item is None:
            # Fallback to name-based lookup/creation
            item_name = item_str
            item = (
                db.query(models.Item)
                .filter(models.Item.id_area == area.id_area, models.Item.nama_item == item_name)
                .first()
            )
            if item is None and item_name:
                item = models.Item(id_area=area.id_area, nama_item=item_name)
                db.add(item); db.commit(); db.refresh(item); created_item += 1

        if create_transactions and master_user:
            ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            tx = models.InspeksiTx(
                ts_utc=ts,
                user_id=master_user.id_user,
                item_id=item.id_item,
                status=default_status,
                catatan='-',
                latitude=None,
                longitude=None,
                shift=default_shift,
            )
            db.add(tx); created_tx += 1
    db.commit()

    return {
        "terminal_id": terminal_id,
        "created": {
            "lokasi": created_lokasi,
            "area": created_area,
            "item": created_item,
            "transactions": created_tx,
        },
        "total_inspections_processed": len(inspections),
    }
