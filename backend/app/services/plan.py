"""Pydantic models for the LLM Ingest Plan (ADR-0011, Phase A)."""
from __future__ import annotations
import re
from typing import List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator


VALID_FRONTMATTER_TYPES = {"concept", "process", "policy", "reference", "glossary"}

_PAGE_PATH_RE = re.compile(r"^[\w\-./]+\.md$", flags=re.UNICODE)


def _validate_page_path(value: str) -> str:
    """Reject path-traversal and non-.md filenames."""
    if not value or not isinstance(value, str):
        raise ValueError("page_path must be a non-empty string")
    if value.startswith("/") or ".." in value.split("/"):
        raise ValueError(f"page_path traversal not allowed: {value!r}")
    if not _PAGE_PATH_RE.match(value):
        raise ValueError(f"page_path must be relative kebab-style ending with .md: {value!r}")
    return value


class CreateAction(BaseModel):
    action: Literal["create"]
    page_path: str
    content: str

    @field_validator("page_path")
    @classmethod
    def _check_path(cls, v: str) -> str:
        return _validate_page_path(v)


class MergeIntoAction(BaseModel):
    action: Literal["merge_into"]
    target: str
    merged_content: str

    @field_validator("target")
    @classmethod
    def _check_target(cls, v: str) -> str:
        return _validate_page_path(v)


class SupersedeAction(BaseModel):
    action: Literal["supersede"]
    target: str
    reason: Optional[str] = None
    new_content: str

    @field_validator("target")
    @classmethod
    def _check_target(cls, v: str) -> str:
        return _validate_page_path(v)


class DeleteAction(BaseModel):
    """Page deletion. Allowed only in WIKI_COMMAND jobs (SC-54/63)."""

    action: Literal["delete"]
    target: str
    reason: Optional[str] = None

    @field_validator("target")
    @classmethod
    def _check_target(cls, v: str) -> str:
        return _validate_page_path(v)


PlanAction = Union[CreateAction, MergeIntoAction, SupersedeAction, DeleteAction]


RESERVED_FILES = {"index.md", "log.md", "_sheska.yaml"}


def is_reserved_path(page_path: str) -> bool:
    """Files protected from delete (SC-56). `_`-prefixed and well-known reserved files."""
    if page_path in RESERVED_FILES:
        return True
    name = page_path.rsplit("/", 1)[-1]
    return name.startswith("_")


class Plan(BaseModel):
    """Top-level wrapper. LLM may emit either a bare list or {"actions": [...]}."""

    actions: List[PlanAction] = Field(default_factory=list)


def coerce_type_field(content: str) -> tuple[str, bool]:
    """Inspect frontmatter `type:` and rewrite to `reference` if it violates the enum.

    Returns (possibly-rewritten content, was_corrected flag).
    """
    fm_match = re.match(r"^(---\n)(.*?)(\n---)", content, flags=re.DOTALL)
    if not fm_match:
        return content, False
    yaml_block = fm_match.group(2)
    type_match = re.search(r"^type:\s*([^\n#]+?)\s*$", yaml_block, flags=re.MULTILINE)
    if not type_match:
        return content, False
    raw_value = type_match.group(1).strip().strip("\"'").lower()
    if raw_value in VALID_FRONTMATTER_TYPES:
        return content, False
    new_yaml = re.sub(
        r"^type:\s*[^\n#]+\s*$",
        "type: reference",
        yaml_block,
        count=1,
        flags=re.MULTILINE,
    )
    new_content = fm_match.group(1) + new_yaml + fm_match.group(3) + content[fm_match.end():]
    return new_content, True


def _split_frontmatter(content: str) -> tuple[str, str, str]:
    """Return (open_block, yaml_block, rest_with_close). If no frontmatter, return ('', '', content)."""
    fm_match = re.match(r"^(---\n)(.*?)(\n---\n?)(.*)$", content, flags=re.DOTALL)
    if not fm_match:
        return "", "", content
    return fm_match.group(1), fm_match.group(2), fm_match.group(3) + fm_match.group(4)


def _yaml_field(yaml_block: str, key: str) -> Optional[str]:
    m = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", yaml_block, flags=re.MULTILINE)
    return m.group(1).strip() if m else None


def _yaml_list(yaml_block: str, key: str) -> List[str]:
    """Parse a YAML block-style list under <key>: returning string items."""
    items: List[str] = []
    pattern = re.compile(
        rf"^{re.escape(key)}:\s*\n((?:[ \t]+-\s+.+\n?)+)",
        flags=re.MULTILINE,
    )
    m = pattern.search(yaml_block)
    if m:
        for line in m.group(1).splitlines():
            stripped = line.strip()
            if stripped.startswith("-"):
                items.append(stripped[1:].strip().strip('"').strip("'"))
        return items
    # Inline form: key: [a, b, c]
    inline = re.search(
        rf"^{re.escape(key)}:\s*\[(.*?)\]\s*$",
        yaml_block,
        flags=re.MULTILINE,
    )
    if inline:
        for item in inline.group(1).split(","):
            item = item.strip().strip('"').strip("'")
            if item:
                items.append(item)
    return items


