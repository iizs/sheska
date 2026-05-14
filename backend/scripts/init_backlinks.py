"""Backlink index migration (ADR-0015).

Scans every wiki page once, extracts `[[outgoing-link]]` references from each body,
and writes the inverse index into each page's `backlinks:` frontmatter field.

Idempotent: pages whose backlinks are already correct are left untouched.

Usage:
    python scripts/init_backlinks.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings, resolve_path  # noqa: E402
from app.services import wiki_store  # noqa: E402
from app.services.plan import _split_frontmatter, _set_yaml_list, _yaml_list  # noqa: E402


def main() -> int:
    settings = get_settings()
    wiki_path = resolve_path(settings.wiki_store_path)
    if not wiki_path.exists():
        print(f"wiki_store path does not exist: {wiki_path}")
        return 1

    repo = wiki_store._get_repo(wiki_path)

    pages = wiki_store.list_pages(wiki_path)
    if not pages:
        print("No pages found — nothing to migrate.")
        return 0

    # Build the inverse index: target_stem -> {source_stem, ...}
    inverse: dict[str, set[str]] = {}
    for page in pages:
        content = wiki_store.read_page(wiki_path, page) or ""
        for outgoing_stem in wiki_store.extract_wikilinks(content):
            inverse.setdefault(outgoing_stem, set()).add(Path(page).stem)

    changed_files: list[str] = []
    for page in pages:
        stem = Path(page).stem
        content = wiki_store.read_page(wiki_path, page) or ""
        _, yaml_block, _ = _split_frontmatter(content)
        existing = _yaml_list(yaml_block, "backlinks") if yaml_block else []
        desired = sorted(inverse.get(stem, set()))
        if existing == desired:
            continue
        new_content = wiki_store._write_backlinks(content, desired)
        (wiki_path / page).write_text(new_content, encoding="utf-8")
        changed_files.append(page)

    if not changed_files:
        print(f"Backlinks already up to date for {len(pages)} pages.")
        return 0

    for f in changed_files:
        repo.index.add([str(Path(f).as_posix())])
    repo.index.commit(f"chore: rebuild backlinks index ({len(changed_files)} pages)")
    print(f"Backlinks rebuilt: {len(changed_files)} pages updated, committed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
