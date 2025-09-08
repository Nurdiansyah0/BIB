# app/settings.py
from pathlib import Path
from fastapi.templating import Jinja2Templates
import os
from dotenv import load_dotenv

load_dotenv()

def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}

def _env_list(name: str, default: list[str] | None = None) -> list[str]:
    val = os.getenv(name)
    if not val:
        return default or []
    return [v.strip() for v in val.split(",") if v.strip()]

BASE_DIR = Path(__file__).resolve().parent.parent  # .../BIB
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")  # override via ENV/.env
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# Security & networking
CORS_ORIGINS = _env_list("CORS_ORIGINS", default=["*"])  # e.g. "http://localhost:3000,https://example.com"
ALLOWED_HOSTS = _env_list("ALLOWED_HOSTS", default=["*"])  # e.g. "example.com,.example.com,localhost"
COOKIE_SECURE = _env_bool("COOKIE_SECURE", False)  # set True behind HTTPS
ENABLE_HTTPS_REDIRECT = _env_bool("ENABLE_HTTPS_REDIRECT", False)

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
