# app/main.py
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import Base, engine, SessionLocal
from . import models
from .routers import auth, dashboard, inspections, terminals, admin
from .settings import BASE_DIR, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, templates
from .deps import get_db, get_current_user  # <- pakai dari deps

app = FastAPI(title="BIB")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
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
    resp = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie("access_token", f"Bearer {token}", httponly=True, samesite="lax", max_age=ACCESS_TOKEN_EXPIRE_MINUTES*60)
    return resp

@app.get("/logout", include_in_schema=False)
def logout():
    resp = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("access_token")
    return resp

@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard_page(request: Request, current_user: models.User = Depends(get_current_user)):
    return templates.TemplateResponse("dashboard.html", {"request": request, "username": current_user.username, "role": current_user.role})
@app.get("/inspection-form", response_class=HTMLResponse, include_in_schema=False)
def inspection_form_page(request: Request, current_user: models.User = Depends(get_current_user)):
    # kalau mau public, hapus parameter current_user + Depends
    return templates.TemplateResponse("inspection_form.html", {"request": request})
# Routers
app.include_router(auth.router,        prefix="/api", tags=["auth"])
app.include_router(dashboard.router,   prefix="/api", tags=["dashboard"])
app.include_router(inspections.router, prefix="/api", tags=["inspections"])
app.include_router(terminals.router,   prefix="/api", tags=["terminals"])
app.include_router(admin.router,       prefix="/api", tags=["admin"])        # API admin
app.include_router(admin.router,                     tags=["admin pages"])   # halaman /admin/import

@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == status.HTTP_303_SEE_OTHER:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("error.html", {"request": request, "error": exc.detail}, status_code=exc.status_code)
