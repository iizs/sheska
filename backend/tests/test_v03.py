from __future__ import annotations
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch


# ---------- Plan parser unit tests ----------

def test_plan_parses_valid_create_action():
    from app.services.plan import Plan
    data = {
        "actions": [
            {"action": "create", "page_path": "intro.md", "content": "---\ntype: concept\n---\n# Intro"}
        ]
    }
    plan = Plan.model_validate(data)
    assert len(plan.actions) == 1
    assert plan.actions[0].action == "create"


def test_plan_rejects_path_traversal():
    from app.services.plan import Plan
    from pydantic import ValidationError
    bad = {"actions": [{"action": "create", "page_path": "../etc/passwd.md", "content": "x"}]}
    with pytest.raises(ValidationError):
        Plan.model_validate(bad)


def test_plan_rejects_absolute_path():
    from app.services.plan import Plan
    from pydantic import ValidationError
    bad = {"actions": [{"action": "create", "page_path": "/abs/path.md", "content": "x"}]}
    with pytest.raises(ValidationError):
        Plan.model_validate(bad)


def test_plan_rejects_non_md_extension():
    from app.services.plan import Plan
    from pydantic import ValidationError
    bad = {"actions": [{"action": "create", "page_path": "file.txt", "content": "x"}]}
    with pytest.raises(ValidationError):
        Plan.model_validate(bad)


def test_plan_accepts_merge_into_and_supersede():
    from app.services.plan import Plan
    data = {"actions": [
        {"action": "merge_into", "target": "x.md", "merged_content": "..."},
        {"action": "supersede", "target": "y.md", "reason": "obsolete", "new_content": "..."},
    ]}
    plan = Plan.model_validate(data)
    assert plan.actions[0].action == "merge_into"
    assert plan.actions[1].action == "supersede"


# SC-51
def test_coerce_type_field_corrects_invalid_enum():
    from app.services.plan import coerce_type_field
    content = "---\ntype: invalid\nfoo: bar\n---\nbody"
    new, corrected = coerce_type_field(content)
    assert corrected is True
    assert "type: reference" in new
    assert "type: invalid" not in new


def test_coerce_type_field_keeps_valid_enum():
    from app.services.plan import coerce_type_field
    content = "---\ntype: process\n---\nbody"
    new, corrected = coerce_type_field(content)
    assert corrected is False
    assert new == content


def test_force_sources_frontmatter_injects_when_missing():
    from app.services.plan import force_sources_frontmatter
    content = "---\ntype: concept\n---\nbody"
    out = force_sources_frontmatter(content, "spec.txt")
    assert 'sources:' in out
    assert '"spec.txt"' in out


def test_force_sources_frontmatter_no_change_when_present():
    from app.services.plan import force_sources_frontmatter
    content = '---\ntype: concept\nsources:\n  - "spec.txt"\n---\nbody'
    out = force_sources_frontmatter(content, "spec.txt")
    assert out == content


# ---------- Pipeline tests ----------

@pytest.mark.asyncio
async def test_sc41_index_md_injected_into_llm_context(tmp_path):
    """SC-41: index.md 내용이 LLM user content에 포함됨"""
    source_file = tmp_path / "spec.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    (wiki_path / "index.md").write_text("# Wiki Index\n\n| existing-page |")

    captured = {}

    async def fake_llm(system, user, response_format=None):
        captured["user"] = user
        return json.dumps({"actions": [
            {"action": "create", "page_path": "new-page.md",
             "content": "---\ntype: concept\n---\n# New Page"}
        ]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new=fake_llm):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="idx-1")

    assert "EXISTING WIKI INDEX" in captured["user"]
    assert "existing-page" in captured["user"]


@pytest.mark.asyncio
async def test_sc41_empty_wiki_uses_no_pages_marker(tmp_path):
    source_file = tmp_path / "spec.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    captured = {}

    async def fake_llm(system, user, response_format=None):
        captured["user"] = user
        return json.dumps({"actions": [
            {"action": "create", "page_path": "new-page.md",
             "content": "---\ntype: concept\n---\n# New Page"}
        ]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new=fake_llm):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="empty-1")

    assert "no existing pages" in captured["user"].lower()


@pytest.mark.asyncio
async def test_sc43_create_action_executes(tmp_path):
    source_file = tmp_path / "spec.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    output = json.dumps({"actions": [
        {"action": "create", "page_path": "intro.md",
         "content": '---\ntype: concept\nsources:\n  - "spec.txt"\n---\n# Intro\nbody'}
    ]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="create-1")

    assert (wiki_path / "intro.md").exists()


