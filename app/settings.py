# app/settings.py
from pathlib import Path
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent  # .../BIB
SECRET_KEY = "your-secret-key-here"  # ganti untuk produksi (ENV)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
