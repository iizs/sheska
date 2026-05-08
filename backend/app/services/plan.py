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


PlanAction = Union[CreateAction, MergeIntoAction, SupersedeAction]


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
