from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import engine, SessionLocal
from app import models
from sqlalchemy.orm import Session
import os
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt

# Konfigurasi
SECRET_KEY = "your-secret-key-here"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Buat folder jika belum ada
os.makedirs("static", exist_ok=True)
os.makedirs("app/templates", exist_ok=True)

# Inisialisasi database
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# Setup password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")

# Dependency untuk database
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Fungsi pembantu
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Route untuk halaman login
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

# Route untuk proses login
@app.post("/login")
async def handle_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    # Cari user di database
    user = db.query(models.User).filter(models.User.username == username).first()
    
    if not user or not verify_password(password, user.password):
        # Tampilkan pesan error di template
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Username atau password salah"
        }, status_code=400)
    
    # Buat token JWT
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires
    )
    
    # Redirect ke dashboard dengan token
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response

# Route untuk dashboard (contoh)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    # Di sini Anda bisa menambahkan verifikasi token
    return templates.TemplateResponse("dashboard.html", {"request": request})

# Error handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "error": exc.detail},
        status_code=exc.status_code
    )