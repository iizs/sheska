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


def parse_llm_pages(llm_output: str) -> dict[str, str]:
    """Parse LLM output formatted as === FILE: name.md === sections."""
    pages: dict[str, str] = {}
    pattern = re.compile(r"=== FILE: (.+?\.md) ===\n(.*?)(?==== FILE:|$)", re.DOTALL)
    for match in pattern.finditer(llm_output):
        filename = match.group(1).strip()
        content = match.group(2).strip()
        pages[filename] = content
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


def commit_changes(wiki_path: Path, files: list[str], message: str):
    repo = _get_repo(wiki_path)
    for f in files:
        rel = str(Path(f).as_posix())
        repo.index.add([rel])
    repo.index.commit(message)


def ensure_sheska_yaml(wiki_path: Path, source_base_url: str):
    yaml_path = wiki_path / "_sheska.yaml"
    if not yaml_path.exists():
        yaml_path.write_text(f"source_base_url: \"{source_base_url}\"\n", encoding="utf-8")
        repo = _get_repo(wiki_path)
        repo.index.add(["_sheska.yaml"])
        repo.index.commit("Add _sheska.yaml")
