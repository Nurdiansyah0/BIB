# app/main.py
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import time
from sqlalchemy import text

from .database import Base, engine, SessionLocal
from . import models
from .routers import auth, dashboard, inspections, terminals, admin, lokasi
from .settings import (
    BASE_DIR,
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    templates,
    CORS_ORIGINS,
    ALLOWED_HOSTS,
    COOKIE_SECURE,
    ENABLE_HTTPS_REDIRECT,
)
from .deps import get_db, get_current_user, require_dashboard_access, decode_token, _normalize_role  # <- pakai dari deps
from starlette.requests import Request as StarletteRequest

app = FastAPI(title="BIB")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # Set common security headers
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(self)")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
if ENABLE_HTTPS_REDIRECT:
    app.add_middleware(HTTPSRedirectMiddleware)
if ALLOWED_HOSTS and ALLOWED_HOSTS != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)


class RateLimitMiddleware(BaseHTTPMiddleware):
    _store: dict = {}

    def __init__(self, app, limit: int = 60, window_seconds: int = 60, paths: list[str] | None = None):
        super().__init__(app)
        self.limit = limit
        self.window = window_seconds
        self.paths = set(paths or [])

    async def dispatch(self, request, call_next):
        path = request.url.path
        method = request.method.upper()
        # Target only sensitive POST endpoints by default
        if self.paths and method == "POST" and any(path.startswith(p) for p in self.paths):
            ip = (request.client.host if request.client else "-")
            now = int(time.time())
            key = (ip, path)
            count, start = self._store.get(key, (0, now))
            if now - start >= self.window:
                count, start = 0, now
            count += 1
            self._store[key] = (count, start)
            if count > self.limit:
                return JSONResponse({"detail": "Too Many Requests"}, status_code=429)
        return await call_next(request)


