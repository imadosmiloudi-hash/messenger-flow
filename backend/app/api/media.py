from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.entities import MediaAsset, User
from app.schemas.common import MediaAssetOut
from app.security.auth import get_current_user
from app.services.media import validate_and_save_upload

router = APIRouter(tags=["media"])


@router.post("/api/media/upload", response_model=MediaAssetOut, status_code=201)
def upload_media(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return validate_and_save_upload(db, file)


@router.get("/api/media", response_model=list[MediaAssetOut])
def list_media(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(200).all()


@router.get("/media/files/{filename}")
def serve_media_file(filename: str):
    """Public file serving so Meta can fetch HTTPS media URLs (via ngrok/public URL)."""
    settings = get_settings()
    # Prevent path traversal
    safe = Path(filename).name
    path = Path(settings.media_upload_dir) / safe
    if not path.is_file():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)
