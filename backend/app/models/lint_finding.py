from __future__ import annotations
import enum
from typing import Optional
from datetime import datetime
from sqlalchemy import String, Text, Enum as SAEnum, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from ..db import Base


class LintCategory(str, enum.Enum):
    """Enumerated finding category. v0.5 active = user_reported only.

    Other categories are reserved for v0.5.1+ Scanner/Agent paths so the model
    can absorb them without migration when those phases land.
    """
    dangling_link = "dangling_link"
    orphan_page = "orphan_page"
    frontmatter_missing = "frontmatter_missing"
    stale = "stale"
    duplicate = "duplicate"
    quality_low = "quality_low"
    split_candidate = "split_candidate"
    merge_candidate = "merge_candidate"
    tag_inconsistency = "tag_inconsistency"
    user_reported = "user_reported"
    other = "other"


class LintSource(str, enum.Enum):
    lint_tier1 = "lint:tier1"
    lint_tier2 = "lint:tier2"
    user_web = "user:web"
    agent_explorer = "agent:explorer"  # reserved for v0.6+


class LintStatus(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    wont_fix = "wont_fix"
    # resolved is reserved for v0.5.1+ (Tier 3 execution)


class LintFinding(Base):
    """ADR-0018 — single source of truth for lint findings.

    Audit trail is preserved by design: there is no DELETE path. Status moves one
    direction (open → acknowledged | wont_fix) and is never rolled back.
    """

    __tablename__ = "lint_findings"

    finding_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    category: Mapped[LintCategory] = mapped_column(SAEnum(LintCategory), nullable=False)
    source: Mapped[LintSource] = mapped_column(SAEnum(LintSource), nullable=False)
    status: Mapped[LintStatus] = mapped_column(
        SAEnum(LintStatus), nullable=False, default=LintStatus.open
    )
    page_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    reported_by: Mapped[str] = mapped_column(String(255), nullable=False)
    decided_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    resolution_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
