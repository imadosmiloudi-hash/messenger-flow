from __future__ import annotations

import uuid
from pathlib import Path

import bleach
from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import MediaAsset

ALLOWED_IMAGE = {"image/jpeg", "image/png", "image/gif", "image/webp"}
# audio/x-m4a and audio/m4a are common phone MIME aliases for M4A (treat as audio/mp4)
ALLOWED_AUDIO = {
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "audio/wav",
    "audio/aac",
    "audio/x-m4a",
    "audio/m4a",
}
ALLOWED_VIDEO = {"video/mp4", "video/quicktime", "video/webm"}
# Meta Messenger does not reliably accept HEIC/HEIF — reject with a clear message
UNSUPPORTED_HEIC = {"image/heic", "image/heif"}

# Normalize phone aliases to Meta-friendly MIME types when storing
CONTENT_TYPE_NORMALIZE = {
    "audio/x-m4a": "audio/mp4",
    "audio/m4a": "audio/mp4",
}

TYPE_MAP = {
    **{m: "image" for m in ALLOWED_IMAGE},
    **{m: "audio" for m in ALLOWED_AUDIO},
    **{m: "video" for m in ALLOWED_VIDEO},
}


def validate_and_save_upload(db: Session, file: UploadFile) -> MediaAsset:
    settings = get_settings()
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type in UNSUPPORTED_HEIC:
        raise HTTPException(
            status_code=400,
            detail="HEIC/HEIF images are not supported by Messenger. Convert to JPEG or PNG on your phone, then upload.",
        )
    if content_type not in TYPE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported media type: {content_type}. Allowed: jpeg/png/webp/gif, mp3/m4a/aac/ogg/wav, mp4/mov/webm.",
        )
    content_type = CONTENT_TYPE_NORMALIZE.get(content_type, content_type)

    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = file.file.read()
    if len(data) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File too large (max {settings.max_upload_mb}MB)")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    safe_name = bleach.clean(file.filename or "upload", tags=[], strip=True)
    safe_name = "".join(c for c in safe_name if c.isalnum() or c in "._-")[:180] or "upload"
    media_type = TYPE_MAP[content_type]
    asset_id = str(uuid.uuid4())
    ext = Path(safe_name).suffix or {
        "image": ".jpg",
        "audio": ".mp3",
        "video": ".mp4",
    }[media_type]

    upload_dir = Path(settings.media_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    storage_name = f"{asset_id}{ext}"
    storage_path = upload_dir / storage_name
    storage_path.write_bytes(data)

    public_url = f"{settings.public_base_url.rstrip('/')}/media/files/{storage_name}"

    asset = MediaAsset(
        id=asset_id,
        filename=safe_name,
        content_type=content_type,
        media_type=media_type,
        size_bytes=len(data),
        storage_path=str(storage_path),
        public_url=public_url,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset
