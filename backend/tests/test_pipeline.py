from __future__ import annotations
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient
from .conftest import get_token


MOCK_INGEST_OUTPUT = """=== FILE: product-overview.md ===
---
type: concept
created: 2026-05-07 00:00:00
last_updated: 2026-05-07 00:00:00
tags: [product]
sources:
  - "test.txt"
---
# Product Overview
This is a test page about the product.

[[related-page]]
"""

MOCK_EDIT_OUTPUT = """---
type: concept
created: 2026-05-07 00:00:00
last_updated: 2026-05-07 01:00:00
tags: [product, updated]
sources:
  - "test.txt"
---
# Product Overview (Updated)
This page has been updated.
"""


@pytest.mark.asyncio
async def test_sc11_ingest_job_registered(client: AsyncClient, tmp_path):
    """SC-11: 파일 업로드 후 INGEST Job 등록, 즉시 'queued' 응답"""
    token = await get_token(client, "admin@test.com", "adminpass")
    with patch("app.routes.sources._source_store", return_value=tmp_path), \
         patch("app.routes.sources.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = await client.post(
            "/api/sources/",
            files={"file": ("test.txt", b"sample content", "text/plain")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_sc11b_ingest_flow_creates_wiki_pages(tmp_path):
    """SC-11-b: Ingest flow 완료 후 Wiki Store에 MD 파일 git commit"""
    source_file = tmp_path / "test.txt"
    source_file.write_text("This is a test document about our product.")

    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=MOCK_INGEST_OUTPUT):
        settings = mock_settings.return_value
        settings.wiki_store_path = str(wiki_path)
        settings.prompts_path = str(tmp_path / "prompts")
        settings.litellm_provider = "anthropic"
        settings.litellm_model = "claude-haiku-4-5-20251001"
        settings.litellm_api_key = ""
        settings.litellm_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="test-job-1")

    assert (wiki_path / "product-overview.md").exists()
    assert (wiki_path / "index.md").exists()
    assert (wiki_path / "log.md").exists()


@pytest.mark.asyncio
async def test_sc12_frontmatter_fields(tmp_path):
    """SC-12: 위키 페이지 frontmatter에 필수 필드 존재"""
    source_file = tmp_path / "spec.txt"
    source_file.write_text("Product specification document.")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=MOCK_INGEST_OUTPUT):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="test-job-2")

    content = (wiki_path / "product-overview.md").read_text()
    for field in ["type:", "created:", "last_updated:", "tags:", "sources:"]:
        assert field in content, f"Missing frontmatter field: {field}"


@pytest.mark.asyncio
async def test_sc13_obsidian_link_format(tmp_path):
    """SC-13: 내부 링크가 [[페이지명]] 형식"""
    source_file = tmp_path / "doc.txt"
    source_file.write_text("Document with links.")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=MOCK_INGEST_OUTPUT):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="test-job-3")

    content = (wiki_path / "product-overview.md").read_text()
    assert "[[related-page]]" in content


@pytest.mark.asyncio
async def test_sc14_sources_frontmatter(tmp_path):
    """SC-14: sources frontmatter에 파일명만 있고 _sheska.yaml에 base_url"""
    source_file = tmp_path / "test.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=MOCK_INGEST_OUTPUT):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = "http://localhost:8000/api/sources"

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="test-job-4")

    content = (wiki_path / "product-overview.md").read_text()
    assert '"test.txt"' in content

    sheska_yaml = wiki_path / "_sheska.yaml"
    assert sheska_yaml.exists(), "_sheska.yaml 파일이 존재해야 함"
    yaml_content = sheska_yaml.read_text()
    assert "source_base_url" in yaml_content


@pytest.mark.asyncio
async def test_sc26_sheska_yaml_created_on_ingest(tmp_path):
    """SC-26: Ingest 완료 후 _sheska.yaml에 source_base_url 기록"""
    source_file = tmp_path / "doc.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=MOCK_INGEST_OUTPUT):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = "http://localhost:8000/api/sources"

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="sc26-test")

    sheska_yaml = wiki_path / "_sheska.yaml"
    assert sheska_yaml.exists()
    content = sheska_yaml.read_text()
    assert "source_base_url" in content
    assert "http://localhost:8000/api/sources" in content


