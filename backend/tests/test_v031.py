from __future__ import annotations
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient
from .conftest import get_token


# ---------------- Plan model ----------------

def test_delete_action_validates():
    from app.services.plan import Plan
    plan = Plan.model_validate({"actions": [
        {"action": "delete", "target": "page.md", "reason": "obsolete"}
    ]})
    assert plan.actions[0].action == "delete"


def test_delete_action_path_traversal_rejected():
    from app.services.plan import Plan
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Plan.model_validate({"actions": [
            {"action": "delete", "target": "../etc/passwd.md"}
        ]})


def test_is_reserved_path():
    from app.services.plan import is_reserved_path
    assert is_reserved_path("index.md")
    assert is_reserved_path("log.md")
    assert is_reserved_path("_sheska.yaml")
    assert is_reserved_path("_secret.md")
    assert not is_reserved_path("regular-page.md")


# ---------------- merge_frontmatter ----------------

def test_merge_frontmatter_preserves_created_and_unions_lists():
    from app.services.plan import merge_frontmatter
    existing = (
        "---\n"
        "type: concept\n"
        "created: 2026-01-01 00:00:00\n"
        "last_updated: 2026-01-01 00:00:00\n"
        "tags: [a, b]\n"
        "sources:\n"
        '  - "old.txt"\n'
        "---\n"
        "# Page\nold body\n"
    )
    new = (
        "---\n"
        "type: process\n"  # 무시되어야 — 기존 보존
        "created: 2099-01-01 00:00:00\n"  # 무시 — 기존 보존
        "last_updated: 2026-05-09 00:00:00\n"
        "tags: [b, c]\n"
        "sources:\n"
        '  - "new.txt"\n'
        "---\n"
        "# Page\nnew body\n"
    )
    out = merge_frontmatter(existing, new, "2026-05-09 12:00:00")
    assert "type: concept" in out  # existing preserved
    assert "type: process" not in out
    assert "created: 2026-01-01" in out
    assert "created: 2099-01-01" not in out
    assert "last_updated: 2026-05-09 12:00:00" in out
    assert '"old.txt"' in out
    assert '"new.txt"' in out
    # tags should include all of a/b/c, no duplication
    assert out.count('"a"') + out.count("- a") >= 1
    assert out.count('"c"') + out.count("- c") >= 1
    assert "new body" in out


# ---------------- merge_into / supersede / delete execution ----------------

