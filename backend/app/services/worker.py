from __future__ import annotations
import asyncio
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select
from ..models.job import Job, JobStatus

logger = logging.getLogger(__name__)

_queue: asyncio.Queue = asyncio.Queue()
_session_factory: Optional[async_sessionmaker] = None


def init_worker(session_factory: async_sessionmaker):
    global _session_factory
    _session_factory = session_factory


async def enqueue_job(job_id: str):
    await _queue.put(job_id)


async def _process_job(job: Job, db: AsyncSession):
    from .pipeline import run_ingest, run_edit, run_wiki_command
    from .llm_client import AgenticCancelled
    from ..models.job import JobType

    try:
        if job.type == JobType.ingest:
            await run_ingest(job.payload["source_path"], db, job_id=job.id)
        elif job.type == JobType.edit:
            await run_edit(job.payload["page_path"], job.payload["edit_text"], db, job_id=job.id)
        elif job.type == JobType.wiki_command:
            await run_wiki_command(job.payload["command_text"], db, job_id=job.id)
        job.status = JobStatus.done
    except AgenticCancelled:
        logger.info(f"Job {job.id} cancelled by user")
        job.status = JobStatus.cancelled
    except Exception as e:
        logger.error(f"Job {job.id} failed: {e}")
        job.status = JobStatus.failed
        job.error_msg = str(e)[:1000]


async def worker_loop():
    logger.info("Worker loop started")
    while True:
        job_id = await _queue.get()
        if _session_factory is None:
            _queue.task_done()
            continue

        async with _session_factory() as db:
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                _queue.task_done()
                continue

            job.status = JobStatus.processing
            await db.commit()

            await _process_job(job, db)
            await db.commit()

        _queue.task_done()