@pytest.mark.asyncio
async def test_sc43_create_conflict_downgrades_to_skipped_merge(tmp_path):
    """SC-43: create page_path 충돌 시 자동 merge_into 강등 + log skip"""
    source_file = tmp_path / "spec.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    # 미리 같은 이름의 페이지 존재
    (wiki_path / "intro.md").write_text("---\ntype: concept\n---\n# Old Intro\nold body")

    output = json.dumps({"actions": [
        {"action": "create", "page_path": "intro.md",
         "content": "---\ntype: concept\n---\n# New Intro\nnew body"}
    ]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="conflict-1")

    # 기존 내용은 보존되어야 함 (Phase A에서는 merge skip)
    intro = (wiki_path / "intro.md").read_text()
    assert "old body" in intro
    assert "new body" not in intro

    log = (wiki_path / "log.md").read_text()
    assert "skipped" in log
    assert "create-conflict" in log


@pytest.mark.asyncio
async def test_sc44_merge_into_skipped_logged(tmp_path):
    source_file = tmp_path / "spec.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    (wiki_path / "existing.md").write_text("---\ntype: concept\n---\n# Existing")

    output = json.dumps({"actions": [
        {"action": "merge_into", "target": "existing.md",
         "merged_content": "---\ntype: concept\n---\n# Existing (updated)"}
    ]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="merge-1")

    # Phase A: 기존 페이지 변경 안 됨
    assert "(updated)" not in (wiki_path / "existing.md").read_text()
    log = (wiki_path / "log.md").read_text()
    assert "skipped (phase A): merge_into → [[existing]]" in log


@pytest.mark.asyncio
async def test_sc44_invalid_target_logged(tmp_path):
    source_file = tmp_path / "spec.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    output = json.dumps({"actions": [
        {"action": "merge_into", "target": "nonexistent.md", "merged_content": "..."}
    ]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="invalid-1")

    log = (wiki_path / "log.md").read_text()
    assert "target not found" in log


@pytest.mark.asyncio
async def test_sc45_graceful_degrade_to_legacy_fallback(tmp_path):
    """SC-45: JSON 파싱 실패 시 기존 4단계 fallback으로 흡수"""
    source_file = tmp_path / "spec.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    # JSON parse 실패하지만 frontmatter+body가 있는 legacy 출력
    legacy_output = (
        "---\n"
        "type: concept\n"
        "created: 2026-05-08 00:00:00\n"
        "last_updated: 2026-05-08 00:00:00\n"
        "tags: []\n"
        'sources:\n  - "spec.txt"\n'
        "---\n"
        "# Spec\nbody"
    )

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=legacy_output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="degrade-1")

    # 페이지 생성됨
    md_files = [p for p in wiki_path.glob("*.md") if p.name not in ("index.md", "log.md")]
    assert len(md_files) == 1
    log = (wiki_path / "log.md").read_text()
    assert "JSON parse failed" in log


@pytest.mark.asyncio
async def test_sc45_pure_garbage_raises(tmp_path):
    """SC-45: JSON도 legacy도 안 되면 ValueError"""
    source_file = tmp_path / "spec.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    junk = "Sorry, I cannot help with that request."

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=junk):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        with pytest.raises(ValueError, match="neither valid JSON Plan nor parseable legacy"):
            await run_ingest(str(source_file), db=None, job_id="junk-1")


@pytest.mark.asyncio
async def test_sc51_type_enum_violation_corrected(tmp_path):
    source_file = tmp_path / "spec.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    output = json.dumps({"actions": [
        {"action": "create", "page_path": "page.md",
         "content": "---\ntype: invalidtype\nsources:\n  - \"spec.txt\"\n---\n# Page\nbody"}
    ]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="enum-1")

    content = (wiki_path / "page.md").read_text()
    assert "type: reference" in content
    assert "type: invalidtype" not in content


# ---------- init_env.py smoke test ----------

def test_init_env_script_exists():
    """T-3a-6: init_env.py 존재, seed_admin.py 폐기"""
    backend = Path(__file__).resolve().parent.parent
    assert (backend / "scripts" / "init_env.py").exists()
    assert not (backend / "scripts" / "seed_admin.py").exists()


def test_init_env_email_validator_exists():
    """init_env가 이메일/패스워드 검증 로직을 노출 — 회귀 방지"""
    import importlib.util
    backend = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "init_env_mod", backend / "scripts" / "init_env.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.EMAIL_RE.match("admin@example.com")
    assert not mod.EMAIL_RE.match("not-an-email")
    assert mod.MIN_PASSWORD_LEN == 8
