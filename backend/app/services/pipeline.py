"""LLM pipeline — Ingest and Edit flows. Stub implementations for Phase 1."""
import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def run_ingest(source_path: str, db: AsyncSession):
    """Phase 2 implementation target. Stub for Phase 1 testing."""
    logger.info(f"[INGEST STUB] source_path={source_path}")


async def run_edit(page_path: str, edit_text: str, db: AsyncSession):
    """Phase 2 implementation target. Stub for Phase 1 testing."""
    logger.info(f"[EDIT STUB] page_path={page_path}, text={edit_text[:80]}")
