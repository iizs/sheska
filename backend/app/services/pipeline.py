from __future__ import annotations
import datetime
import json
import logging
import re
from pathlib import Path
from typing import Optional, Tuple, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import ValidationError
from ..config import get_settings, resolve_path
from ..models.job import Job
from . import wiki_store, index_updater
from .llm_client import call_llm
from .plan import (
    Plan,
    CreateAction,
    MergeIntoAction,
    SupersedeAction,
    DeleteAction,
    coerce_type_field,
    force_sources_frontmatter,
    merge_frontmatter,
    is_reserved_path,
)

logger = logging.getLogger(__name__)


def _load_prompt(name: str) -> str:
    """Load prompt file. Resolves relative paths from project root or backend root.

    Raises FileNotFoundError if the file is missing — silent empty-string return
    causes downstream LLM API errors that are hard to diagnose.
    """
    settings = get_settings()
    prompts_dir = resolve_path(settings.prompts_path)
    path = prompts_dir / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {path}. "
            f"PROMPTS_PATH={settings.prompts_path!r}; resolved={prompts_dir}."
        )
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"Prompt file is empty: {path}")
    return content


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


def _format_log_line(outcome: str, info: dict) -> str:
    """SC-61: unified log line prefixes (executed: / rejected: / skipped: / failed:)."""
    target = info.get("target") or info.get("page_path") or "?"
    stem = Path(target).stem if target != "?" else "?"
    if outcome == "executed_create":
        return f"- executed: create → [[{stem}]]"
    if outcome == "executed_merge":
        return f"- executed: merge_into → [[{stem}]]"
    if outcome == "executed_supersede":
        reason = info.get("reason") or ""
        suffix = f" (reason: {reason})" if reason else ""
        return f"- executed: supersede → [[{stem}]]{suffix}"
    if outcome == "executed_delete":
        reason = info.get("reason") or ""
        suffix = f" (reason: {reason})" if reason else ""
        return f"- executed: delete → [[{stem}]]{suffix}"
    if outcome == "executed_merge_from_conflict":
        return f"- executed: merge_into ← create-conflict → [[{stem}]]"
    if outcome == "skipped_invalid_target":
        kind = info.get("kind", "merge_into")
        return f"- skipped: {kind} → [[{stem}]] (target not found)"
    if outcome == "rejected_reserved":
        return f"- rejected: delete → [[{stem}]] (reserved file)"
    if outcome == "rejected_forbidden_in_ingest":
        return f"- rejected: delete → [[{stem}]] (forbidden in INGEST)"
    if outcome == "failed":
        err = info.get("error") or ""
        return f"- failed: {info.get('action', '?')} → [[{stem}]] (error: {err})"
    if outcome == "normalized_type":
        return f"- normalized: type enum corrected → reference for [[{stem}]]"
    return f"- {outcome}"


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


def _now_str() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _execute_plan(
    plan: Plan,
    wiki_path: Path,
    *,
    job_type: str,                        # "ingest" or "wiki_command"
    source_filename: str = "",
) -> Tuple[List[str], List[str], List[str], List[dict]]:
    """Execute Phase B plan handling.

    Returns (written_paths, deleted_paths, log_lines, plan_summary).
    """
    written: list[str] = []
    deleted: list[str] = []
    log_lines: list[str] = []
    summary: list[dict] = []

    for action in plan.actions:
        try:
            outcome, info = _resolve_and_execute(
                action, wiki_path,
                job_type=job_type,
                source_filename=source_filename,
            )
        except Exception as e:
            outcome = "failed"
            info = {
                "action": getattr(action, "action", "unknown"),
                "target": getattr(action, "target", None) or getattr(action, "page_path", "?"),
                "error": str(e)[:200],
            }
            logger.exception("Action %r failed: %s", info["action"], e)

        summary.append({
            "action": info.get("action", getattr(action, "action", "?")),
            "outcome": outcome,
            "info": {k: v for k, v in info.items()
                     if k not in {"merged_content", "content", "new_content"}},
        })

        if outcome == "executed_create":
            written.append(info["page_path"])
        elif outcome in {"executed_merge", "executed_supersede", "executed_merge_from_conflict"}:
            written.append(info["target"])
        elif outcome == "executed_delete":
            deleted.append(info["target"])

        log_lines.append(_format_log_line(outcome, info))

        # type-enum normalization is reported separately for traceability
        for extra in info.get("_extra_log", []) or []:
            log_lines.append(extra)

    return written, deleted, log_lines, summary


