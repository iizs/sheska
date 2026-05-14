"""v0.4 — agentic loop / tool catalog / backlinks tests."""
from __future__ import annotations
import json
import pytest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

from .conftest import get_token


# ============================ wiki_store helpers ============================

def test_extract_wikilinks_basic():
    from app.services.wiki_store import extract_wikilinks
    content = (
        "---\nbacklinks:\n  - other\n---\n"
        "# Title\nLook at [[alpha]] and [[beta|aliased]] and [[alpha]] again."
    )
    links = extract_wikilinks(content)
    assert links == {"alpha", "beta"}


def test_extract_wikilinks_skips_frontmatter():
    from app.services.wiki_store import extract_wikilinks
    content = (
        "---\ntype: concept\nbacklinks:\n  - some-page\n---\n"
        "No wikilinks in body."
    )
    assert extract_wikilinks(content) == set()


def test_apply_unified_diff_basic_change(tmp_path):
    from app.services.wiki_store import apply_unified_diff
    original = "line 1\nline 2\nline 3\n"
    diff = (
        "@@\n"
        " line 1\n"
        "-line 2\n"
        "+line two\n"
        " line 3\n"
    )
    result = apply_unified_diff(original, diff)
    assert result["error"] is None
    assert result["hunks_applied"] == 1
    assert "line two" in result["new_content"]
    assert "line 2" not in result["new_content"]


def test_apply_unified_diff_context_fuzzy():
    """Whitespace-only context differences should still match."""
    from app.services.wiki_store import apply_unified_diff
    original = "line 1\n  line 2\nline 3\n"
    diff = (
        "@@\n"
        " line 1\n"
        "-line 2\n"
        "+line two\n"
        " line 3\n"
    )
    result = apply_unified_diff(original, diff)
    assert result["hunks_applied"] == 1


def test_apply_unified_diff_context_missing_fails():
    from app.services.wiki_store import apply_unified_diff
    original = "line a\nline b\nline c\n"
    diff = (
        "@@\n"
        " line X\n"
        "-line Y\n"
        "+line Z\n"
        " line W\n"
    )
    result = apply_unified_diff(original, diff)
    assert result["hunks_applied"] == 0
    assert len(result["hunks_failed"]) == 1


def test_apply_unified_diff_multiple_hunks_independent():
    from app.services.wiki_store import apply_unified_diff
    original = "a\nb\nc\nx\ny\nz\n"
    diff = (
        "@@\n"
        " a\n"
        "-b\n"
        "+B\n"
        " c\n"
        "@@\n"
        " GHOST CONTEXT\n"
        "-y\n"
        "+Y\n"
        " z\n"
    )
    result = apply_unified_diff(original, diff)
    assert result["hunks_applied"] == 1
    assert "B" in result["new_content"]
    assert len(result["hunks_failed"]) == 1


# ============================ Backlink index ============================

def test_update_backlinks_adds_and_removes(tmp_path):
    from app.services import wiki_store
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    # alpha already has `source` backlink (so the removal step will mutate it)
    (wiki / "alpha.md").write_text(
        "---\ntype: reference\nbacklinks:\n  - source\n---\n# Alpha\n"
    )
    (wiki / "beta.md").write_text("---\ntype: reference\n---\n# Beta\n")

    # source page changes [[alpha]] -> [[beta]]
    old = "---\ntype: concept\n---\n# Source\nLink [[alpha]]\n"
    new = "---\ntype: concept\n---\n# Source\nLink [[beta]]\n"
    (wiki / "source.md").write_text(new)
    changed = wiki_store.update_backlinks_for_change(wiki, "source.md", old, new)
    assert "alpha.md" in changed
    assert "beta.md" in changed

    alpha = (wiki / "alpha.md").read_text()
    beta = (wiki / "beta.md").read_text()
    assert "source" not in alpha  # backlink removed
    assert "source" in beta       # backlink added


