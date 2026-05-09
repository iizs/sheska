from __future__ import annotations
from typing import Optional
from sqlalchemy import String, Enum as SAEnum, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from ..db import Base
import enum
import datetime


class JobType(str, enum.Enum):
    ingest = "INGEST"
    edit = "EDIT"
    wiki_command = "WIKI_COMMAND"


class JobStatus(str, enum.Enum):
    pending = "Pending"
    processing = "Processing"
    done = "Done"
    failed = "Failed"


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    type: Mapped[JobType] = mapped_column(SAEnum(JobType), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        SAEnum(JobStatus), nullable=False, default=JobStatus.pending
    )
    created_by: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    error_msg: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