def _resolve_and_execute(
    action,
    wiki_path: Path,
    *,
    job_type: str,
    source_filename: str,
) -> Tuple[str, dict]:
    """Apply a single action to disk. Returns (outcome, info). Caller handles git commit."""
    extra_logs: list[str] = []

    # ----- DeleteAction -----
    if isinstance(action, DeleteAction):
        # SC-63: forbidden in INGEST
        if job_type == "ingest":
            return ("rejected_forbidden_in_ingest",
                    {"action": "delete", "target": action.target, "reason": action.reason})
        # SC-56: reserved files protected
        if is_reserved_path(action.target):
            return ("rejected_reserved",
                    {"action": "delete", "target": action.target})
        if not wiki_store.delete_page(wiki_path, action.target):
            return ("skipped_invalid_target",
                    {"action": "delete", "target": action.target, "kind": "delete"})
        return ("executed_delete",
                {"action": "delete", "target": action.target, "reason": action.reason})

    # ----- CreateAction -----
    if isinstance(action, CreateAction):
        existing = wiki_store.read_page(wiki_path, action.page_path)
        if existing is not None:
            # SC-55: conflict → auto-downgrade to merge_into and execute (Phase B)
            new_content = action.content
            if job_type == "ingest" and source_filename:
                new_content = force_sources_frontmatter(new_content, source_filename)
            new_content, type_corrected = coerce_type_field(new_content)
            if type_corrected:
                extra_logs.append(_format_log_line(
                    "normalized_type", {"target": action.page_path}
                ))
            merged = merge_frontmatter(existing, new_content, _now_str())
            wiki_store.write_pages(wiki_path, {action.page_path: merged})
            return ("executed_merge_from_conflict",
                    {"action": "create", "target": action.page_path,
                     "_extra_log": extra_logs})

        content = action.content
        if job_type == "ingest" and source_filename:
            content = force_sources_frontmatter(content, source_filename)
        content, type_corrected = coerce_type_field(content)
        if type_corrected:
            extra_logs.append(_format_log_line("normalized_type", {"target": action.page_path}))
        wiki_store.write_pages(wiki_path, {action.page_path: content})
        return ("executed_create",
                {"action": "create", "page_path": action.page_path,
                 "_extra_log": extra_logs})

    # ----- MergeIntoAction -----
    if isinstance(action, MergeIntoAction):
        existing = wiki_store.read_page(wiki_path, action.target)
        if existing is None:
            return ("skipped_invalid_target",
                    {"action": "merge_into", "target": action.target, "kind": "merge_into"})
        new_content = action.merged_content
        if job_type == "ingest" and source_filename:
            new_content = force_sources_frontmatter(new_content, source_filename)
        new_content, type_corrected = coerce_type_field(new_content)
        if type_corrected:
            extra_logs.append(_format_log_line("normalized_type", {"target": action.target}))
        merged = merge_frontmatter(existing, new_content, _now_str())
        wiki_store.write_pages(wiki_path, {action.target: merged})
        return ("executed_merge",
                {"action": "merge_into", "target": action.target,
                 "_extra_log": extra_logs})

    # ----- SupersedeAction -----
    if isinstance(action, SupersedeAction):
        existing = wiki_store.read_page(wiki_path, action.target)
        if existing is None:
            return ("skipped_invalid_target",
                    {"action": "supersede", "target": action.target, "kind": "supersede"})
        new_content = action.new_content
        if job_type == "ingest" and source_filename:
            new_content = force_sources_frontmatter(new_content, source_filename)
        new_content, type_corrected = coerce_type_field(new_content)
        if type_corrected:
            extra_logs.append(_format_log_line("normalized_type", {"target": action.target}))
        merged = merge_frontmatter(existing, new_content, _now_str())
        wiki_store.write_pages(wiki_path, {action.target: merged})
        return ("executed_supersede",
                {"action": "supersede", "target": action.target,
                 "reason": action.reason, "_extra_log": extra_logs})

    raise ValueError(f"Unknown action type: {type(action)}")


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
    log_lines: list[str] = []
    written: list[str] = []
    deleted: list[str] = []

    if plan is not None:
        written, deleted, log_lines, plan_summary = _execute_plan(
            plan, wiki_path,
            job_type="ingest",
            source_filename=source_filename,
        )
    else:
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
        coerced_pages: dict[str, str] = {}
        for fname, content in legacy_pages.items():
            content = force_sources_frontmatter(content, source_filename)
            content, _ = coerce_type_field(content)
            coerced_pages[fname] = content
        written = wiki_store.write_pages(wiki_path, coerced_pages)
        plan_summary = [{"action": "legacy_fallback", "outcome": "executed", "info": {"pages": written}}]

    # Refresh index.md
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
        log_entry += f"- created/updated: {', '.join(f'[[{Path(p).stem}]]' for p in written)}\n"
    for line in log_lines:
        log_entry += f"{line}\n"
    log_entry = log_entry.rstrip()

    wiki_store.append_log(wiki_path, log_entry)
    commit_files.append("log.md")

    wiki_store.commit_changes(
        wiki_path, commit_files,
        f"ingest: {source_filename} → {len(written)} page(s) [job:{job_id}]",
        removed=deleted,
    )

    await _persist_plan_payload(
        db, job_id,
        {"plan_summary": plan_summary, "fallback_used": fallback_used},
    )

    logger.info(f"[INGEST] {source_filename} → written={written}, deleted={deleted}")