def test_init_backlinks_script_idempotent(tmp_path, monkeypatch):
    import subprocess
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text("---\ntype: reference\n---\n# A\nLink [[b]]\n")
    (wiki / "b.md").write_text("---\ntype: reference\n---\n# B\n")

    monkeypatch.setenv("WIKI_STORE_PATH", str(wiki))
    backend = Path(__file__).resolve().parent.parent
    r1 = subprocess.run(
        ["python", str(backend / "scripts" / "init_backlinks.py")],
        cwd=str(backend), env={**__import__("os").environ},
        capture_output=True, text=True,
    )
    assert r1.returncode == 0
    b_content = (wiki / "b.md").read_text()
    assert "backlinks" in b_content
    assert "a" in b_content

    r2 = subprocess.run(
        ["python", str(backend / "scripts" / "init_backlinks.py")],
        cwd=str(backend), capture_output=True, text=True,
    )
    assert "already up to date" in r2.stdout


# ============================ Tool executors ============================

@pytest.mark.asyncio
async def test_tool_write_page_executes(tmp_path):
    from app.services.tools import get_executor, ToolContext
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    ctx = ToolContext(job_type="wiki_command", job_id="t1")
    fn = get_executor("write_page")
    result = await fn(wiki, {
        "path": "intro.md",
        "content": "---\ntype: concept\n---\n# Intro\nbody\n",
    }, ctx)
    payload = json.loads(result)
    assert payload["ok"] is True
    assert (wiki / "intro.md").exists()
    assert "intro.md" in ctx.written_paths


@pytest.mark.asyncio
async def test_tool_write_page_rejects_reserved(tmp_path):
    from app.services.tools import get_executor, ToolContext
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    ctx = ToolContext(job_type="wiki_command", job_id="t2")
    fn = get_executor("write_page")
    result = await fn(wiki, {"path": "index.md", "content": "x"}, ctx)
    payload = json.loads(result)
    assert payload["ok"] is False
    assert "reserved" in payload["error"]


@pytest.mark.asyncio
async def test_tool_delete_page_forbidden_in_ingest(tmp_path):
    from app.services.tools import get_executor, ToolContext
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "victim.md").write_text("---\ntype: concept\n---\n# V\n")
    ctx = ToolContext(job_type="ingest", job_id="t3", source_filename="x.txt")
    fn = get_executor("delete_page")
    result = await fn(wiki, {"path": "victim.md", "reason": "stale"}, ctx)
    payload = json.loads(result)
    assert payload["ok"] is False
    assert "forbidden in INGEST" in payload["error"]
    assert (wiki / "victim.md").exists()  # not deleted


@pytest.mark.asyncio
async def test_tool_delete_page_executes_in_wiki_command(tmp_path):
    from app.services.tools import get_executor, ToolContext
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "obsolete.md").write_text("---\ntype: concept\n---\n# O\n")
    ctx = ToolContext(job_type="wiki_command", job_id="t4")
    fn = get_executor("delete_page")
    result = await fn(wiki, {"path": "obsolete.md", "reason": "merged"}, ctx)
    payload = json.loads(result)
    assert payload["ok"] is True
    assert not (wiki / "obsolete.md").exists()
    assert "obsolete.md" in ctx.deleted_paths


@pytest.mark.asyncio
async def test_tool_patch_page_unified_diff(tmp_path):
    from app.services.tools import get_executor, ToolContext
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "page.md").write_text("---\ntype: concept\n---\n# Page\nold body\nmore\n")
    ctx = ToolContext(job_type="wiki_command", job_id="t5")
    fn = get_executor("patch_page")
    diff = "@@\n # Page\n-old body\n+new body\n more\n"
    result = await fn(wiki, {"path": "page.md", "diff": diff}, ctx)
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["hunks_applied"] == 1
    assert "new body" in (wiki / "page.md").read_text()


@pytest.mark.asyncio
async def test_tool_patch_page_no_hunks_applied_no_commit(tmp_path):
    from app.services.tools import get_executor, ToolContext
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "page.md").write_text("---\ntype: concept\n---\n# Page\nactual body\n")
    ctx = ToolContext(job_type="wiki_command", job_id="t6")
    fn = get_executor("patch_page")
    diff = "@@\n NOT IN FILE\n-x\n+y\n"
    result = await fn(wiki, {"path": "page.md", "diff": diff}, ctx)
    payload = json.loads(result)
    assert payload["ok"] is False
    assert payload["applied"] is False
    assert payload["hunks_applied"] == 0
    # File not modified
    assert "actual body" in (wiki / "page.md").read_text()
    assert "page.md" not in ctx.written_paths