@pytest.mark.asyncio
async def test_sc52_merge_into_executes(tmp_path):
    """SC-52: merge_into 정상 실행 + frontmatter 정책"""
    source_file = tmp_path / "src.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    (wiki_path / "page.md").write_text(
        "---\ntype: concept\ncreated: 2026-01-01 00:00:00\n"
        "last_updated: 2026-01-01 00:00:00\ntags: [a]\nsources: []\n---\n"
        "# Page\nold body\n"
    )

    plan_output = json.dumps({"actions": [{
        "action": "merge_into",
        "target": "page.md",
        "merged_content": (
            "---\ntype: process\ncreated: 2099-01-01\n"
            "last_updated: 2099-01-01\ntags: [b]\n"
            'sources:\n  - "src.txt"\n---\n# Page\nNEW BODY\n'
        ),
    }]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=plan_output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="merge-1")

    page = (wiki_path / "page.md").read_text()
    assert "NEW BODY" in page
    assert "old body" not in page
    assert "type: concept" in page  # existing type preserved
    assert "created: 2026-01-01" in page  # existing created preserved
    log = (wiki_path / "log.md").read_text()
    assert "executed: merge_into → [[page]]" in log


@pytest.mark.asyncio
async def test_sc53_supersede_executes(tmp_path):
    source_file = tmp_path / "src.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    (wiki_path / "old.md").write_text(
        "---\ntype: concept\ncreated: 2025-01-01\n"
        "last_updated: 2025-01-01\ntags: []\nsources: []\n---\n"
        "# Old\nstale\n"
    )

    plan_output = json.dumps({"actions": [{
        "action": "supersede",
        "target": "old.md",
        "reason": "outdated",
        "new_content": (
            "---\ntype: concept\ncreated: 2099-01-01\n"
            "last_updated: 2026-05-09\ntags: []\nsources: []\n---\n# Old\nfresh\n"
        ),
    }]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=plan_output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""
        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="sup-1")

    page = (wiki_path / "old.md").read_text()
    assert "fresh" in page
    assert "stale" not in page
    log = (wiki_path / "log.md").read_text()
    assert "executed: supersede → [[old]]" in log
    assert "outdated" in log


@pytest.mark.asyncio
async def test_sc54_delete_executes_in_wiki_command(tmp_path):
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    (wiki_path / "doomed.md").write_text(
        "---\ntype: concept\n---\n# Doomed\n"
    )

    plan_output = json.dumps({"actions": [{
        "action": "delete",
        "target": "doomed.md",
        "reason": "obsolete",
    }]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=plan_output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""
        from app.services.pipeline import run_wiki_command
        await run_wiki_command("delete the obsolete page", db=None, job_id="del-1")

    assert not (wiki_path / "doomed.md").exists()
    log = (wiki_path / "log.md").read_text()
    assert "executed: delete → [[doomed]]" in log
    assert "obsolete" in log


@pytest.mark.asyncio
async def test_sc55_create_conflict_phase_b_executes_merge(tmp_path):
    """SC-55: create 충돌 시 Phase B에서는 정상 merge 실행"""
    source_file = tmp_path / "src.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    (wiki_path / "page.md").write_text(
        "---\ntype: concept\ncreated: 2025-01-01\n"
        "last_updated: 2025-01-01\ntags: []\nsources: []\n---\n# Page\nold\n"
    )

    plan_output = json.dumps({"actions": [{
        "action": "create",
        "page_path": "page.md",
        "content": (
            "---\ntype: concept\ncreated: 2099-01-01\n"
            "last_updated: 2099-01-01\ntags: []\nsources: []\n---\n# Page\nNEW\n"
        ),
    }]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=plan_output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""
        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="conflict-2")

    page = (wiki_path / "page.md").read_text()
    assert "NEW" in page
    assert "created: 2025-01-01" in page  # frontmatter preservation
    log = (wiki_path / "log.md").read_text()
    assert "executed: merge_into ← create-conflict → [[page]]" in log


@pytest.mark.asyncio
async def test_sc56_delete_reserved_file_rejected(tmp_path):
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    plan_output = json.dumps({"actions": [{
        "action": "delete",
        "target": "index.md",
    }]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=plan_output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""
        from app.services.pipeline import run_wiki_command
        await run_wiki_command("delete index", db=None, job_id="reject-1")

    # index.md is rebuilt anyway (system file)
    assert (wiki_path / "index.md").exists()
    log = (wiki_path / "log.md").read_text()
    assert "rejected: delete → [[index]] (reserved file)" in log


@pytest.mark.asyncio
async def test_sc63_delete_in_ingest_rejected(tmp_path):
    """SC-63: INGEST plan에 delete 액션 → 거부"""
    source_file = tmp_path / "src.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    (wiki_path / "victim.md").write_text("---\ntype: concept\n---\n# Victim\n")

    plan_output = json.dumps({"actions": [
        {"action": "delete", "target": "victim.md", "reason": "ingest tries to delete"},
        {"action": "create", "page_path": "newpage.md",
         "content": "---\ntype: concept\nsources:\n  - \"src.txt\"\n---\n# New\n"},
    ]})

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=plan_output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""
        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="ingest-del-1")

    # victim 페이지는 그대로
    assert (wiki_path / "victim.md").exists()
    # newpage는 정상 생성
    assert (wiki_path / "newpage.md").exists()
    log = (wiki_path / "log.md").read_text()
    assert "rejected: delete → [[victim]] (forbidden in INGEST)" in log
    assert "executed: create → [[newpage]]" in log


# ---------------- WIKI_COMMAND endpoint ----------------

@pytest.mark.asyncio
async def test_sc57_wiki_command_member_can_submit(client: AsyncClient):
    token = await get_token(client, "member@test.com", "memberpass")
    with patch("app.routes.wiki.enqueue_job", new_callable=AsyncMock):
        resp = await client.post(
            "/api/wiki/commands",
            json={"command_text": "delete [[anything]]"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_sc57_empty_command_text_rejected(client: AsyncClient):
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.post(
        "/api/wiki/commands",
        json={"command_text": "   "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sc57_wiki_command_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/wiki/commands",
        json={"command_text": "test"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sc59_empty_plan_succeeds(tmp_path):
    """SC-59: actions=[] → SUCCESS + log 'no actions'"""
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock,
               return_value=json.dumps({"actions": []})):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""
        from app.services.pipeline import run_wiki_command
        await run_wiki_command("vague request", db=None, job_id="empty-1")

    log = (wiki_path / "log.md").read_text()
    assert "no actions" in log
