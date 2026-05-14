from __future__ import annotations
import re
import datetime
from pathlib import Path
import git
from ..config import get_settings


def _get_repo(wiki_path: Path) -> git.Repo:
    if not (wiki_path / ".git").exists():
        repo = git.Repo.init(wiki_path)
        # Initial commit needed for proper git operation
        if not (wiki_path / "index.md").exists():
            (wiki_path / "index.md").write_text("# Wiki Index\n\n*Empty — no pages yet.*\n")
        if not (wiki_path / "log.md").exists():
            (wiki_path / "log.md").write_text("# Sheska Operation Log\n")
        repo.index.add(["index.md", "log.md"])
        repo.index.commit("Initial wiki setup")
        return repo
    return git.Repo(wiki_path)


def _slugify(text: str, default: str = "page") -> str:
    """Filename-safe kebab-case slug. Preserves unicode word chars (한글 포함)."""
    slug = re.sub(r"[^\w-]+", "-", text, flags=re.UNICODE).strip("-").lower()
    return slug or default


def _auto_frontmatter(source_filename: str) -> str:
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return (
        "---\n"
        "type: reference\n"
        f"created: {now}\n"
        f"last_updated: {now}\n"
        "tags: []\n"
        "sources:\n"
        f'  - "{source_filename}"\n'
        "---\n"
    )