@pytest.mark.asyncio
async def test_sc15_edit_request_queued(client: AsyncClient, tmp_path):
    """SC-15: 위키 페이지 Edit 요청 시 EDIT Job 등록 및 'queued' 응답"""
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    (wiki_path / "product-overview.md").write_text("---\ntype: concept\n---\n# Product")

    token = await get_token(client, "member@test.com", "memberpass")
    with patch("app.routes.wiki._wiki_path", return_value=wiki_path), \
         patch("app.routes.wiki.enqueue_job", new_callable=AsyncMock) as mock_enqueue:
        resp = await client.post(
            "/api/wiki/pages/product-overview.md/edit",
            json={"edit_text": "Add payment section"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"
    mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_sc16_edit_modifies_only_target_page(tmp_path):
    """SC-16: Edit flow가 지정 페이지만 수정"""
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    (wiki_path / "page-a.md").write_text("---\ntype: concept\ncreated: 2026-01-01\nlast_updated: 2026-01-01\ntags: []\nsources: []\n---\n# Page A\nOriginal A")
    (wiki_path / "page-b.md").write_text("---\ntype: concept\ncreated: 2026-01-01\nlast_updated: 2026-01-01\ntags: []\nsources: []\n---\n# Page B\nOriginal B")

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=MOCK_EDIT_OUTPUT):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")

        from app.services.pipeline import run_edit
        await run_edit("page-a.md", "Update title to include 'Updated'", db=None, job_id="edit-1")

    assert "Updated" in (wiki_path / "page-a.md").read_text()
    assert "Original B" in (wiki_path / "page-b.md").read_text()


@pytest.mark.asyncio
async def test_sc16b_index_updated_after_ingest(tmp_path):
    """SC-16-b: Ingest/Edit 완료 후 index.md 자동 갱신"""
    source_file = tmp_path / "test.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=MOCK_INGEST_OUTPUT):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="idx-test")

    index_content = (wiki_path / "index.md").read_text()
    assert "product-overview" in index_content
    assert "Last updated" in index_content


@pytest.mark.asyncio
async def test_ingest_fallback_when_no_file_markers(tmp_path):
    """Ollama 등 모델이 === FILE: === 마커 없이 frontmatter만 출력해도 단일 페이지로 저장"""
    source_file = tmp_path / "my-doc.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    fallback_output = (
        "---\n"
        "type: concept\n"
        "created: 2026-05-07 00:00:00\n"
        "last_updated: 2026-05-07 00:00:00\n"
        "tags: []\n"
        'sources:\n  - "my-doc.txt"\n'
        "---\n"
        "# My Doc\n\nLLM did not include FILE markers.\n"
    )

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=fallback_output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="fallback-1")

    assert (wiki_path / "my-doc.md").exists()


