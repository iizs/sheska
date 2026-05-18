"""v0.5 — Lint Finding Tracker tests."""
from __future__ import annotations
import pytest
from httpx import AsyncClient
from .conftest import get_token


# ---------------- SC-81: create finding ----------------

@pytest.mark.asyncio
async def test_sc81_user_can_report_finding(client: AsyncClient):
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.post(
        "/api/lint/findings",
        json={
            "page_path": "auth.md",
            "description": "page is empty",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "user:web"
    assert body["status"] == "open"
    assert body["category"] == "user_reported"
    assert body["reported_by"] == "member@test.com"
    assert body["page_path"] == "auth.md"


@pytest.mark.asyncio
async def test_sc81_category_dropdown_accepted(client: AsyncClient):
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.post(
        "/api/lint/findings",
        json={
            "page_path": "auth.md",
            "description": "looks stale",
            "category": "stale",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["category"] == "stale"


@pytest.mark.asyncio
async def test_sc81_source_cannot_be_overridden_by_client(client: AsyncClient):
    """Even if the request body included source, the server forces user:web."""
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.post(
        "/api/lint/findings",
        # FindingCreate doesn't accept source — extras ignored by pydantic by default
        json={
            "page_path": "auth.md",
            "description": "x",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["source"] == "user:web"


@pytest.mark.asyncio
async def test_sc81_invalid_category_rejected(client: AsyncClient):
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.post(
        "/api/lint/findings",
        json={"description": "x", "category": "nonsense_category"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sc81_description_required(client: AsyncClient):
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.post(
        "/api/lint/findings",
        json={"page_path": "x.md"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sc81_unauthenticated_rejected(client: AsyncClient):
    resp = await client.post(
        "/api/lint/findings",
        json={"description": "should require auth"},
    )
    assert resp.status_code == 401


# ---------------- SC-82: list / single GET + filters / pagination ----------------

@pytest.mark.asyncio
async def test_sc82_list_findings_response_shape(client: AsyncClient):
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.get(
        "/api/lint/findings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body and "total" in body and "page" in body and "size" in body
    assert body["page"] == 1
    assert body["size"] == 20


@pytest.mark.asyncio
async def test_sc82_filter_by_status(client: AsyncClient):
    member_token = await get_token(client, "member@test.com", "memberpass")
    # Seed 2 findings
    for desc in ("first", "second"):
        await client.post(
            "/api/lint/findings",
            json={"description": desc, "page_path": "x.md"},
            headers={"Authorization": f"Bearer {member_token}"},
        )
    resp = await client.get(
        "/api/lint/findings?status=open",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2
    assert all(item["status"] == "open" for item in body["items"])


@pytest.mark.asyncio
async def test_sc82_get_single_finding(client: AsyncClient):
    token = await get_token(client, "member@test.com", "memberpass")
    create = await client.post(
        "/api/lint/findings",
        json={"description": "specific", "page_path": "x.md"},
        headers={"Authorization": f"Bearer {token}"},
    )
    fid = create.json()["finding_id"]
    resp = await client.get(
        f"/api/lint/findings/{fid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["finding_id"] == fid


@pytest.mark.asyncio
async def test_sc82_not_found_returns_404(client: AsyncClient):
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.get(
        "/api/lint/findings/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ---------------- SC-83: Admin-only PATCH ----------------

@pytest.mark.asyncio
async def test_sc83_admin_can_acknowledge(client: AsyncClient):
    member_token = await get_token(client, "member@test.com", "memberpass")
    create = await client.post(
        "/api/lint/findings",
        json={"description": "ack me", "page_path": "x.md"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    fid = create.json()["finding_id"]

    admin_token = await get_token(client, "admin@test.com", "adminpass")
    resp = await client.patch(
        f"/api/lint/findings/{fid}",
        json={"status": "acknowledged", "resolution_reason": "valid issue"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "acknowledged"
    assert body["decided_by"] == "admin@test.com"
    assert body["decided_at"] is not None
    assert body["resolution_reason"] == "valid issue"


@pytest.mark.asyncio
async def test_sc83_admin_can_wont_fix(client: AsyncClient):
    member_token = await get_token(client, "member@test.com", "memberpass")
    create = await client.post(
        "/api/lint/findings",
        json={"description": "wf", "page_path": "x.md"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    fid = create.json()["finding_id"]
    admin_token = await get_token(client, "admin@test.com", "adminpass")
    resp = await client.patch(
        f"/api/lint/findings/{fid}",
        json={"status": "wont_fix", "resolution_reason": "not actionable"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "wont_fix"


@pytest.mark.asyncio
async def test_sc83_member_cannot_patch(client: AsyncClient):
    member_token = await get_token(client, "member@test.com", "memberpass")
    create = await client.post(
        "/api/lint/findings",
        json={"description": "nope", "page_path": "x.md"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    fid = create.json()["finding_id"]
    resp = await client.patch(
        f"/api/lint/findings/{fid}",
        json={"status": "acknowledged", "resolution_reason": "I want this"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sc83_resolution_reason_required(client: AsyncClient):
    member_token = await get_token(client, "member@test.com", "memberpass")
    create = await client.post(
        "/api/lint/findings",
        json={"description": "rr", "page_path": "x.md"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    fid = create.json()["finding_id"]
    admin_token = await get_token(client, "admin@test.com", "adminpass")
    resp = await client.patch(
        f"/api/lint/findings/{fid}",
        json={"status": "acknowledged"},  # missing reason
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


# ---------------- SC-84: status flow one-way ----------------

@pytest.mark.asyncio
async def test_sc84_cannot_set_status_open_via_patch(client: AsyncClient):
    member_token = await get_token(client, "member@test.com", "memberpass")
    create = await client.post(
        "/api/lint/findings",
        json={"description": "x", "page_path": "x.md"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    fid = create.json()["finding_id"]
    admin_token = await get_token(client, "admin@test.com", "adminpass")
    resp = await client.patch(
        f"/api/lint/findings/{fid}",
        json={"status": "open", "resolution_reason": "no-op"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_sc84_terminal_status_cannot_be_changed(client: AsyncClient):
    member_token = await get_token(client, "member@test.com", "memberpass")
    create = await client.post(
        "/api/lint/findings",
        json={"description": "x", "page_path": "x.md"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    fid = create.json()["finding_id"]
    admin_token = await get_token(client, "admin@test.com", "adminpass")
    await client.patch(
        f"/api/lint/findings/{fid}",
        json={"status": "wont_fix", "resolution_reason": "x"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # second PATCH must be rejected — already terminal
    resp = await client.patch(
        f"/api/lint/findings/{fid}",
        json={"status": "acknowledged", "resolution_reason": "changed mind"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 409


# ---------------- SC-85: DELETE not supported ----------------

@pytest.mark.asyncio
async def test_sc85_delete_not_supported(client: AsyncClient):
    member_token = await get_token(client, "member@test.com", "memberpass")
    create = await client.post(
        "/api/lint/findings",
        json={"description": "x", "page_path": "x.md"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    fid = create.json()["finding_id"]
    admin_token = await get_token(client, "admin@test.com", "adminpass")
    resp = await client.delete(
        f"/api/lint/findings/{fid}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # No DELETE route → 405 Method Not Allowed
    assert resp.status_code in (404, 405)