def _set_yaml_scalar(yaml_block: str, key: str, value: str) -> str:
    """Replace a scalar field's value (or insert if absent)."""
    pattern = re.compile(rf"^{re.escape(key)}:\s*.*$", flags=re.MULTILINE)
    if pattern.search(yaml_block):
        return pattern.sub(f"{key}: {value}", yaml_block, count=1)
    return yaml_block.rstrip() + f"\n{key}: {value}\n"


def _set_yaml_list(yaml_block: str, key: str, items: List[str]) -> str:
    """Replace a list field with the given items as block-style list (or insert)."""
    block_pattern = re.compile(
        rf"^{re.escape(key)}:\s*\n(?:[ \t]+-\s+.+\n?)+", flags=re.MULTILINE
    )
    inline_pattern = re.compile(rf"^{re.escape(key)}:\s*\[.*?\]\s*$", flags=re.MULTILINE)
    if items:
        rendered = f"{key}:\n" + "".join(f'  - "{x}"\n' for x in items)
    else:
        rendered = f"{key}: []\n"
    if block_pattern.search(yaml_block):
        return block_pattern.sub(rendered.rstrip("\n"), yaml_block, count=1)
    if inline_pattern.search(yaml_block):
        return inline_pattern.sub(rendered.rstrip("\n"), yaml_block, count=1)
    return yaml_block.rstrip() + "\n" + rendered.rstrip("\n")


def merge_frontmatter(existing_content: str, new_content: str, now_str: str) -> str:
    """Combine an existing page's frontmatter with the LLM-proposed new content (SC-52).

    Policy:
      - created: existing preserved
      - last_updated: replaced with `now_str`
      - tags: union (set), order: existing first, then new-only
      - sources: union (set), order: existing first, then new-only
      - type: existing preserved (SC-12 enum stability)
      - body: from new_content
    """
    _, ex_yaml, _ = _split_frontmatter(existing_content)
    new_open, new_yaml, new_body_block = _split_frontmatter(new_content)
    if not new_open:
        # New content has no frontmatter; reuse existing yaml + new body
        return existing_content.split("\n---\n", 1)[0] + "\n---\n" + new_content.lstrip()

    merged_yaml = new_yaml

    if ex_yaml:
        ex_created = _yaml_field(ex_yaml, "created")
        ex_type = _yaml_field(ex_yaml, "type")
        ex_tags = _yaml_list(ex_yaml, "tags")
        ex_sources = _yaml_list(ex_yaml, "sources")

        if ex_created:
            merged_yaml = _set_yaml_scalar(merged_yaml, "created", ex_created)
        if ex_type:
            merged_yaml = _set_yaml_scalar(merged_yaml, "type", ex_type)

        new_tags = _yaml_list(merged_yaml, "tags")
        union_tags: List[str] = list(ex_tags)
        for t in new_tags:
            if t not in union_tags:
                union_tags.append(t)
        merged_yaml = _set_yaml_list(merged_yaml, "tags", union_tags)

        new_sources = _yaml_list(merged_yaml, "sources")
        union_sources: List[str] = list(ex_sources)
        for s in new_sources:
            if s not in union_sources:
                union_sources.append(s)
        merged_yaml = _set_yaml_list(merged_yaml, "sources", union_sources)

    merged_yaml = _set_yaml_scalar(merged_yaml, "last_updated", now_str)

    return new_open + merged_yaml + new_body_block


def force_sources_frontmatter(content: str, source_filename: str) -> str:
    """Ensure frontmatter `sources:` includes `source_filename` (SC-14 guarantee)."""
    if not source_filename:
        return content
    fm_match = re.match(r"^(---\n)(.*?)(\n---\n?)", content, flags=re.DOTALL)
    if not fm_match:
        # Prepend a minimal frontmatter block
        return (
            "---\n"
            "type: reference\n"
            f"sources:\n  - \"{source_filename}\"\n"
            "---\n"
            + content
        )
    yaml_block = fm_match.group(2)
    if re.search(r"^sources:", yaml_block, flags=re.MULTILINE):
        # If the listed sources don't mention our filename, append it
        if source_filename in yaml_block:
            return content
        new_yaml = re.sub(
            r"^sources:\s*$",
            f"sources:\n  - \"{source_filename}\"",
            yaml_block,
            count=1,
            flags=re.MULTILINE,
        )
        if new_yaml == yaml_block:
            # sources: was non-empty list — append item
            new_yaml = re.sub(
                r"^(sources:\n(?:\s+-\s+.*\n)+)",
                lambda m: m.group(1) + f"  - \"{source_filename}\"\n",
                yaml_block,
                count=1,
                flags=re.MULTILINE,
            )
        rest = content[fm_match.end():]
        return fm_match.group(1) + new_yaml + fm_match.group(3) + rest
    # No sources field at all — inject one
    new_yaml = yaml_block.rstrip() + f"\nsources:\n  - \"{source_filename}\""
    rest = content[fm_match.end():]
    return fm_match.group(1) + new_yaml + fm_match.group(3) + rest
