from __future__ import annotations
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from ..db import get_db
from ..models.job import Job, JobType, JobStatus
from ..models.user import User, Role
from ..services.auth_service import get_current_user

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobResponse(BaseModel):
    id: str
    type: JobType
    payload: dict
    status: JobStatus
    created_by: int
    error_msg: Optional[str]

    class Config:
        from_attributes = True


class PaginatedJobs(BaseModel):
    items: List[JobResponse]
    total: int
    page: int
    size: int


@router.get("/", response_model=PaginatedJobs)
async def list_jobs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Job).order_by(Job.created_at.desc())
    count_stmt = select(func.count(Job.id))
    if current_user.role != Role.admin:
        stmt = stmt.where(Job.created_by == current_user.id)
        count_stmt = count_stmt.where(Job.created_by == current_user.id)

    total = (await db.execute(count_stmt)).scalar_one()
    offset = (page - 1) * size
    stmt = stmt.offset(offset).limit(size)
    items = (await db.execute(stmt)).scalars().all()
    return PaginatedJobs(items=items, total=total, page=page, size=size)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != Role.admin and job.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return job


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SC-66: request cancellation of a running job. Sets status=cancelling;
    the worker transitions to cancelled at the next iteration boundary."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role != Role.admin and job.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if job.status in (JobStatus.done, JobStatus.failed, JobStatus.cancelled):
        # idempotent — already terminal
        return job
    if job.status not in (JobStatus.cancelling, JobStatus.processing, JobStatus.pending):
        raise HTTPException(status_code=409, detail=f"Cannot cancel from status {job.status}")
    job.status = JobStatus.cancelling
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job
