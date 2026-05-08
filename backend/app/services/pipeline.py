from __future__ import annotations
import datetime
import json
import logging
import re
from pathlib import Path
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import ValidationError
from ..config import get_settings
from ..models.job import Job
from . import wiki_store, index_updater
from .llm_client import call_llm
from .plan import (
    Plan,
    CreateAction,
    MergeIntoAction,
    SupersedeAction,
    coerce_type_field,
    force_sources_frontmatter,
)

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


def _strip_codefence(s: str) -> str:
    """Some models wrap JSON in ```json ... ``` despite instructions."""
    s = s.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", s, flags=re.DOTALL)
    return m.group(1).strip() if m else s


def _try_parse_plan(llm_output: str) -> Optional[Plan]:
    """Try to parse LLM output as a JSON Plan. Returns None on any failure."""
    text = _strip_codefence(llm_output)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    # Allow either {"actions":[...]} or a bare list
    if isinstance(data, list):
        data = {"actions": data}
    try:
        return Plan.model_validate(data)
    except ValidationError as e:
        logger.warning(f"Plan validation failed: {e}")
        return None


def _resolve_action(
    action,
    wiki_path: Path,
    source_filename: str,
) -> Tuple[str, dict]:
    """Determine effective outcome for an action.

    Returns (outcome, info) where outcome is one of:
      - "executed_create"  → create written
      - "skipped_merge"    → merge_into skipped (Phase A)
      - "skipped_supersede"→ supersede skipped (Phase A)
      - "skipped_invalid_target" → merge_into/supersede target missing
      - "downgraded_merge" → create collided, downgraded to merge_into (skipped)
    """
    if isinstance(action, CreateAction):
        existing = wiki_store.read_page(wiki_path, action.page_path) is not None
        if existing:
            return ("downgraded_merge", {"target": action.page_path, "merged_content": action.content})
        return ("executed_create", {"page_path": action.page_path, "content": action.content})

    if isinstance(action, MergeIntoAction):
        if wiki_store.read_page(wiki_path, action.target) is None:
            return ("skipped_invalid_target", {"target": action.target, "kind": "merge_into"})
        return ("skipped_merge", {"target": action.target})

    if isinstance(action, SupersedeAction):
        if wiki_store.read_page(wiki_path, action.target) is None:
            return ("skipped_invalid_target", {"target": action.target, "kind": "supersede"})
        return ("skipped_supersede", {"target": action.target, "reason": action.reason})

    raise ValueError(f"Unknown action type: {type(action)}")


def _format_skip_log_line(outcome: str, info: dict) -> str:
    target = info.get("target", "?")
    stem = Path(target).stem
    if outcome == "skipped_merge":
        return f"- skipped (phase A): merge_into → [[{stem}]]"
    if outcome == "skipped_supersede":
        reason = info.get("reason") or ""
        suffix = f" ({reason})" if reason else ""
        return f"- skipped (phase A): supersede → [[{stem}]]{suffix}"
    if outcome == "skipped_invalid_target":
        kind = info.get("kind", "merge_into")
        return f"- skipped (phase A): {kind} → [[{stem}]] (target not found)"
    if outcome == "downgraded_merge":
        return f"- skipped (phase A): merge_into ← create-conflict → [[{stem}]]"
    return f"- skipped (phase A): {outcome}"


async def _persist_plan_payload(db: Optional[AsyncSession], job_id: str, payload_extra: dict):
    """Merge extra fields into Job.payload for visibility (SC-44)."""
    if db is None or not job_id:
        return
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        return
    merged = dict(job.payload or {})
    merged.update(payload_extra)
    job.payload = merged
    db.add(job)
    await db.commit()


async def _ingest_via_plan(
    plan: Plan,
    wiki_path: Path,
    source_filename: str,
    db: Optional[AsyncSession],
    job_id: str,
) -> Tuple[list[str], list[str], list[dict]]:
    """Execute Phase A plan handling. Returns (written_paths, skip_log_lines, plan_summary)."""
    written: list[str] = []
    skip_lines: list[str] = []
    summary: list[dict] = []

    for action in plan.actions:
        outcome, info = _resolve_action(action, wiki_path, source_filename)
        summary.append({
            "action": action.action,
            "outcome": outcome,
            "info": {k: v for k, v in info.items() if k != "merged_content" and k != "content"},
        })

        if outcome == "executed_create":
            content = info["content"]
            content = force_sources_frontmatter(content, source_filename)
            content, type_corrected = coerce_type_field(content)
            if type_corrected:
                logger.info(f"[INGEST] type enum corrected → reference for {info['page_path']}")
                skip_lines.append(
                    f"- normalized: type enum corrected → reference for [[{Path(info['page_path']).stem}]]"
                )
            wiki_store.write_pages(wiki_path, {info["page_path"]: content})
            written.append(info["page_path"])
        else:
            skip_lines.append(_format_skip_log_line(outcome, info))

    return written, skip_lines, summary