@pytest.mark.asyncio
async def test_ingest_raises_when_unparseable(tmp_path):
    """LLM 출력이 마커도 frontmatter도 없으면 명시적으로 raise → Job FAILED 처리"""
    source_file = tmp_path / "junk.txt"
    source_file.write_text("content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    junk_output = "Sorry, I cannot help with that request."

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=junk_output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        # v0.3: error message changed — covers both JSON Plan and legacy fallback failure
        with pytest.raises(ValueError, match="(neither valid JSON Plan|no parseable pages)"):
            await run_ingest(str(source_file), db=None, job_id="junk-1")


def test_parser_dangling_dashes_no_yaml():
    """LLM이 '---' 시작했지만 yaml 없이 본문으로 가는 케이스 (gemma 실측 패턴)"""
    from app.services import wiki_store
    output = "---\n# 감자 샐러드\n\n블로그 레시피를 기반으로 한 버전입니다.\n"
    pages = wiki_store.parse_llm_pages(
        output, fallback_stem="potato_recipe", source_filename="potato_recipe.md"
    )
    assert len(pages) == 1
    filename, content = next(iter(pages.items()))
    assert filename.endswith(".md")
    # 자동 frontmatter 삽입 확인
    assert content.startswith("---\n")
    assert "type: reference" in content
    assert 'sources:\n  - "potato_recipe.md"' in content
    # 본문 보존 확인
    assert "# 감자 샐러드" in content
    assert "블로그 레시피" in content
    # dangling --- 제거 확인 — 첫 frontmatter 블록 외에 다른 --- 없어야 함
    assert content.count("---") == 2


def test_parser_no_frontmatter_with_heading():
    """frontmatter 없이 # 제목으로 시작하면 자동 frontmatter 삽입 후 페이지 생성"""
    from app.services import wiki_store
    output = "# Product Overview\n\nA CLI tool for tasks."
    pages = wiki_store.parse_llm_pages(
        output, fallback_stem="spec", source_filename="spec.txt"
    )
    assert len(pages) == 1
    filename, content = next(iter(pages.items()))
    assert "product-overview" in filename.lower()
    assert content.startswith("---\n")
    assert "# Product Overview" in content
    assert 'sources:\n  - "spec.txt"' in content


def test_parser_pure_commentary_returns_empty():
    """평론형 응답은 빈 dict — 호출자가 raise"""
    from app.services import wiki_store
    output = "This is a well-structured recipe note. If you'd like, I can help you archive it."
    pages = wiki_store.parse_llm_pages(output, fallback_stem="recipe", source_filename="recipe.md")
    assert pages == {}


def test_parser_valid_frontmatter_preserved():
    """기존 동작: 정상 frontmatter는 그대로 보존 (회귀 방지)"""
    from app.services import wiki_store
    output = (
        "---\n"
        "type: concept\n"
        "created: 2026-05-07 00:00:00\n"
        "last_updated: 2026-05-07 00:00:00\n"
        "tags: [test]\n"
        "sources:\n  - \"x.md\"\n"
        "---\n"
        "# Title\n\nBody."
    )
    pages = wiki_store.parse_llm_pages(output, fallback_stem="x", source_filename="x.md")
    assert len(pages) == 1
    filename, content = next(iter(pages.items()))
    assert content == output  # 변형 없음
    # 자동 frontmatter 안 들어갔어야 — 'type: reference' 가 들어가면 안 됨
    assert "type: reference" not in content


@pytest.mark.asyncio
async def test_ingest_dangling_dashes_creates_page(tmp_path):
    """End-to-end: gemma의 실측 출력 패턴이 INGEST 흐름을 통과해 페이지로 저장됨"""
    source_file = tmp_path / "potato.md"
    source_file.write_text("recipe content")
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()

    gemma_output = (
        "---\n"
        "# 감자 샐러드\n\n"
        "블로그 레시피 기반.\n\n"
        "## 재료\n- 감자 4lb\n- 계란 6개\n"
    )

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=gemma_output):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")
        s.source_base_url = ""

        from app.services.pipeline import run_ingest
        await run_ingest(str(source_file), db=None, job_id="gemma-1")

    md_files = list(wiki_path.glob("*.md"))
    page_files = [p for p in md_files if p.name not in ("index.md", "log.md")]
    assert len(page_files) == 1
    page = page_files[0]
    text = page.read_text()
    assert text.startswith("---\n")
    assert "type: reference" in text
    assert "# 감자 샐러드" in text


@pytest.mark.asyncio
async def test_sc16c_log_contains_job_id_not_edit_text(tmp_path):
    """SC-16-c: log.md에 job_id + 결과만, 요청 전문 없음"""
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    (wiki_path / "page-a.md").write_text("---\ntype: concept\ncreated: 2026-01-01\nlast_updated: 2026-01-01\ntags: []\nsources: []\n---\n# A")

    secret_text = "VERY_SECRET_EDIT_REQUEST_DO_NOT_LOG"

    with patch("app.services.pipeline.get_settings") as mock_settings, \
         patch("app.services.pipeline.call_llm", new_callable=AsyncMock, return_value=MOCK_EDIT_OUTPUT):
        s = mock_settings.return_value
        s.wiki_store_path = str(wiki_path)
        s.prompts_path = str(tmp_path / "prompts")

        from app.services.pipeline import run_edit
        await run_edit("page-a.md", secret_text, db=None, job_id="secret-job-99")

    log_content = (wiki_path / "log.md").read_text()
    assert "secret-job-99" in log_content
    assert secret_text not in log_content