@pytest.mark.asyncio
async def test_sc71_patch_page_refreshes_last_updated(tmp_path):
    """SC-71 hotfix: patch_page sets a fresh last_updated automatically."""
    from app.services.tools import get_executor, ToolContext
    from app.services import wiki_store
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    wiki_store._get_repo(wiki)
    (wiki / "page.md").write_text(
        "---\ntype: concept\nlast_updated: 2025-01-01 00:00:00\n---\n# Page\nold\n"
    )
    ctx = ToolContext(job_type="wiki_command", job_id="lu1")
    fn = get_executor("patch_page")
    diff = "@@\n # Page\n-old\n+new\n"
    await fn(wiki, {"path": "page.md", "diff": diff}, ctx)
    content = (wiki / "page.md").read_text()
    assert "2025-01-01 00:00:00" not in content
    assert "last_updated:" in content


@pytest.mark.asyncio
async def test_sc71_write_page_refreshes_last_updated(tmp_path):
    """SC-71 hotfix: write_page also sets last_updated."""
    from app.services.tools import get_executor, ToolContext
    from app.services import wiki_store
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    wiki_store._get_repo(wiki)
    ctx = ToolContext(job_type="wiki_command", job_id="lu2")
    fn = get_executor("write_page")
    content_in = "---\ntype: concept\nlast_updated: 2025-01-01 00:00:00\n---\n# X\n"
    await fn(wiki, {"path": "new.md", "content": content_in}, ctx)
    content_out = (wiki / "new.md").read_text()
    assert "2025-01-01 00:00:00" not in content_out
    assert "last_updated:" in content_out


@pytest.mark.asyncio
async def test_sc78_write_tool_commits_per_call(tmp_path):
    """SC-78: each write tool call produces a separate git commit with required message pattern."""
    from app.services.tools import get_executor, ToolContext
    from app.services import wiki_store
    import git

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    repo = wiki_store._get_repo(wiki)
    initial_commits = sum(1 for _ in repo.iter_commits())

    ctx = ToolContext(job_type="wiki_command", job_id="JOB123")
    write = get_executor("write_page")
    patch = get_executor("patch_page")
    delete = get_executor("delete_page")

    await write(wiki, {
        "path": "p1.md",
        "content": "---\ntype: concept\n---\n# P1\nbody\nmore\n",
    }, ctx)
    await write(wiki, {
        "path": "p2.md",
        "content": "---\ntype: concept\n---\n# P2\nbody\n",
    }, ctx)
    diff = "@@\n # P1\n-body\n+UPDATED body\n more\n"
    await patch(wiki, {"path": "p1.md", "diff": diff}, ctx)
    await delete(wiki, {"path": "p2.md", "reason": "obsolete"}, ctx)

    commits = list(repo.iter_commits())
    new_count = len(commits) - initial_commits
    assert new_count == 4, f"expected 4 commits, got {new_count}"

    messages = [c.message.strip() for c in commits[:4]]
    assert any("step:1] write_page: p1.md" in m for m in messages)
    assert any("step:2] write_page: p2.md" in m for m in messages)
    assert any("step:3] patch_page: p1.md" in m for m in messages)
    assert any("step:4] delete_page: p2.md" in m for m in messages)
    for m in messages:
        assert "job:JOB123" in m


@pytest.mark.asyncio
async def test_tool_get_backlinks(tmp_path):
    from app.services.tools import get_executor, ToolContext
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "page.md").write_text(
        "---\ntype: concept\nbacklinks:\n  - alpha\n  - beta\n---\n# Page\n"
    )
    ctx = ToolContext(job_type="wiki_command", job_id="t7")
    fn = get_executor("get_backlinks")
    result = await fn(wiki, {"page": "page.md"}, ctx)
    payload = json.loads(result)
    assert payload["ok"] is True
    assert set(payload["backlinks"]) == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_tool_search_pages_truncates(tmp_path):
    from app.services.tools import get_executor, ToolContext
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    for i in range(25):
        (wiki / f"p{i:02d}.md").write_text(
            f"---\ntype: concept\n---\n# P{i}\nThe needle is here\n"
        )
    ctx = ToolContext(job_type="wiki_command", job_id="t8")
    fn = get_executor("search_pages")
    result = await fn(wiki, {"query": "needle", "max_items": 20}, ctx)
    payload = json.loads(result)
    assert payload["ok"] is True
    assert len(payload["matches"]) == 20
    assert payload["truncated"] is True


# ============================ Agentic loop (mocked Anthropic) ============================

