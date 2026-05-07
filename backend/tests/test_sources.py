from __future__ import annotations
import io
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient
from .conftest import get_token


@pytest.mark.asyncio
async def test_sc6_admin_can_upload_pdf(client: AsyncClient, tmp_path):
    """SC-6: Admin이 PDF 파일 업로드 성공"""
    token = await get_token(client, "admin@test.com", "adminpass")
    with patch("app.routes.sources._source_store", return_value=tmp_path), \
         patch("app.services.worker.enqueue_job", new_callable=AsyncMock):
        resp = await client.post(
            "/api/sources/",
            files={"file": ("test.pdf", b"%PDF-1.4 test", "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["filename"] == "test.pdf"
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_sc6_admin_can_upload_txt(client: AsyncClient, tmp_path):
    """SC-6: Admin이 TXT 파일 업로드 성공"""
    token = await get_token(client, "admin@test.com", "adminpass")
    with patch("app.routes.sources._source_store", return_value=tmp_path), \
         patch("app.services.worker.enqueue_job", new_callable=AsyncMock):
        resp = await client.post(
            "/api/sources/",
            files={"file": ("doc.txt", b"Hello world", "text/plain")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_sc7_disallowed_extension_rejected(client: AsyncClient, tmp_path):
    """SC-7: 허용 외 확장자(.docx) 업로드 거부"""
    token = await get_token(client, "admin@test.com", "adminpass")
    with patch("app.routes.sources._source_store", return_value=tmp_path):
        resp = await client.post(
            "/api/sources/",
            files={"file": ("doc.docx", b"binary", "application/octet-stream")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400
    assert "not allowed" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_sc7_xlsx_rejected(client: AsyncClient, tmp_path):
    """SC-7: xlsx 거부"""
    token = await get_token(client, "admin@test.com", "adminpass")
    with patch("app.routes.sources._source_store", return_value=tmp_path):
        resp = await client.post(
            "/api/sources/",
            files={"file": ("data.xlsx", b"binary", "application/octet-stream")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_sc8_same_filename_replaces(client: AsyncClient, tmp_path):
    """SC-8: 동일 파일명으로 재업로드 시 교체 및 re-ingest"""
    token = await get_token(client, "admin@test.com", "adminpass")
    (tmp_path / "spec.txt").write_text("v1")
    with patch("app.routes.sources._source_store", return_value=tmp_path), \
         patch("app.services.worker.enqueue_job", new_callable=AsyncMock):
        resp = await client.post(
            "/api/sources/",
            files={"file": ("spec.txt", b"v2 content", "text/plain")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 202
    assert (tmp_path / "spec.txt").read_text() == "v2 content"


@pytest.mark.asyncio
async def test_sc10_member_cannot_upload(client: AsyncClient, tmp_path):
    """SC-10: Member 업로드 불가 → 403"""
    token = await get_token(client, "member@test.com", "memberpass")
    with patch("app.routes.sources._source_store", return_value=tmp_path):
        resp = await client.post(
            "/api/sources/",
            files={"file": ("doc.txt", b"content", "text/plain")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sc21_member_can_list_sources(client: AsyncClient, tmp_path):
    """SC-21: Member도 원본 파일 목록 조회 가능"""
    (tmp_path / "a.txt").write_text("hello")
    token = await get_token(client, "member@test.com", "memberpass")
    with patch("app.routes.sources._source_store", return_value=tmp_path):
        resp = await client.get("/api/sources/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert any(f["filename"] == "a.txt" for f in resp.json())


@pytest.mark.asyncio
async def test_sc22_member_can_download_source(client: AsyncClient, tmp_path):
    """SC-22: Member 원본 파일 다운로드 가능"""
    (tmp_path / "doc.txt").write_text("content")
    token = await get_token(client, "member@test.com", "memberpass")
    with patch("app.routes.sources._source_store", return_value=tmp_path):
        resp = await client.get("/api/sources/doc.txt", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_sc23_unauth_source_returns_401(client: AsyncClient, tmp_path):
    """SC-23: 비인증 /api/sources/{filename} → 401"""
    with patch("app.routes.sources._source_store", return_value=tmp_path):
        resp = await client.get("/api/sources/doc.txt")
    assert resp.status_code == 401