def parse_llm_pages(
    llm_output: str,
    fallback_stem: str = "page",
    source_filename: str = "",
) -> dict[str, str]:
    """Parse LLM output into wiki pages.

    Strategy (most specific → most lenient):
      1. '=== FILE: <name>.md ===' markers (multiple pages supported)
      2. valid '---\\n<yaml>\\n---\\n<body>' frontmatter (single page)
      3. dangling '---' opener with content but no proper yaml → strip + auto-frontmatter
      4. no '---' but has '#' heading → use as body + auto-frontmatter; title from first heading
      5. otherwise (pure commentary, no heading) → empty dict (caller raises)
    """
    pages: dict[str, str] = {}

    pattern = re.compile(r"=== FILE: (.+?\.md) ===\n(.*?)(?==== FILE:|$)", re.DOTALL)
    for match in pattern.finditer(llm_output):
        filename = match.group(1).strip()
        content = match.group(2).strip()
        pages[filename] = content
    if pages:
        return pages

    stripped = llm_output.strip()
    if not stripped:
        return {}

    # Reject pure commentary — must have at least one '#' heading anywhere
    if not re.search(r"^#+\s+\S", stripped, re.MULTILINE):
        return {}

    src = source_filename or fallback_stem

    fm_match = re.match(r"^---\n(.*?)\n---\n?(.*)$", stripped, re.DOTALL)
    if fm_match and fm_match.group(1).strip():
        # Case 2: valid frontmatter present → keep as-is
        body = fm_match.group(2).lstrip("\n")
        final = stripped
    else:
        # Case 3/4: leading '---' but no yaml, or no '---' at all → strip dangling opener
        body = re.sub(r"^---\s*\n", "", stripped, count=1)
        final = _auto_frontmatter(src) + body.strip() + "\n"

    title_match = re.search(r"^#+\s+(.+?)\s*$", body, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else fallback_stem
    page_stem = _slugify(title, default=_slugify(fallback_stem))

    pages[f"{page_stem}.md"] = final
    return pages


def write_pages(wiki_path: Path, pages: dict[str, str]) -> list[str]:
    """Write pages to wiki store. Returns list of written filenames."""
    written = []
    for filename, content in pages.items():
        filepath = wiki_path / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        written.append(filename)
    return written


def read_page(wiki_path: Path, page_path: str) -> str | None:
    filepath = wiki_path / page_path
    if not filepath.exists():
        return None
    return filepath.read_text(encoding="utf-8")


def list_pages(wiki_path: Path) -> list[str]:
    reserved = {"index.md", "log.md", "_sheska.yaml"}
    pages = []
    for p in wiki_path.rglob("*.md"):
        rel = p.relative_to(wiki_path).as_posix()
        if rel not in reserved and not rel.startswith("_"):
            pages.append(rel)
    return sorted(pages)


def append_log(wiki_path: Path, entry: str):
    log_path = wiki_path / "log.md"
    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else "# Sheska Operation Log\n"
    lines = existing.split("\n", 1)
    header = lines[0]
    rest = lines[1] if len(lines) > 1 else ""
    new_content = f"{header}\n\n{entry}\n{rest}"
    log_path.write_text(new_content, encoding="utf-8")


def commit_changes(wiki_path: Path, files: list[str], message: str, removed: list[str] | None = None):
    repo = _get_repo(wiki_path)
    for f in files:
        rel = str(Path(f).as_posix())
        repo.index.add([rel])
    if removed:
        for f in removed:
            rel = str(Path(f).as_posix())
            try:
                repo.index.remove([rel], working_tree=True)
            except Exception:
                # Already gone from working tree — best effort
                pass
    repo.index.commit(message)


def delete_page(wiki_path: Path, page_path: str) -> bool:
    """Remove a wiki file from the working tree. Returns True if removed, False if missing."""
    target = wiki_path / page_path
    if not target.exists():
        return False
    target.unlink()
    return True


def ensure_sheska_yaml(wiki_path: Path, source_base_url: str):
    yaml_path = wiki_path / "_sheska.yaml"
    if not yaml_path.exists():
        yaml_path.write_text(f"source_base_url: \"{source_base_url}\"\n", encoding="utf-8")
        repo = _get_repo(wiki_path)
        repo.index.add(["_sheska.yaml"])
        repo.index.commit("Add _sheska.yaml")


# =========================================================================
# v0.4 — Backlink index + patch_page (unified diff)
# =========================================================================

_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")


def extract_wikilinks(content: str) -> set[str]:
    """Outgoing wikilinks from page body. Returns set of stems (no .md)."""
    body = content
    # strip frontmatter if present
    fm = re.match(r"^---\n.*?\n---\n?", content, flags=re.DOTALL)
    if fm:
        body = content[fm.end():]
    return {m.group(1).split("|", 1)[0].strip() for m in _WIKILINK_RE.finditer(body)}


def _stem(page_path: str) -> str:
    return Path(page_path).stem


def _read_backlinks(yaml_block: str) -> list[str]:
    from .plan import _yaml_list
    return _yaml_list(yaml_block, "backlinks")


def _write_backlinks(content: str, backlinks: list[str]) -> str:
    """Set the backlinks list in the frontmatter. Adds the frontmatter block if missing."""
    from .plan import _split_frontmatter, _set_yaml_list
    open_block, yaml_block, rest = _split_frontmatter(content)
    if not open_block:
        new_yaml = _set_yaml_list("type: reference", "backlinks", backlinks)
        return f"---\n{new_yaml}\n---\n{content}"
    new_yaml = _set_yaml_list(yaml_block, "backlinks", backlinks)
    return open_block + new_yaml + rest


def _update_one_page_backlinks(wiki_path: Path, target_stem: str, add_stems: set[str], remove_stems: set[str]) -> bool:
    """Apply add/remove to the backlinks of `<target_stem>.md`. Returns True if file changed."""
    target_path = f"{target_stem}.md"
    content = read_page(wiki_path, target_path)
    if content is None:
        return False
    from .plan import _split_frontmatter
    _, yaml_block, _ = _split_frontmatter(content)
    existing = _read_backlinks(yaml_block) if yaml_block else []
    new = [b for b in existing if b not in remove_stems]
    for s in add_stems:
        if s not in new:
            new.append(s)
    if new == existing:
        return False
    new_content = _write_backlinks(content, new)
    (wiki_path / target_path).write_text(new_content, encoding="utf-8")
    return True


def update_backlinks_for_change(
    wiki_path: Path,
    changed_page: str,
    old_content: str | None,
    new_content: str | None,
) -> list[str]:
    """Update backlinks for every page whose set of incoming links changed.

    Args:
      changed_page: filename (e.g. "auth.md") that was written or deleted.
      old_content: previous content of the changed page, or None if it didn't exist.
      new_content: new content of the changed page, or None if it was deleted.

    Returns the list of *other* page filenames that were modified.
    """
    changed_stem = _stem(changed_page)
    old_links = extract_wikilinks(old_content) if old_content else set()
    new_links = extract_wikilinks(new_content) if new_content else set()

    added = new_links - old_links
    removed = old_links - new_links

    modified: list[str] = []
    for stem in sorted(added):
        if _update_one_page_backlinks(wiki_path, stem, {changed_stem}, set()):
            modified.append(f"{stem}.md")
    for stem in sorted(removed):
        if _update_one_page_backlinks(wiki_path, stem, set(), {changed_stem}):
            modified.append(f"{stem}.md")
    return modified


def update_last_updated(content: str, now_str: str) -> str:
    """Refresh `last_updated:` in frontmatter (insert minimal frontmatter if absent)."""
    from .plan import _split_frontmatter, _set_yaml_scalar
    open_block, yaml_block, rest = _split_frontmatter(content)
    if not open_block:
        return f"---\ntype: reference\nlast_updated: {now_str}\n---\n{content}"
    new_yaml = _set_yaml_scalar(yaml_block, "last_updated", now_str)
    return open_block + new_yaml + rest


# ---- Unified diff patch ----

def apply_unified_diff(content: str, diff_text: str) -> dict:
    """Apply a unified diff with context-fuzzy matching (line numbers ignored).

    Returns:
      {
        "new_content": str | None,
        "hunks_applied": int,
        "hunks_failed": [{"idx": int, "reason": str, "context_excerpt": str}],
        "error": str | None,
      }
    """
    hunks = _split_unified_diff(diff_text)
    if not hunks:
        return {"new_content": None, "hunks_applied": 0, "hunks_failed": [],
                "error": "no hunks parsed from diff"}

    lines = content.splitlines(keepends=False)
    applied = 0
    failed: list[dict] = []
    for idx, hunk in enumerate(hunks):
        result = _apply_one_hunk(lines, hunk)
        if result["ok"]:
            lines = result["lines"]
            applied += 1
        else:
            failed.append({"idx": idx, "reason": result["reason"],
                           "context_excerpt": "\n".join(hunk["lines"][:6])})
    if applied == 0:
        return {"new_content": None, "hunks_applied": 0, "hunks_failed": failed, "error": None}
    new_content = "\n".join(lines)
    if content.endswith("\n") and not new_content.endswith("\n"):
        new_content += "\n"
    return {"new_content": new_content, "hunks_applied": applied,
            "hunks_failed": failed, "error": None}


def _split_unified_diff(diff_text: str) -> list[dict]:
    """Return list of hunks. Each hunk: {"lines": [str], }. Ignores @@ markers' line numbers."""
    hunks: list[dict] = []
    current: list[str] | None = None
    for line in diff_text.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            if current is not None:
                hunks.append({"lines": current})
            current = []
            continue
        if current is None:
            # No @@ seen yet — start a synthetic hunk
            current = []
        # Treat all non-marker lines as content (skip diff header noise)
        if line and line[0] in " +-\\":
            if line.startswith("\\"):
                continue  # "\ No newline at end of file"
            current.append(line)
    if current:
        hunks.append({"lines": current})
    return hunks


def _apply_one_hunk(lines: list[str], hunk: dict) -> dict:
    """Context-fuzzy match a single hunk against `lines`. Returns {ok, lines, reason}."""
    hunk_lines = hunk["lines"]
    # Extract "before" (context + removed) and "after" (context + added)
    before: list[str] = []
    after: list[str] = []
    for h in hunk_lines:
        if not h:
            before.append("")
            after.append("")
            continue
        marker, body = h[0], h[1:]
        if marker == " ":
            before.append(body)
            after.append(body)
        elif marker == "-":
            before.append(body)
        elif marker == "+":
            after.append(body)
        else:
            # malformed line — best-effort treat as context
            before.append(h)
            after.append(h)

    if not before:
        # Pure insertion hunk — append at end (rare but possible)
        return {"ok": True, "lines": lines + after, "reason": ""}

    # Search for the "before" block in `lines`
    n = len(lines)
    bl = len(before)
    for start in range(n - bl + 1):
        if lines[start:start + bl] == before:
            return {"ok": True,
                    "lines": lines[:start] + after + lines[start + bl:],
                    "reason": ""}

    # Fuzzy: try with leading/trailing whitespace stripped
    norm_before = [x.strip() for x in before]
    for start in range(n - bl + 1):
        if [x.strip() for x in lines[start:start + bl]] == norm_before:
            return {"ok": True,
                    "lines": lines[:start] + after + lines[start + bl:],
                    "reason": ""}

    return {"ok": False, "lines": lines, "reason": "context not found in target"}