def _fake_anthropic_response(blocks: list[dict], stop_reason: str = "end_turn"):
    """Mimic anthropic SDK response object: .content list with .model_dump()."""
    class _Block:
        def __init__(self, data):
            self._data = data
        def model_dump(self):
            return self._data
    return SimpleNamespace(
        content=[_Block(b) for b in blocks],
        stop_reason=stop_reason,
    )


@pytest.mark.asyncio
async def test_prompt_caching_applied_to_system_and_tools():
    """system + tools list arrive with cache_control on the cacheable prefix."""
    from app.services import llm_client

    captured: dict = {}

    class _Capture:
        def __init__(self, **kw): pass
        class messages:
            @staticmethod
            async def create(**kwargs):
                captured.update(kwargs)
                return _fake_anthropic_response(
                    [{"type": "text", "text": "done"}], stop_reason="end_turn"
                )

    tools = [
        {"name": "alpha", "input_schema": {"type": "object", "properties": {}}},
        {"name": "beta", "input_schema": {"type": "object", "properties": {}}},
    ]
    with patch.object(llm_client, "get_settings") as mock_settings, \
         patch("anthropic.AsyncAnthropic", new=_Capture):
        s = mock_settings.return_value
        s.litellm_provider = "anthropic"
        s.litellm_model = "claude-sonnet"
        s.litellm_api_key = "k"
        s.agent_max_iterations = 3
        s.agent_max_tool_calls = 5
        s.agent_timeout_seconds = 30
        s.agent_repeat_pattern_threshold = 3
        s.llm_max_output_tokens = 8192
        await llm_client.run_agentic_loop(
            system_prompt="system text",
            user_content="u",
            tools_schemas=tools,
            tool_executor=lambda *_: None,
        )

    sys_arg = captured.get("system")
    assert isinstance(sys_arg, list)
    assert sys_arg[0]["text"] == "system text"
    assert sys_arg[0]["cache_control"] == {"type": "ephemeral"}

    tools_arg = captured.get("tools")
    assert tools_arg[-1]["name"] == "beta"
    assert tools_arg[-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in tools_arg[0]  # only the last one carries it


def test_add_cache_control_helper_does_not_mutate_input():
    from app.services.llm_client import _add_cache_control_to_last
    original = [
        {"name": "a", "input_schema": {}},
        {"name": "b", "input_schema": {}},
    ]
    snapshot = [dict(t) for t in original]
    result = _add_cache_control_to_last(original)
    assert original == snapshot  # input unchanged
    assert result[-1]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.asyncio
async def test_llm_max_output_tokens_passed_to_anthropic():
    """LLM_MAX_OUTPUT_TOKENS env value reaches Anthropic SDK as max_tokens."""
    from app.services import llm_client

    captured: dict = {}

    class _Capture:
        def __init__(self, **kw): pass
        class messages:
            @staticmethod
            async def create(**kwargs):
                captured.update(kwargs)
                return _fake_anthropic_response(
                    [{"type": "text", "text": "done"}], stop_reason="end_turn"
                )

    with patch.object(llm_client, "get_settings") as mock_settings, \
         patch("anthropic.AsyncAnthropic", new=_Capture):
        s = mock_settings.return_value
        s.litellm_provider = "anthropic"
        s.litellm_model = "claude-3-5"
        s.litellm_api_key = "key"
        s.agent_max_iterations = 5
        s.agent_max_tool_calls = 10
        s.agent_timeout_seconds = 30
        s.agent_repeat_pattern_threshold = 3
        s.llm_max_output_tokens = 16384
        await llm_client.run_agentic_loop(
            system_prompt="s", user_content="u", tools_schemas=[],
            tool_executor=lambda *_: None,  # never called
        )
    assert captured.get("max_tokens") == 16384


@pytest.mark.asyncio
async def test_sc64_agentic_loop_natural_end(tmp_path):
    """SC-64: agentic loop ends on stop_reason=end_turn with no tool_use."""
    from app.services import llm_client

    captured_steps: list[dict] = []
    call_count = {"n": 0}

    class FakeClient:
        def __init__(self, **kw): pass
        class messages:
            @staticmethod
            async def create(**kwargs):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return _fake_anthropic_response([
                        {"type": "tool_use", "id": "u1", "name": "get_index", "input": {}}
                    ])
                return _fake_anthropic_response(
                    [{"type": "text", "text": "Done."}],
                    stop_reason="end_turn",
                )

    async def fake_executor(name, inp):
        return json.dumps({"ok": True, "content": "wiki index..."})

    async def on_step(s): captured_steps.append(s)

    with patch.object(llm_client, "get_settings") as mock_settings, \
         patch("anthropic.AsyncAnthropic", new=FakeClient):
        s = mock_settings.return_value
        s.litellm_provider = "anthropic"
        s.litellm_model = "claude-3-5"
        s.litellm_api_key = "key"
        s.agent_max_iterations = 20
        s.agent_max_tool_calls = 50
        s.agent_timeout_seconds = 60
        s.agent_repeat_pattern_threshold = 3
        result = await llm_client.run_agentic_loop(
            system_prompt="sys",
            user_content="hi",
            tools_schemas=[{"name": "get_index", "input_schema": {"type": "object", "properties": {}}}],
            tool_executor=fake_executor,
            on_step=on_step,
        )

    assert result["stop_reason"] == "end_turn"
    assert result["tool_calls"] == 1
    assert len(captured_steps) == 1
    assert captured_steps[0]["tool_name"] == "get_index"


@pytest.mark.asyncio
async def test_sc65_max_iterations_aborts():
    from app.services import llm_client

    class _Loop:
        def __init__(self, **kw): pass
        class messages:
            @staticmethod
            async def create(**kwargs):
                return _fake_anthropic_response(
                    [{"type": "tool_use", "id": f"u{id(kwargs)}", "name": "get_index", "input": {"q": id(kwargs)}}]
                )

    async def fake_executor(name, inp):
        return json.dumps({"ok": True})

    with patch.object(llm_client, "get_settings") as mock_settings, \
         patch("anthropic.AsyncAnthropic", new=_Loop):
        s = mock_settings.return_value
        s.litellm_provider = "anthropic"
        s.litellm_model = "m"
        s.litellm_api_key = "key"
        s.agent_max_iterations = 3
        s.agent_max_tool_calls = 100
        s.agent_timeout_seconds = 60
        s.agent_repeat_pattern_threshold = 999  # disable pattern check
        with pytest.raises(llm_client.AgenticError, match="max_iterations"):
            await llm_client.run_agentic_loop(
                system_prompt="s", user_content="u", tools_schemas=[],
                tool_executor=fake_executor,
            )


@pytest.mark.asyncio
async def test_sc65_repeat_pattern_aborts():
    from app.services import llm_client

    class _Loop:
        def __init__(self, **kw): pass
        class messages:
            @staticmethod
            async def create(**kwargs):
                return _fake_anthropic_response(
                    [{"type": "tool_use", "id": "same", "name": "get_index", "input": {"x": 1}}]
                )

    async def fake_executor(name, inp):
        return "{}"

    with patch.object(llm_client, "get_settings") as mock_settings, \
         patch("anthropic.AsyncAnthropic", new=_Loop):
        s = mock_settings.return_value
        s.litellm_provider = "anthropic"
        s.litellm_model = "m"
        s.litellm_api_key = "key"
        s.agent_max_iterations = 99
        s.agent_max_tool_calls = 99
        s.agent_timeout_seconds = 60
        s.agent_repeat_pattern_threshold = 3
        with pytest.raises(llm_client.AgenticError, match="repeat pattern"):
            await llm_client.run_agentic_loop(
                system_prompt="s", user_content="u", tools_schemas=[],
                tool_executor=fake_executor,
            )


@pytest.mark.asyncio
async def test_sc65_max_tokens_aborts():
    from app.services import llm_client

    class _Loop:
        def __init__(self, **kw): pass
        class messages:
            @staticmethod
            async def create(**kwargs):
                return _fake_anthropic_response(
                    [{"type": "text", "text": "partial..."}],
                    stop_reason="max_tokens",
                )

    async def fake_executor(name, inp):
        return "{}"

    with patch.object(llm_client, "get_settings") as mock_settings, \
         patch("anthropic.AsyncAnthropic", new=_Loop):
        s = mock_settings.return_value
        s.litellm_provider = "anthropic"
        s.litellm_model = "m"
        s.litellm_api_key = "key"
        s.agent_max_iterations = 20
        s.agent_max_tool_calls = 50
        s.agent_timeout_seconds = 60
        s.agent_repeat_pattern_threshold = 3
        with pytest.raises(llm_client.AgenticError, match="max_tokens"):
            await llm_client.run_agentic_loop(
                system_prompt="s", user_content="u", tools_schemas=[],
                tool_executor=fake_executor,
            )


@pytest.mark.asyncio
async def test_sc66_user_cancel_during_loop():
    from app.services import llm_client

    class _Loop:
        def __init__(self, **kw): pass
        class messages:
            @staticmethod
            async def create(**kwargs):
                return _fake_anthropic_response(
                    [{"type": "tool_use", "id": "u", "name": "get_index", "input": {}}]
                )

    cancel_flag = {"v": False}

    async def fake_executor(name, inp):
        cancel_flag["v"] = True  # next iteration must abort
        return "{}"

    async def is_cancelled(): return cancel_flag["v"]

    with patch.object(llm_client, "get_settings") as mock_settings, \
         patch("anthropic.AsyncAnthropic", new=_Loop):
        s = mock_settings.return_value
        s.litellm_provider = "anthropic"
        s.litellm_model = "m"
        s.litellm_api_key = "key"
        s.agent_max_iterations = 20
        s.agent_max_tool_calls = 50
        s.agent_timeout_seconds = 60
        s.agent_repeat_pattern_threshold = 999
        with pytest.raises(llm_client.AgenticCancelled):
            await llm_client.run_agentic_loop(
                system_prompt="s", user_content="u", tools_schemas=[],
                tool_executor=fake_executor,
                is_cancelled=is_cancelled,
            )


@pytest.mark.asyncio
async def test_sc74_non_anthropic_provider_fails_fast():
    """SC-74: Anthropic 외 provider → 즉시 Job FAILED + 명시 에러"""
    from app.services import pipeline

    with patch("app.services.pipeline.is_anthropic_provider", return_value=False), \
         patch("app.services.pipeline.get_settings") as mock_settings:
        s = mock_settings.return_value
        s.litellm_provider = "ollama"
        with pytest.raises(ValueError, match="does not support agentic mode"):
            await pipeline.run_wiki_command("test command", db=None, job_id="np-1")


# ============================ Cancel endpoint (SC-66/80) ============================

@pytest.mark.asyncio
async def test_sc66_cancel_endpoint(client: AsyncClient, db_session):
    """POST /api/jobs/{id}/cancel sets status to Cancelling."""
    from app.models.job import Job, JobType, JobStatus
    import uuid
    # member user submits a fake pending job directly via DB
    token = await get_token(client, "member@test.com", "memberpass")
    me_resp = await client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    me_id = me_resp.json()["id"]

    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        type=JobType.wiki_command,
        payload={"command_text": "test"},
        status=JobStatus.processing,
        created_by=me_id,
    )
    db_session.add(job)
    await db_session.commit()

    resp = await client.post(
        f"/api/jobs/{job_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == JobStatus.cancelling.value


@pytest.mark.asyncio
async def test_sc66_cancel_other_users_job_forbidden(client: AsyncClient, db_session):
    from app.models.job import Job, JobType, JobStatus
    import uuid
    admin_token = await get_token(client, "admin@test.com", "adminpass")
    admin_id = (await client.get("/api/users/me",
                                  headers={"Authorization": f"Bearer {admin_token}"})).json()["id"]
    member_token = await get_token(client, "member@test.com", "memberpass")

    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id, type=JobType.wiki_command,
        payload={"command_text": "x"}, status=JobStatus.processing, created_by=admin_id,
    )
    db_session.add(job)
    await db_session.commit()

    resp = await client.post(
        f"/api/jobs/{job_id}/cancel",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sc66_cancel_done_job_is_idempotent(client: AsyncClient, db_session):
    from app.models.job import Job, JobType, JobStatus
    import uuid
    token = await get_token(client, "admin@test.com", "adminpass")
    admin_id = (await client.get("/api/users/me",
                                  headers={"Authorization": f"Bearer {token}"})).json()["id"]
    job_id = str(uuid.uuid4())
    job = Job(id=job_id, type=JobType.wiki_command, payload={"command_text": "x"},
              status=JobStatus.done, created_by=admin_id)
    db_session.add(job)
    await db_session.commit()
    resp = await client.post(
        f"/api/jobs/{job_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    # idempotent: terminal status preserved
    assert resp.status_code == 200
    assert resp.json()["status"] == JobStatus.done.value
