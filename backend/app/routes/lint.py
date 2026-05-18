from __future__ import annotations
import datetime
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from ..db import get_db
from ..models.lint_finding import LintFinding, LintCategory, LintSource, LintStatus
from ..models.user import User, Role
from ..services.auth_service import get_current_user, require_admin

router = APIRouter(prefix="/api/lint", tags=["lint"])


# ============================== Pydantic schemas ==============================

class FindingResponse(BaseModel):
    finding_id: str
    category: LintCategory
    source: LintSource
    status: LintStatus
    page_path: Optional[str]
    description: str
    details: Optional[dict] = None
    created_at: datetime.datetime
    reported_by: str
    decided_by: Optional[str] = None
    decided_at: Optional[datetime.datetime] = None
    resolution_reason: Optional[str] = None

    class Config:
        from_attributes = True


class PaginatedFindings(BaseModel):
    items: List[FindingResponse]
    total: int
    page: int
    size: int


class FindingCreate(BaseModel):
    """SC-81: user-submitted finding. source is forced to user:web by the server."""
    page_path: Optional[str] = Field(default=None, max_length=255)
    description: str = Field(min_length=1, max_length=2000)
    category: LintCategory = LintCategory.user_reported
    details: Optional[dict] = None


class FindingDecision(BaseModel):
    """SC-83: status change. Only acknowledged / wont_fix are allowed from open."""
    status: LintStatus
    resolution_reason: str = Field(min_length=1, max_length=2000)


# ============================== Endpoints ==============================

@router.post("/findings", response_model=FindingResponse, status_code=201)
async def create_finding(
    body: FindingCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SC-81: User-reported finding. source forced to user:web."""
    finding = LintFinding(
        finding_id=str(uuid.uuid4()),
        category=body.category,
        source=LintSource.user_web,
        status=LintStatus.open,
        page_path=body.page_path,
        description=body.description,
        details=body.details,
        reported_by=current_user.email,
    )
    db.add(finding)
    await db.commit()
    await db.refresh(finding)
    return finding


@router.get("/findings", response_model=PaginatedFindings)
async def list_findings(
    status: Optional[LintStatus] = None,
    category: Optional[LintCategory] = None,
    source: Optional[LintSource] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SC-82: paginated listing with filters, sorted by created_at desc."""
    stmt = select(LintFinding).order_by(LintFinding.created_at.desc())
    count_stmt = select(func.count(LintFinding.finding_id))
    if status is not None:
        stmt = stmt.where(LintFinding.status == status)
        count_stmt = count_stmt.where(LintFinding.status == status)
    if category is not None:
        stmt = stmt.where(LintFinding.category == category)
        count_stmt = count_stmt.where(LintFinding.category == category)
    if source is not None:
        stmt = stmt.where(LintFinding.source == source)
        count_stmt = count_stmt.where(LintFinding.source == source)

    total = (await db.execute(count_stmt)).scalar_one()
    offset = (page - 1) * size
    stmt = stmt.offset(offset).limit(size)
    items = (await db.execute(stmt)).scalars().all()
    return PaginatedFindings(items=items, total=total, page=page, size=size)


@router.get("/findings/{finding_id}", response_model=FindingResponse)
async def get_finding(
    finding_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LintFinding).where(LintFinding.finding_id == finding_id)
    )
    finding = result.scalar_one_or_none()
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


@router.patch("/findings/{finding_id}", response_model=FindingResponse)
async def decide_finding(
    finding_id: str,
    body: FindingDecision,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """SC-83: Admin-only status change with required resolution_reason.

    SC-84: status flows one direction (open → acknowledged | wont_fix).
    Anything else (incl. attempts to set status=open or revert from terminal) is rejected.
    """
    if body.status not in (LintStatus.acknowledged, LintStatus.wont_fix):
        raise HTTPException(
            status_code=400,
            detail="status must be acknowledged or wont_fix",
        )
    result = await db.execute(
        select(LintFinding).where(LintFinding.finding_id == finding_id)
    )
    finding = result.scalar_one_or_none()
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    if finding.status != LintStatus.open:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition from terminal status {finding.status.value}",
        )

    finding.status = body.status
    finding.resolution_reason = body.resolution_reason
    finding.decided_by = admin.email
    finding.decided_at = datetime.datetime.utcnow()
    db.add(finding)
    await db.commit()
    await db.refresh(finding)
    return finding
