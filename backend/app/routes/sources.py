from __future__ import annotations
import uuid
import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from ..models.job import Job, JobType, JobStatus
from ..models.user import User
from ..services.auth_service import get_current_user, require_admin
from ..services.worker import enqueue_job
from ..config import get_settings

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _source_store() -> Path:
    return Path(get_settings().source_store_path)


def _allowed(filename: str) -> bool:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in get_settings().allowed_extensions


@router.post("/", status_code=202)
async def upload_source(
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not _allowed(file.filename or ""):
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {get_settings().allowed_extensions}",
        )

    store = _source_store()
    store.mkdir(parents=True, exist_ok=True)
    dest = store / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    job = Job(
        id=str(uuid.uuid4()),
        type=JobType.ingest,
        payload={"source_path": str(dest)},
        status=JobStatus.pending,
        created_by=admin.id,
    )
    db.add(job)
    await db.commit()
    await enqueue_job(job.id)

    return {"job_id": job.id, "filename": file.filename, "status": "queued"}


@router.get("/")
async def list_sources(
    current_user: User = Depends(get_current_user),
):
    store = _source_store()
    store.mkdir(parents=True, exist_ok=True)
    files = [
        {"filename": f.name, "size": f.stat().st_size}
        for f in store.iterdir()
        if f.is_file() and not f.name.startswith(".")
    ]
    return files


@router.get("/{filename}")
async def get_source(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    filepath = _source_store() / filename
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="Source file not found")
    return FileResponse(str(filepath), filename=filename)