async def run_wiki_command(command_text: str, db: AsyncSession, job_id: str = ""):
    """SC-58: execute a natural-language wiki command via Plan."""
    settings = get_settings()
    wiki_path = Path(settings.wiki_store_path)
    wiki_store._get_repo(wiki_path)
    wiki_store.ensure_sheska_yaml(wiki_path, settings.source_base_url)

    system_prompt = _load_prompt("wiki_command")

    existing_index = wiki_store.read_page(wiki_path, "index.md")
    if not existing_index or "no pages yet" in existing_index.lower() or "*Empty" in existing_index:
        index_block = "EXISTING WIKI INDEX:\n(empty)"
    else:
        index_block = f"EXISTING WIKI INDEX:\n{existing_index.strip()}"

    user_content = f"{index_block}\n\nUSER COMMAND:\n{command_text}"

    llm_output = await call_llm(
        system_prompt,
        user_content,
        response_format={"type": "json_object"},
    )
    logger.info(f"[WIKI_COMMAND] LLM raw output ({len(llm_output)} chars): {llm_output[:500]!r}")

    plan = _try_parse_plan(llm_output)
    if plan is None:
        snippet = llm_output[:200].replace("\n", " ")
        raise ValueError(
            "WIKI_COMMAND: LLM output is not a valid JSON Plan. "
            f"Got: {snippet!r}"
        )

    written, deleted, log_lines, plan_summary = _execute_plan(
        plan, wiki_path, job_type="wiki_command",
    )

    all_pages = wiki_store.list_pages(wiki_path)
    index_content = index_updater.rebuild_index(wiki_path, all_pages)
    (wiki_path / "index.md").write_text(index_content, encoding="utf-8")

    commit_files = list(written) + ["index.md"]
    now = datetime.datetime.utcnow().isoformat() + "Z"

    log_entry = f"## {now} | WIKI_COMMAND | SUCCESS | job_id: {job_id}\n"
    if not plan.actions:
        log_entry += "- no actions: LLM produced an empty plan for the command\n"
    if written:
        log_entry += f"- updated: {', '.join(f'[[{Path(p).stem}]]' for p in written)}\n"
    if deleted:
        log_entry += f"- removed: {', '.join(f'[[{Path(p).stem}]]' for p in deleted)}\n"
    for line in log_lines:
        log_entry += f"{line}\n"
    log_entry = log_entry.rstrip()

    wiki_store.append_log(wiki_path, log_entry)
    commit_files.append("log.md")

    wiki_store.commit_changes(
        wiki_path, commit_files,
        f"wiki_command: {len(written)} updated, {len(deleted)} removed [job:{job_id}]",
        removed=deleted,
    )

    await _persist_plan_payload(
        db, job_id,
        {"plan_summary": plan_summary},
    )
    logger.info(f"[WIKI_COMMAND] written={written}, deleted={deleted}")


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
