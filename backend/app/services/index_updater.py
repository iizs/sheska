from __future__ import annotations
import datetime
import re
from pathlib import Path


def _extract_summary(content: str) -> str:
    lines = content.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("---") and not stripped.startswith("-"):
            return stripped[:80]
    return ""


def _extract_type(content: str) -> str:
    m = re.search(r"^type:\s*(\S+)", content, re.MULTILINE)
    return m.group(1) if m else "concept"


def _extract_last_updated(content: str) -> str:
    m = re.search(r"^last_updated:\s*(.+)", content, re.MULTILINE)
    return m.group(1).strip() if m else ""


def rebuild_index(wiki_path: Path, page_paths: list[str]) -> str:
    """Rebuild index.md from current wiki pages."""
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for page in sorted(page_paths):
        filepath = wiki_path / page
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding="utf-8")
        page_type = _extract_type(content)
        summary = _extract_summary(content)
        last_updated = _extract_last_updated(content)
        stem = Path(page).stem
        rows.append(f"| [[{stem}]] | {page_type} | {summary} | {last_updated} |")

    header = f"# Wiki Index\n*Last updated: {now}*\n\n| 페이지 | 타입 | 한줄 요약 | 최종 수정 |\n|--------|------|-----------|-----------|"
    return header + "\n" + "\n".join(rows) + "\n"