# Apply a conservative rate-limit for auth operations (per IP)
app.add_middleware(
    RateLimitMiddleware,
    limit=100,  # 100 req/min per IP per path
    window_seconds=60,
    paths=[
        "/login",
        "/api/login",
        "/api/register",
        "/api/password/forgot",
        "/api/password/reset",
    ],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    # Create export view (SQLite); ignore errors if already exists
    with engine.begin() as conn:
        # Try to add require_password_change column if missing
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN require_password_change INTEGER DEFAULT 0"))
        except Exception:
            pass
        # Add lokasi geofence columns if missing
        try:
            conn.execute(text("ALTER TABLE lokasi ADD COLUMN latitude REAL"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE lokasi ADD COLUMN longitude REAL"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE lokasi ADD COLUMN radius_m INTEGER DEFAULT 200"))
        except Exception:
            pass
        try:
            conn.execute(text("DROP VIEW IF EXISTS v_inspeksi_export"))
            conn.execute(text(
                """
                CREATE VIEW v_inspeksi_export AS
                SELECT
                  (CASE strftime('%w', ts_utc)
                     WHEN '0' THEN 'Minggu'
                     WHEN '1' THEN 'Senin'
                     WHEN '2' THEN 'Selasa'
                     WHEN '3' THEN 'Rabu'
                     WHEN '4' THEN 'Kamis'
                     WHEN '5' THEN 'Jumat'
                     WHEN '6' THEN 'Sabtu'
                   END)
                   || ', ' || CAST(strftime('%d', ts_utc) AS INTEGER)
                   || ' ' || CAST(strftime('%m', ts_utc) AS INTEGER)
                   || ' ' || strftime('%Y', ts_utc)
                   || ', ' || strftime('%H', ts_utc) || '.' || strftime('%M', ts_utc) || '.' AS "TIMESTAMP",
                  MU.nama_lengkap AS "NAMA_PETUGAS",
                  A.nama_area     AS "LOKASI",
                  I.nama_item     AS "ITEM_INSPEKSI",
                  X.status        AS "STATUS",
                  COALESCE(X.catatan, '-') AS "CATATAN",
                  REPLACE(CAST(X.latitude  AS TEXT), '.', ',')  AS "LATITUDE",
                  REPLACE(CAST(X.longitude AS TEXT), '.', ',')  AS "LONGITUDE",
                  X.shift AS "SHIFT"
                FROM inspeksi X
                JOIN master_users MU ON MU.id_user = X.user_id
                JOIN item I ON I.id_item = X.item_id
                JOIN area A ON A.id_area = I.id_area
                JOIN lokasi L ON L.id_lokasi = A.id_lokasi
                """
            ))
        except Exception:
            pass
    # superuser default
    db = SessionLocal()
    try:
        default_username = "admin"
        default_password = "Admin123!"
        default_role = "superadmin"
        user = db.query(models.User).filter(models.User.username == default_username).first()
        if not user:
            hashed = pwd_context.hash(default_password)
            db.add(models.User(username=default_username, password=hashed, role=default_role))
            db.commit()
            print(f"[INFO] Default superuser '{default_username}' dibuat.")
        else:
            print(f"[INFO] Default superuser '{default_username}' sudah ada.")
        # Seed master users (idempotent)
        seed_master = [
            ("terminal.landside313@gmail.com","Administrator","administrator"),
            ("resa.thians@gmail.com","Administrator","administrator"),
            ("nudiansyahdian28.adv@gmail.com","Administrator","administrator"),
            ("rdef707@gmail.com","Defrianto","officer"),
            ("sutrisnobatam78@gmail.com","Sutrisno","officer"),
            ("eeddygunawan@gmail.com","Eddy Gunawan","officer"),
            ("dwichahyandha@gmail.com","Dwi Chahyanda","officer"),
            ("sakiramaulida321@gmail.com","Saparudin","officer"),
            ("albertmaruli329@gmail.com","Albert Maruli","officer"),
            ("samsuri051971@gmail.com","Samsuri","officer"),
            ("syahrudinn007@gmail.com","Syahruddin Harahap","officer"),
            ("ikrambandara@gmail.com","Ikram","officer"),
            ("setiapermana998@gmail.com","Agus Setia P","officer"),
            ("jhonniindrabutas@gmail.com","Jhoni Indra Butas","officer"),
            ("mustofaairport@gmail.com","Mustofa","officer"),
            ("sutarnombah@gmail.com","Sutarno","officer"),
            ("cckhd71@gmail.com","Syamsul Hadi","officer"),
            ("cservicebib@gmail.com","percobaan","officer"),
            ("operationbatam.tlom@gmail.com","Novita Milana","officer"),
            ("novita.milana@gmail.com","Administrator","administrator"),
            ("hartowibowo1978@gmail.com","Harto Wibowo","officer"),
        ]
        allowed_roles = {"officer","squad leader","team leader","manager","grup head","administrator"}
        for email, nama, role in seed_master:
            role = role if role in allowed_roles else "officer"
            if not db.query(models.MasterUser).filter(models.MasterUser.email == email).first():
                db.add(models.MasterUser(email=email, nama_lengkap=nama, departemen="Umum", role=role))
        db.commit()

        # Ensure at least one Terminal exists so the inspection form can load
        if db.query(models.Terminal).count() == 0:
            default_schema = {
                "fields": [
                    {"name": "Lokasi", "type": "select", "label": "Lokasi"},
                    {"name": "ID_Lokasi", "type": "select", "label": "ID Lokasi"},
                    {"name": "Area", "type": "select", "label": "Area"},
                    {"name": "Item_Cek_ID", "type": "select", "label": "Item"},
                ]
            }
            db.add(models.Terminal(name="Terminal 1", form_schema=default_schema))
            db.commit()
    finally:
        db.close()

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=HTMLResponse, include_in_schema=False)
def handle_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(password, user.password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Username atau password salah"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    token = create_access_token(data={"sub": user.username, "role": user.role}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    # If the account requires password change, force redirect
    next_url = "/password/change" if getattr(user, "require_password_change", 0) else "/dashboard"
    resp = RedirectResponse(url=next_url, status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        "access_token",
        f"Bearer {token}",
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return resp

@app.get("/logout", include_in_schema=False)
def logout():
    resp = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("access_token")
    return resp

# NOTE: Dashboard now served by Dash app mounted at /dashboard
@app.get("/inspection-form", response_class=HTMLResponse, include_in_schema=False)
def inspection_form_page(request: Request, current_user: models.User = Depends(get_current_user)):
    # kalau mau public, hapus parameter current_user + Depends
    return templates.TemplateResponse("inspection_form.html", {"request": request})

@app.get("/password/change", response_class=HTMLResponse, include_in_schema=False)
def password_change_page(request: Request, current_user: models.User = Depends(get_current_user)):
    return templates.TemplateResponse("change_password.html", {"request": request})

@app.post("/password/change", response_class=HTMLResponse, include_in_schema=False)
def password_change_submit(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if len(new_password) < 6 or new_password != confirm_password:
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "error": "Password minimal 6 karakter dan konfirmasi harus sama."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    user.password = pwd_context.hash(new_password)
    try:
        # Clear force-change flag if column exists
        if hasattr(user, "require_password_change"):
            user.require_password_change = 0
    except Exception:
        pass
    db.commit()
    # Redirect to dashboard if allowed; otherwise to inspection form
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/inspections", response_class=HTMLResponse, include_in_schema=False)
def inspections_list_page(request: Request, current_user: models.User = Depends(get_current_user)):
    return templates.TemplateResponse("inspections_list.html", {"request": request})

@app.get("/account", response_class=HTMLResponse, include_in_schema=False)
def account_page(request: Request, current_user: models.User = Depends(get_current_user)):
    return templates.TemplateResponse("account.html", {"request": request, "username": current_user.username, "role": current_user.role})

@app.get("/users", response_class=HTMLResponse, include_in_schema=False)
def users_page(request: Request, current_user: models.User = Depends(require_dashboard_access)):
    return templates.TemplateResponse("users.html", {"request": request})
# Routers
app.include_router(auth.router,        prefix="/api", tags=["auth"])
app.include_router(dashboard.router,   prefix="/api", tags=["dashboard"])
app.include_router(inspections.router, prefix="/api", tags=["inspections"])
app.include_router(terminals.router,   prefix="/api", tags=["terminals"])
app.include_router(admin.router,       prefix="/api", tags=["admin"])        # API admin
app.include_router(admin.router_pages,               tags=["admin pages"])   # halaman /admin/import
app.include_router(lokasi.router,      prefix="/api", tags=["lokasi"])       # lokasi master data

@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == status.HTTP_303_SEE_OTHER:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    # Serve JSON errors for API/JSON clients
    accept = (request.headers.get("accept") or "").lower()
    if request.url.path.startswith("/api") or "application/json" in accept:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    # Otherwise render HTML error page
    return templates.TemplateResponse("error.html", {"request": request, "error": exc.detail}, status_code=exc.status_code)

# ---- Dash analytics app mounted under /dashboard ----
try:
    from dash import Dash, html, dcc, Input, Output
    import plotly.graph_objs as go
    from sqlalchemy import func
    from datetime import datetime, timedelta, timezone

    def _fetch_summary_series(days: int = 30):
        db = SessionLocal()
        try:
            total = db.query(models.InspeksiTx).count()
            bagus = db.query(models.InspeksiTx).filter(models.InspeksiTx.status == 'Bagus').count()
            rusak = db.query(models.InspeksiTx).filter(models.InspeksiTx.status == 'Rusak').count()
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
            last24 = db.query(models.InspeksiTx).filter(models.InspeksiTx.ts_utc >= cutoff).count()

            # Series
            dcut = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
            day_col = func.substr(models.InspeksiTx.ts_utc, 1, 10)
            day_labeled = day_col.label('day')
            rows = (
                db.query(day_labeled, models.InspeksiTx.status, func.count(models.InspeksiTx.id_inspeksi))
                .filter(models.InspeksiTx.ts_utc >= dcut)
                .group_by(day_labeled, models.InspeksiTx.status)
                .order_by(day_labeled)
                .all()
            )
            series = {}
            for day, status, cnt in rows:
                d = series.setdefault(day, {"total": 0, "bagus": 0, "rusak": 0})
                d["total"] += int(cnt)
                s = (status or '').lower()
                if s == 'bagus': d['bagus'] += int(cnt)
                elif s == 'rusak': d['rusak'] += int(cnt)
            series_list = [
                {"day": k, **v} for k, v in sorted(series.items())
            ]

            # Top lokasi
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
            by_lokasi = [(n or '(tanpa nama)', int(c)) for n, c in q_loc]

            return {
                "totals": {"total": total, "bagus": bagus, "rusak": rusak, "last24h": last24},
                "series": series_list,
                "by_lokasi": by_lokasi,
            }
        finally:
            db.close()

    # Fetch lokasi options for filters
    def _lokasi_options():
        db = SessionLocal()
        try:
            rows = db.query(models.Lokasi).order_by(models.Lokasi.nama_lokasi.asc()).all()
            return [{"label": f"{r.nama_lokasi} (#{r.id_lokasi})", "value": r.id_lokasi} for r in rows]
        finally:
            db.close()

    # Mount Dash at an internal subpath; we'll proxy it at /dashboard to inject the site header
    dash_app = Dash(__name__, requests_pathname_prefix="/dashapp/")
    from datetime import date
    _today = date.today()
    _start_default = (_today - timedelta(days=30))
    controls = html.Div([
        html.Div([
            html.Label('Lokasi'),
            dcc.Dropdown(id='f_lokasi', options=_lokasi_options(), multi=True, placeholder='Semua lokasi'),
        ], style={'minWidth':'240px'}),
        html.Div([
            html.Label('Shift'),
            dcc.Dropdown(id='f_shift', options=[{'label':s, 'value':s} for s in ['Pagi','Siang','Malam']], multi=False, placeholder='Semua shift'),
        ], style={'minWidth':'180px'}),
        html.Div([
            html.Label('Tanggal'),
            dcc.DatePickerRange(id='f_range', start_date=_start_default, end_date=_today),
        ], style={'minWidth':'280px'}),
    ], style={'display':'flex','gap':'12px','flexWrap':'wrap','marginBottom':'10px'})

    dash_app.layout = html.Div([
        html.H2("Dashboard Inspeksi"),
        controls,
        html.Div(id='kpis', style={'display':'grid','gridTemplateColumns':'repeat(auto-fit, minmax(180px,1fr))','gap':'10px'}),
        dcc.Graph(id='tsChart'),
        html.Div(style={'display':'grid','gridTemplateColumns':'repeat(auto-fit, minmax(320px,1fr))','gap':'10px'}, children=[
            dcc.Graph(id='statusPie'),
            dcc.Graph(id='lokBar'),
        ]),
        dcc.Graph(id='geoMap'),
        dcc.Interval(id='iv', interval=60*1000, n_intervals=0),
    ], style={'padding':'10px'})

    def _fetch_filtered(days: int, lokasi_ids, shift, start_date, end_date):
        # Build time constraints
        start_iso = None
        end_iso = None
        if start_date:
            try:
                sd = datetime.fromisoformat(str(start_date))
            except Exception:
                sd = datetime.now(timezone.utc) - timedelta(days=days)
            start_iso = sd.strftime('%Y-%m-%dT00:00:00Z')
        if end_date:
            try:
                ed = datetime.fromisoformat(str(end_date))
            except Exception:
                ed = datetime.now(timezone.utc)
            end_iso = ed.strftime('%Y-%m-%dT23:59:59Z')

        db = SessionLocal()
        try:
            # Base filter on time
            q_tx = db.query(models.InspeksiTx)
            if start_iso:
                q_tx = q_tx.filter(models.InspeksiTx.ts_utc >= start_iso)
            else:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
                q_tx = q_tx.filter(models.InspeksiTx.ts_utc >= cutoff)
            if end_iso:
                q_tx = q_tx.filter(models.InspeksiTx.ts_utc <= end_iso)
            shift_val = (shift or '').strip() or None
            if shift_val:
                q_tx = q_tx.filter(models.InspeksiTx.shift == shift_val)
            if lokasi_ids:
                q_tx = (
                    q_tx.join(models.Item, models.Item.id_item == models.InspeksiTx.item_id)
                        .join(models.Area, models.Area.id_area == models.Item.id_area)
                        .join(models.Lokasi, models.Lokasi.id_lokasi == models.Area.id_lokasi)
                        .filter(models.Lokasi.id_lokasi.in_(lokasi_ids))
                )

            # Totals and status counts
            total = q_tx.count()
            bagus = q_tx.filter(models.InspeksiTx.status == 'Bagus').count()
            rusak = q_tx.filter(models.InspeksiTx.status == 'Rusak').count()
            cutoff24 = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
            last24 = q_tx.filter(models.InspeksiTx.ts_utc >= cutoff24).count()

            # Filters joining lokasi if needed
            # Series grouped by day and status
            day_col = func.substr(models.InspeksiTx.ts_utc, 1, 10)
            day_labeled = day_col.label('day')
            q_series = (
                db.query(day_labeled, models.InspeksiTx.status, func.count(models.InspeksiTx.id_inspeksi))
                .filter(models.InspeksiTx.ts_utc >= (start_iso or (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')))
            )
            if end_iso:
                q_series = q_series.filter(models.InspeksiTx.ts_utc <= end_iso)
            if shift_val:
                q_series = q_series.filter(models.InspeksiTx.shift == shift_val)
            if lokasi_ids:
                q_series = (
                    q_series.join(models.Item, models.Item.id_item == models.InspeksiTx.item_id)
                           .join(models.Area, models.Area.id_area == models.Item.id_area)
                           .join(models.Lokasi, models.Lokasi.id_lokasi == models.Area.id_lokasi)
                           .filter(models.Lokasi.id_lokasi.in_(lokasi_ids))
                )
            rows = q_series.group_by(day_labeled, models.InspeksiTx.status).order_by(day_labeled).all()
            series = {}
            for day, status, cnt in rows:
                d = series.setdefault(day, {"total": 0, "bagus": 0, "rusak": 0})
                d["total"] += int(cnt)
                s = (status or '').lower()
                if s == 'bagus': d['bagus'] += int(cnt)
                elif s == 'rusak': d['rusak'] += int(cnt)
            series_list = [
                {"day": k, **v} for k, v in sorted(series.items())
            ]

            # Top lokasi bar
            q_loc = (
                db.query(models.Lokasi.nama_lokasi, func.count(models.InspeksiTx.id_inspeksi))
                .join(models.Area, models.Area.id_lokasi == models.Lokasi.id_lokasi)
                .join(models.Item, models.Item.id_area == models.Area.id_area)
                .join(models.InspeksiTx, models.InspeksiTx.item_id == models.Item.id_item)
            )
            if start_iso:
                q_loc = q_loc.filter(models.InspeksiTx.ts_utc >= start_iso)
            if end_iso:
                q_loc = q_loc.filter(models.InspeksiTx.ts_utc <= end_iso)
            if shift:
                q_loc = q_loc.filter(models.InspeksiTx.shift == shift)
            if lokasi_ids:
                q_loc = q_loc.filter(models.Lokasi.id_lokasi.in_(lokasi_ids))
            q_loc = q_loc.group_by(models.Lokasi.id_lokasi).order_by(func.count(models.InspeksiTx.id_inspeksi).desc()).limit(10).all()
            by_lokasi = [(n or '(tanpa nama)', int(c)) for n, c in q_loc]

            # Geo data: lokasi markers and recent inspections points
            q_lokasi = db.query(models.Lokasi).order_by(models.Lokasi.nama_lokasi.asc())
            if lokasi_ids:
                q_lokasi = q_lokasi.filter(models.Lokasi.id_lokasi.in_(lokasi_ids))
            lokasi_rows = q_lokasi.all()
            lokasi_points = [
                (float(r.latitude), float(r.longitude), r.nama_lokasi)
                for r in lokasi_rows if (r.latitude is not None and r.longitude is not None)
            ]

            insp_points = []
            # Reuse q_tx (already time/shift/lokasi filtered) to fetch points
            for lat, lon in q_tx.with_entities(models.InspeksiTx.latitude, models.InspeksiTx.longitude).order_by(models.InspeksiTx.id_inspeksi.desc()).limit(500).all():
                try:
                    if lat is None or lon is None:
                        continue
                    insp_points.append((float(lat), float(lon)))
                except Exception:
                    continue

            return {
                "totals": {"total": total, "bagus": bagus, "rusak": rusak, "last24h": last24},
                "series": series_list,
                "by_lokasi": by_lokasi,
                "geo": {
                    "lokasi": lokasi_points,
                    "inspeksi": insp_points,
                }
            }
        finally:
            db.close()

    @dash_app.callback(
        [
            Output('kpis','children'),
            Output('tsChart','figure'),
            Output('statusPie','figure'),
            Output('lokBar','figure'),
            Output('geoMap','figure'),
        ],
        [Input('iv','n_intervals'), Input('f_lokasi','value'), Input('f_shift','value'), Input('f_range','start_date'), Input('f_range','end_date')]
    )
    def _update(_, lokasi_ids, shift, start_date, end_date):
        data = _fetch_filtered(30, lokasi_ids, shift, start_date, end_date)
        t = data['totals']
        def kbox(label, val):
            return html.Div([
                html.Div(label, style={'opacity':0.85}),
                html.Div(str(val), style={'fontSize':'28px','fontWeight':'bold'})
            ], style={'background':'#f5f5f5','padding':'10px','borderRadius':'8px'})
        kpis = [
            kbox('Total', t.get('total',0)),
            kbox('24 Jam', t.get('last24h',0)),
            kbox('Bagus', t.get('bagus',0)),
            kbox('Rusak', t.get('rusak',0)),
        ]
        xs = [r['day'] for r in data['series']]
        fig_ts = {
            'data': [
                go.Scatter(x=xs, y=[r['total'] for r in data['series']], mode='lines+markers', name='Total'),
                go.Scatter(x=xs, y=[r['rusak'] for r in data['series']], mode='lines+markers', name='Rusak'),
            ],
            'layout': go.Layout(title='Inspeksi per Hari', margin=dict(t=40,l=40,r=20,b=40))
        }
        fig_pie = {
            'data': [go.Pie(labels=['Bagus','Rusak'], values=[t.get('bagus',0), t.get('rusak',0)], hole=0.4)],
            'layout': go.Layout(title='Status')
        }
        locs = data['by_lokasi']
        fig_bar = {
            'data': [go.Bar(x=[c for _,c in locs], y=[n for n,_ in locs], orientation='h')],
            'layout': go.Layout(title='Top Lokasi (jumlah inspeksi)', margin=dict(l=140))
        }
        # Geo map figure (scattergeo without external tokens)
        geo = data.get('geo', {})
        locs = geo.get('lokasi', [])
        ips = geo.get('inspeksi', [])
        traces = []
        if locs:
            traces.append(
                go.Scattergeo(
                    lon=[b for _, b, _ in locs], lat=[a for a, _, _ in locs],
                    text=[n for _, _, n in locs], mode='markers', name='Lokasi',
                    marker=dict(color='#0072BC', size=8, symbol='circle')
                )
            )
        if ips:
            traces.append(
                go.Scattergeo(
                    lon=[b for _, b in ips], lat=[a for a, _ in ips],
                    mode='markers', name='Inspeksi',
                    marker=dict(color='#F26522', size=6, symbol='x')
                )
            )
        fig_map = {
            'data': traces,
            'layout': go.Layout(title='Sebaran Lokasi & Titik Inspeksi', geo=dict(showland=True, landcolor='#eaeaea'), margin=dict(t=40,l=20,r=20,b=20))
        }

        return kpis, fig_ts, fig_pie, fig_bar, fig_map

    # Auth + header-injecting proxy for /dashboard -> /dashapp
    class _DashProxy:
        def __init__(self, inner_asgi, src_prefix: str, dst_prefix: str):
            self.inner = inner_asgi
            self.src_prefix = src_prefix.rstrip('/')
            self.dst_prefix = dst_prefix.rstrip('/')

        async def __call__(self, scope, receive, send):
            if scope.get('type') != 'http':
                return await self.inner(scope, receive, send)

            req = StarletteRequest(scope, receive)
            # Auth guard
            token_cookie = req.cookies.get('access_token')
            def redirect_home():
                resp = RedirectResponse(url='/', status_code=status.HTTP_303_SEE_OTHER)
                return resp
            if not token_cookie:
                return await redirect_home()(scope, receive, send)
            parts = token_cookie.split(' ', 1)
            if len(parts) != 2 or parts[0].lower() != 'bearer':
                return await redirect_home()(scope, receive, send)
            try:
                payload = decode_token(parts[1])
                username = payload.get('sub')
            except Exception:
                username = None
            if not username:
                return await redirect_home()(scope, receive, send)
            db = SessionLocal()
            try:
                user = db.query(models.User).filter(models.User.username == username).first()
                if not user:
                    return await redirect_home()(scope, receive, send)
                role = _normalize_role(getattr(user, 'role', ''))
                allowed = {"team leader", "manager", "group head", "administrator"}
                if role not in allowed:
                    return await redirect_home()(scope, receive, send)
            finally:
                db.close()

            # Rewrite path to the mounted dash app
            path = scope.get('path', '')
            if not path.startswith(self.src_prefix):
                forward_path = self.dst_prefix + path
            else:
                forward_path = self.dst_prefix + path[len(self.src_prefix):]
            # Ensure trailing slash for root path to satisfy Dash prefix
            if path.rstrip('/') == self.src_prefix.rstrip('/') and not forward_path.endswith('/'):
                forward_path = forward_path + '/'
            if not forward_path.startswith('/'):
                forward_path = '/' + forward_path

            new_scope = dict(scope)
            new_scope['path'] = forward_path
            new_scope['raw_path'] = forward_path.encode('utf-8')

            # Capture response to inject header for HTML documents
            started = {}
            body_chunks = []
            async def send_wrapper(message):
                if message['type'] == 'http.response.start':
                    started['status'] = message['status']
                    # Copy headers
                    started['headers'] = [(k, v) for k, v in message.get('headers', [])]
                elif message['type'] == 'http.response.body':
                    body_chunks.append(message.get('body', b''))
                    if not message.get('more_body'):
                        status = started.get('status', 200)
                        headers = started.get('headers', [])
                        ctype = b"".join([v for k, v in headers if k.lower() == b'content-type'])
                        data = b"".join(body_chunks)
                        if status == 200 and b'text/html' in ctype and b'<body' in data.lower():
                            try:
                                txt = data.decode('utf-8', errors='ignore')
                                # Inject CSS link
                                if '</head>' in txt:
                                    css_tag = (
                                        '<link rel="stylesheet" href="/static/app.css">'
                                        '<style>body{color:#222;background:#fff;} a{color:#0072BC;}</style>'
                                    )
                                    txt = txt.replace('</head>', css_tag + '</head>', 1)
                                # Inject header nav after <body>
                                header = """
<header class="topbar"><div class="topbar-inner">
  <a class="brand" href="/dashboard">BIB</a>
  <nav id="nav-links" class="links"></nav>
</div></header>
<div style="height:56px"></div>
<script>
(async function(){
  const el = document.getElementById('nav-links');
  if (!el) return;
  function set(h){ el.innerHTML = h; }
  try {
    const r = await fetch('/api/me');
    if (!r.ok) throw 0;
    const me = await r.json();
    if (me && me.username) {
      const rr = (me.role || ' ').toLowerCase().replace('_',' ');
      const canDash = ['team leader','manager','group head','administrator','superadmin'].includes(rr);
      const isAdmin = rr === 'superadmin' || rr === 'administrator';
      set(
        (canDash ? '<a href="/dashboard">Dashboard</a>' : '') +
        '<a href="/inspection-form">Form Inspeksi</a>' +
        '<a href="/inspections">Daftar Inspeksi</a>' +
        (isAdmin ? '<a href="/admin/manage">Admin</a><a href="/admin/import">Import</a>' : '') +
        '<span class="sep"></span>' +
        '<a href="/account">Akun</a>' +
        '<span class="who">' + me.username + ' (' + me.role + ')</span>' +
        '<a href="/logout">Keluar</a>'
      );
    } else {
      set('<a href="/">Login</a>');
    }
  } catch(e) {
    set('<a href="/">Login</a>');
  }
})();
</script>
"""
                                lower = txt.lower()
                                idx = lower.find('<body')
                                if idx != -1:
                                    # Find end of opening body tag
                                    end = lower.find('>', idx)
                                    if end != -1:
                                        end += 1
                                        txt = txt[:end] + header + txt[end:]
                                data = txt.encode('utf-8')
                                # Ensure content-length matches
                                new_headers = []
                                for k, v in headers:
                                    if k.lower() == b'content-length':
                                        continue
                                    new_headers.append((k, v))
                                new_headers.append((b'content-length', str(len(data)).encode()))
                                await send({ 'type':'http.response.start', 'status': status, 'headers': new_headers })
                                await send({ 'type':'http.response.body', 'body': data, 'more_body': False })
                                return
                            except Exception:
                                # Fall through to original
                                pass
                        # Default passthrough
                        await send({ 'type':'http.response.start', 'status': status, 'headers': headers })
                        await send({ 'type':'http.response.body', 'body': data, 'more_body': False })
                        return
                    else:
                        # wait for more
                        pass
                else:
                    await send(message)

            return await self.inner(new_scope, receive, send_wrapper)

    # Mount proxy at /dashboard that forwards to internal /dashapp
    _dash_asgi = WSGIMiddleware(dash_app.server)
    app.mount("/dashboard", _DashProxy(_dash_asgi, src_prefix="/dashboard", dst_prefix="/dashapp"))
    # Also mount /dashapp for asset URLs referenced by Dash HTML
    app.mount("/dashapp", _dash_asgi)
except Exception as _e:
    # Dash not installed; dashboard iframe/link will fail gracefully
    pass
