# app/routers/admin.py
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import pandas as pd
import io, secrets, time

from ..database import SessionLocal
from .. import models
from ..deps import get_db, require_superadmin    # <- dari deps
from ..settings import templates                 # <- dari settings

router = APIRouter()

# (kode IMPORT_CACHE, cleanup_cache, infer_schema_from_df, dll tetap sama seperti sebelumnya)

@router.get("/admin/import", response_class=HTMLResponse)
def admin_import_page(request: Request, _: models.User = Depends(require_superadmin)):
    return templates.TemplateResponse("admin_import.html", {"request": request})

# ... endpoint /admin/import-xlsx dan /admin/commit-import tetap sama ...