async def run_ingest(source_path: str, db: AsyncSession, job_id: str = ""):
    settings = get_settings()
    wiki_path = Path(settings.wiki_store_path)
    wiki_store._get_repo(wiki_path)
    wiki_store.ensure_sheska_yaml(wiki_path, settings.source_base_url)

    source_text = _parse_source_text(source_path)
    source_filename = Path(source_path).name
    system_prompt = _load_prompt("ingest")

    # SC-41: inject existing index.md into LLM context
    existing_index = wiki_store.read_page(wiki_path, "index.md")
    if not existing_index or "no pages yet" in existing_index.lower() or "*Empty" in existing_index:
        index_block = "EXISTING WIKI INDEX:\n(no existing pages yet — this is the first ingest)"
    else:
        index_block = f"EXISTING WIKI INDEX:\n{existing_index.strip()}"

    user_content = (
        f"{index_block}\n\n"
        f"NEW SOURCE FILE: {source_filename}\n\n"
        f"NEW SOURCE CONTENT:\n{source_text}"
    )

    llm_output = await call_llm(
        system_prompt,
        user_content,
        response_format={"type": "json_object"},
    )
    logger.info(f"[INGEST] LLM raw output ({len(llm_output)} chars): {llm_output[:500]!r}")

    plan = _try_parse_plan(llm_output)
    fallback_used = False
    plan_summary: list[dict] = []
    skip_lines: list[str] = []

    if plan is not None:
        # SC-43/44: process plan actions
        written, skip_lines, plan_summary = await _ingest_via_plan(
            plan, wiki_path, source_filename, db, job_id
        )
    else:
        # SC-45: graceful degrade to legacy fallback
        logger.warning("[INGEST] JSON plan parse failed; falling back to legacy parser")
        fallback_used = True
        legacy_pages = wiki_store.parse_llm_pages(
            llm_output,
            fallback_stem=Path(source_filename).stem,
            source_filename=source_filename,
        )
        if not legacy_pages:
            snippet = llm_output[:200].replace("\n", " ")
            raise ValueError(
                "LLM output is neither valid JSON Plan nor parseable legacy format. "
                f"Got: {snippet!r}"
            )
        # Apply sources injection + type coercion to each fallback page
        coerced_pages: dict[str, str] = {}
        for fname, content in legacy_pages.items():
            content = force_sources_frontmatter(content, source_filename)
            content, _ = coerce_type_field(content)
            coerced_pages[fname] = content
        written = wiki_store.write_pages(wiki_path, coerced_pages)
        plan_summary = [{"action": "legacy_fallback", "outcome": "executed", "info": {"pages": written}}]

    # Refresh index.md regardless of path taken
    all_pages = wiki_store.list_pages(wiki_path)
    index_content = index_updater.rebuild_index(wiki_path, all_pages)
    (wiki_path / "index.md").write_text(index_content, encoding="utf-8")

    commit_files = list(written) + ["index.md"]
    now = datetime.datetime.utcnow().isoformat() + "Z"

    log_entry = (
        f"## {now} | INGEST | SUCCESS | job_id: {job_id}\n"
        f"- source: {source_filename}\n"
    )
    if fallback_used:
        log_entry += "- note: JSON parse failed; used legacy fallback\n"
    if written:
        log_entry += f"- created: {', '.join(f'[[{Path(p).stem}]]' for p in written)}\n"
    for line in skip_lines:
        log_entry += f"{line}\n"
    log_entry = log_entry.rstrip()

    wiki_store.append_log(wiki_path, log_entry)
    commit_files.append("log.md")

    wiki_store.commit_changes(
        wiki_path, commit_files,
        f"ingest: {source_filename} → {len(written)} page(s) [job:{job_id}]"
    )

    # SC-44: persist plan summary into Job.payload for Jobs tab visibility
    await _persist_plan_payload(
        db, job_id,
        {"plan_summary": plan_summary, "fallback_used": fallback_used},
    )

    logger.info(f"[INGEST] {source_filename} → written={written}, skipped={len(skip_lines)}")


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
