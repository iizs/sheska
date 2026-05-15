"""v0.4 Agentic tool catalog (ADR-0014).

Each tool is a (schema, executor) pair. The agentic loop in `llm_client` dispatches
tool_use blocks emitted by the LLM to the executors and returns their JSON-serializable
results as `tool_result` blocks.

Executors take `(wiki_path: Path, args: dict, ctx: ToolContext)` and return a string
(JSON-encoded payload) — Anthropic tool_result accepts string content.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable, Optional

from . import wiki_store
from .plan import is_reserved_path, _split_frontmatter, _yaml_list


@dataclass
class ToolContext:
    job_type: str                    # "ingest" | "wiki_command"
    job_id: str
    source_filename: str = ""        # set for ingest
    written_paths: list[str] = field(default_factory=list)  # cumulative across loop
    deleted_paths: list[str] = field(default_factory=list)
    step_counter: int = 0            # incremented per write/patch/delete commit


def _now_str() -> str:
    import datetime
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _commit_step(
    ctx: ToolContext,
    wiki_path: Path,
    written: list[str],
    removed: list[str],
    tool_name: str,
    primary_path: str,
):
    """Per-write commit (SC-78). One git commit per write/patch/delete tool call."""
    ctx.step_counter += 1
    msg = f"[job:{ctx.job_id} step:{ctx.step_counter}] {tool_name}: {primary_path}"
    wiki_store.commit_changes(wiki_path, written, msg, removed=removed)


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _result_ok(**kwargs) -> str:
    return _json({"ok": True, **kwargs})


def _result_error(msg: str, **kwargs) -> str:
    return _json({"ok": False, "error": msg, **kwargs})


# ============================== Executors ==============================

async def _exec_get_index(wiki_path: Path, args: dict, ctx: ToolContext) -> str:
    content = wiki_store.read_page(wiki_path, "index.md") or ""
    return _result_ok(content=content)


async def _exec_read_page(wiki_path: Path, args: dict, ctx: ToolContext) -> str:
    path = args.get("path")
    if not isinstance(path, str) or not path:
        return _result_error("path required")
    content = wiki_store.read_page(wiki_path, path)
    if content is None:
        return _result_error("page not found", path=path)
    return _result_ok(path=path, content=content)


async def _exec_read_source(wiki_path: Path, args: dict, ctx: ToolContext) -> str:
    from ..config import get_settings
    from .pipeline import _parse_source_text
    filename = args.get("filename")
    if not isinstance(filename, str) or not filename:
        return _result_error("filename required")
    src_dir = Path(get_settings().source_store_path)
    src_path = src_dir / filename
    if not src_path.exists():
        return _result_error("source not found", filename=filename)
    try:
        text = _parse_source_text(str(src_path))
    except Exception as e:
        return _result_error(f"source parse failed: {e}")
    return _result_ok(filename=filename, text=text)


async def _exec_search_pages(wiki_path: Path, args: dict, ctx: ToolContext) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query:
        return _result_error("query required")
    max_items = int(args.get("max_items", 20))
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    matches: list[dict] = []
    truncated = False
    for page in wiki_store.list_pages(wiki_path):
        content = wiki_store.read_page(wiki_path, page) or ""
        snippets: list[dict] = []
        for i, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
                snippets.append({"line": i, "text": line.strip()[:200]})
                if len(snippets) >= 3:
                    break
        if snippets:
            if len(matches) >= max_items:
                truncated = True
                break
            matches.append({"path": page, "snippets": snippets})
    return _result_ok(query=query, matches=matches, truncated=truncated)


_VALID_TYPES = {"concept", "process", "policy", "reference", "glossary"}


def _validate_writable_path(path: Any) -> Optional[str]:
    """Return None if path is OK, or an error string."""
    if not isinstance(path, str) or not path:
        return "path required"
    if path.startswith("/") or ".." in path.split("/"):
        return f"path traversal not allowed: {path!r}"
    if not path.endswith(".md"):
        return f"path must end with .md: {path!r}"
    if is_reserved_path(path):
        return f"reserved file cannot be modified by LLM: {path}"
    return None


async def _exec_write_page(wiki_path: Path, args: dict, ctx: ToolContext) -> str:
    path = args.get("path")
    content = args.get("content")
    err = _validate_writable_path(path)
    if err:
        return _result_error(err)
    if not isinstance(content, str) or not content:
        return _result_error("content required")

    from .plan import coerce_type_field, force_sources_frontmatter
    new_content = content
    if ctx.job_type == "ingest" and ctx.source_filename:
        new_content = force_sources_frontmatter(new_content, ctx.source_filename)
    new_content, type_corrected = coerce_type_field(new_content)
    now = _now_str()
    new_content = wiki_store.update_last_updated(new_content, now)

    old = wiki_store.read_page(wiki_path, path)
    # SC-67 follow-up: enforce `created` — LLM tends to hallucinate the value.
    # New page → created = now. Overwrite of existing → preserve original created.
    if old is None:
        new_content = wiki_store.force_created(new_content, now)
    else:
        existing_created = wiki_store.read_created(old)
        if existing_created:
            new_content = wiki_store.force_created(new_content, existing_created)
    (wiki_path / path).parent.mkdir(parents=True, exist_ok=True)
    (wiki_path / path).write_text(new_content, encoding="utf-8")
    backlinks_changed = wiki_store.update_backlinks_for_change(
        wiki_path, path, old, new_content
    )
    if path not in ctx.written_paths:
        ctx.written_paths.append(path)
    for bl in backlinks_changed:
        if bl not in ctx.written_paths:
            ctx.written_paths.append(bl)

    # SC-78: one commit per write tool call
    step_files = [path] + list(backlinks_changed)
    _commit_step(ctx, wiki_path, step_files, [], "write_page", path)

    return _result_ok(
        path=path,
        existed=old is not None,
        type_corrected=type_corrected,
        backlinks_updated=backlinks_changed,
    )


async def _exec_patch_page(wiki_path: Path, args: dict, ctx: ToolContext) -> str:
    path = args.get("path")
    diff_text = args.get("diff")
    err = _validate_writable_path(path)
    if err:
        return _result_error(err)
    if not isinstance(diff_text, str) or not diff_text.strip():
        return _result_error("diff required (unified diff format)")
    old = wiki_store.read_page(wiki_path, path)
    if old is None:
        return _result_error(
            f"page not found — use write_page for new pages: {path}"
        )
    result = wiki_store.apply_unified_diff(old, diff_text)
    if result["error"]:
        return _result_error(result["error"], hunks_failed=result["hunks_failed"])
    if result["hunks_applied"] == 0:
        # 0 applied — no commit, return diagnostic
        return _json({
            "ok": False,
            "applied": False,
            "hunks_applied": 0,
            "hunks_failed": result["hunks_failed"],
            "error": "no hunks applied",
        })
    new_content = result["new_content"]
    from .plan import coerce_type_field
    new_content, type_corrected = coerce_type_field(new_content)
    new_content = wiki_store.update_last_updated(new_content, _now_str())
    (wiki_path / path).write_text(new_content, encoding="utf-8")
    backlinks_changed = wiki_store.update_backlinks_for_change(
        wiki_path, path, old, new_content
    )
    if path not in ctx.written_paths:
        ctx.written_paths.append(path)
    for bl in backlinks_changed:
        if bl not in ctx.written_paths:
            ctx.written_paths.append(bl)

    # SC-78: one commit per patch tool call
    step_files = [path] + list(backlinks_changed)
    _commit_step(ctx, wiki_path, step_files, [], "patch_page", path)

    return _result_ok(
        path=path,
        hunks_applied=result["hunks_applied"],
        hunks_failed=result["hunks_failed"],
        type_corrected=type_corrected,
        backlinks_updated=backlinks_changed,
    )


async def _exec_delete_page(wiki_path: Path, args: dict, ctx: ToolContext) -> str:
    path = args.get("path")
    reason = args.get("reason", "")
    err = _validate_writable_path(path)
    if err:
        return _result_error(err)
    if ctx.job_type == "ingest":
        return _result_error(
            f"delete is forbidden in INGEST (accumulation principle): {path}"
        )
    old = wiki_store.read_page(wiki_path, path)
    if old is None:
        return _result_error(f"page not found: {path}")
    wiki_store.delete_page(wiki_path, path)
    backlinks_changed = wiki_store.update_backlinks_for_change(
        wiki_path, path, old, None
    )
    if path not in ctx.deleted_paths:
        ctx.deleted_paths.append(path)
    for bl in backlinks_changed:
        if bl not in ctx.written_paths:
            ctx.written_paths.append(bl)

    # SC-78: one commit per delete tool call
    _commit_step(ctx, wiki_path, list(backlinks_changed), [path], "delete_page", path)

    return _result_ok(path=path, reason=reason, backlinks_updated=backlinks_changed)


async def _exec_get_backlinks(wiki_path: Path, args: dict, ctx: ToolContext) -> str:
    page = args.get("page")
    if not isinstance(page, str) or not page:
        return _result_error("page required")
    if not page.endswith(".md"):
        page = page + ".md"
    content = wiki_store.read_page(wiki_path, page)
    if content is None:
        return _result_error(f"page not found: {page}")
    _, yaml_block, _ = _split_frontmatter(content)
    backlinks = _yaml_list(yaml_block, "backlinks") if yaml_block else []
    return _result_ok(page=page, backlinks=backlinks)


# ============================== Schemas (Anthropic tool format) ==============================

_TOOL_SCHEMAS = {
    "get_index": {
        "name": "get_index",
        "description": "Return the wiki index (titles + summaries). Call this first to understand what pages exist before deciding to create or edit.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "read_page": {
        "name": "read_page",
        "description": "Read the full content of a wiki page (frontmatter + body). Returns ok:false if the page does not exist.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "kebab-case filename ending with .md"}},
            "required": ["path"],
        },
    },
    "read_source": {
        "name": "read_source",
        "description": "Read the original source document (PDF/TXT/MD) by filename. Used in INGEST flow.",
        "input_schema": {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
    },
    "search_pages": {
        "name": "search_pages",
        "description": "Substring search across all wiki pages (case-insensitive). Returns matching pages + line snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_items": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    "write_page": {
        "name": "write_page",
        "description": "Create a new page or fully overwrite an existing one. Provide complete markdown including YAML frontmatter. For partial edits prefer patch_page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    "patch_page": {
        "name": "patch_page",
        "description": "Apply a unified diff to an existing page. Use this for partial edits. Line numbers in @@ headers are ignored; context lines are matched fuzzily. Returns hunks_applied + hunks_failed; the page is only written when hunks_applied > 0.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "diff": {"type": "string", "description": "Standard unified diff. ~5 lines of context per hunk recommended."},
            },
            "required": ["path", "diff"],
        },
    },
    "delete_page": {
        "name": "delete_page",
        "description": "Delete a wiki page. Forbidden in INGEST context (accumulation principle). Reserved files cannot be deleted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["path", "reason"],
        },
    },
    "get_backlinks": {
        "name": "get_backlinks",
        "description": "Return the list of pages that link to the given page (from frontmatter backlinks index).",
        "input_schema": {
            "type": "object",
            "properties": {"page": {"type": "string"}},
            "required": ["page"],
        },
    },
}


_EXECUTORS: dict[str, Callable[[Path, dict, ToolContext], Awaitable[str]]] = {
    "get_index": _exec_get_index,
    "read_page": _exec_read_page,
    "read_source": _exec_read_source,
    "search_pages": _exec_search_pages,
    "write_page": _exec_write_page,
    "patch_page": _exec_patch_page,
    "delete_page": _exec_delete_page,
    "get_backlinks": _exec_get_backlinks,
}


def list_schemas() -> list[dict]:
    return list(_TOOL_SCHEMAS.values())


def get_executor(name: str) -> Optional[Callable[[Path, dict, ToolContext], Awaitable[str]]]:
    return _EXECUTORS.get(name)
