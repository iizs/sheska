from __future__ import annotations
import io
import zipfile
import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient
from .conftest import get_token


@pytest.mark.asyncio
async def test_sc17a_member_sees_own_jobs_only(client: AsyncClient):
    """SC-17-a: Member는 본인 Job만 조회 (페이징 응답)"""
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.get("/api/jobs/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["items"], list)
    assert "total" in body and "page" in body and "size" in body


@pytest.mark.asyncio
async def test_sc17b_admin_sees_all_jobs(client: AsyncClient):
    """SC-17-b: Admin은 전체 Job 조회 가능 (페이징 응답)"""
    token = await get_token(client, "admin@test.com", "adminpass")
    resp = await client.get("/api/jobs/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_sc17b_member_cannot_see_other_jobs(client: AsyncClient, tmp_path):
    """SC-17-b: Member는 타인 Job에 직접 접근 불가 (403)"""
    admin_token = await get_token(client, "admin@test.com", "adminpass")
    member_token = await get_token(client, "member@test.com", "memberpass")

    with patch("app.routes.sources._source_store", return_value=tmp_path), \
         patch("app.routes.sources.enqueue_job", new_callable=AsyncMock):
        resp = await client.post(
            "/api/sources/",
            files={"file": ("test.txt", b"content", "text/plain")},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    resp = await client.get(
        f"/api/jobs/{job_id}",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sc25_zip_download(client: AsyncClient, tmp_path):
    """SC-25: 위키 zip 다운로드 — _sheska.yaml 포함"""
    wiki_path = tmp_path / "wiki"
    wiki_path.mkdir()
    (wiki_path / "page-a.md").write_text("# Page A\ncontent")
    (wiki_path / "_sheska.yaml").write_text('source_base_url: "http://localhost:8000/api/sources"\n')

    token = await get_token(client, "member@test.com", "memberpass")
    with patch("app.routes.wiki._wiki_path", return_value=wiki_path):
        resp = await client.get(
            "/api/wiki/zip",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert "page-a.md" in names
    assert "_sheska.yaml" in names

    yaml_content = zf.read("_sheska.yaml").decode()
    assert "source_base_url" in yaml_content


@pytest.mark.asyncio
async def test_sc25_zip_requires_auth(client: AsyncClient):
    """SC-25: 비인증 zip 다운로드 → 401"""
    resp = await client.get("/api/wiki/zip")
    assert resp.status_code == 401
