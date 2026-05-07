from __future__ import annotations
import datetime
import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import get_settings
from . import wiki_store, index_updater
from .llm_client import call_llm

logger = logging.getLogger(__name__)


def _load_prompt(name: str) -> str:
    settings = get_settings()
    path = Path(settings.prompts_path) / f"{name}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _parse_source_text(source_path: str) -> str:
    path = Path(source_path)
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {source_path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        return path.read_text(encoding="utf-8")


async def run_ingest(source_path: str, db: AsyncSession, job_id: str = ""):
    settings = get_settings()
    wiki_path = Path(settings.wiki_store_path)
    wiki_store._get_repo(wiki_path)
    wiki_store.ensure_sheska_yaml(wiki_path, settings.source_base_url)

    source_text = _parse_source_text(source_path)
    source_filename = Path(source_path).name
    system_prompt = _load_prompt("ingest")

    user_content = f"Source file: {source_filename}\n\n{source_text}"
    llm_output = await call_llm(system_prompt, user_content)

    pages = wiki_store.parse_llm_pages(llm_output)
    if not pages:
        logger.warning(f"LLM returned no parseable pages for {source_filename}")
        return

    written = wiki_store.write_pages(wiki_path, pages)

    all_pages = wiki_store.list_pages(wiki_path)
    index_content = index_updater.rebuild_index(wiki_path, all_pages)
    (wiki_path / "index.md").write_text(index_content, encoding="utf-8")

    commit_files = written + ["index.md"]
    now = datetime.datetime.utcnow().isoformat() + "Z"
    wiki_store.append_log(
        wiki_path,
        f"## {now} | INGEST | SUCCESS | job_id: {job_id}\n"
        f"- source: {source_filename}\n"
        f"- created/updated: {', '.join(f'[[{Path(p).stem}]]' for p in written)}"
    )
    commit_files.append("log.md")

    wiki_store.commit_changes(
        wiki_path, commit_files,
        f"ingest: {source_filename} → {len(written)} page(s) [job:{job_id}]"
    )
    logger.info(f"[INGEST] {source_filename} → {written}")


async def run_edit(page_path: str, edit_text: str, db: AsyncSession, job_id: str = ""):
    settings = get_settings()
    wiki_path = Path(settings.wiki_store_path)
    wiki_store._get_repo(wiki_path)  # ensure repo exists before any write

    current_content = wiki_store.read_page(wiki_path, page_path)
    if current_content is None:
        raise FileNotFoundError(f"Wiki page not found: {page_path}")

    system_prompt = _load_prompt("edit")
    user_content = (
        f"Current page ({page_path}):\n\n{current_content}\n\n"
        f"Edit request: {edit_text}"
    )
    updated_content = await call_llm(system_prompt, user_content)

    filepath = wiki_path / page_path
    filepath.write_text(updated_content, encoding="utf-8")

    all_pages = wiki_store.list_pages(wiki_path)
    index_content = index_updater.rebuild_index(wiki_path, all_pages)
    (wiki_path / "index.md").write_text(index_content, encoding="utf-8")

    now = datetime.datetime.utcnow().isoformat() + "Z"
    stem = Path(page_path).stem
    wiki_store.append_log(
        wiki_path,
        f"## {now} | EDIT | SUCCESS | job_id: {job_id}\n"
        f"- page: [[{stem}]]\n"
        f"- modified: [[{stem}]]"
    )

    wiki_store.commit_changes(
        wiki_path, [page_path, "index.md", "log.md"],
        f"edit: {page_path} [job:{job_id}]"
    )
    logger.info(f"[EDIT] {page_path} updated [job:{job_id}]")
