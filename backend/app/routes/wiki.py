from __future__ import annotations
import io
import uuid
import zipfile
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_db
from ..models.job import Job, JobType, JobStatus
from ..models.user import User
from ..services.auth_service import get_current_user
from ..services.worker import enqueue_job
from ..services import wiki_store
from ..config import get_settings

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


def _wiki_path() -> Path:
    return Path(get_settings().wiki_store_path)


class EditRequest(BaseModel):
    edit_text: str


@router.get("/pages")
async def list_pages(current_user: User = Depends(get_current_user)):
    pages = wiki_store.list_pages(_wiki_path())
    return {"pages": pages}


@router.get("/pages/{page_path:path}")
async def get_page(
    page_path: str,
    current_user: User = Depends(get_current_user),
):
    content = wiki_store.read_page(_wiki_path(), page_path)
    if content is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"page_path": page_path, "content": content}


@router.post("/pages/{page_path:path}/edit", status_code=202)
async def request_edit(
    page_path: str,
    body: EditRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if wiki_store.read_page(_wiki_path(), page_path) is None:
        raise HTTPException(status_code=404, detail="Page not found")

    job = Job(
        id=str(uuid.uuid4()),
        type=JobType.edit,
        payload={"page_path": page_path, "edit_text": body.edit_text},
        status=JobStatus.pending,
        created_by=current_user.id,
    )
    db.add(job)
    await db.commit()
    await enqueue_job(job.id)

    return {"job_id": job.id, "page_path": page_path, "status": "queued"}


@router.get("/index")
async def get_index(current_user: User = Depends(get_current_user)):
    content = wiki_store.read_page(_wiki_path(), "index.md")
    return {"content": content or ""}


@router.get("/log")
async def get_log(current_user: User = Depends(get_current_user)):
    content = wiki_store.read_page(_wiki_path(), "log.md")
    return {"content": content or ""}


@router.get("/zip")
async def download_zip(current_user: User = Depends(get_current_user)):
    wiki_path = _wiki_path()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in wiki_path.rglob("*"):
            if fpath.is_file() and ".git" not in fpath.parts:
                zf.write(fpath, fpath.relative_to(wiki_path))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=wiki.zip"},
    )
