import pytest
from httpx import AsyncClient
from .conftest import get_token


@pytest.mark.asyncio
async def test_sc1_login_success(client: AsyncClient):
    """SC-1: 이메일+패스워드 로그인 성공 → JWT 발급"""
    resp = await client.post("/api/auth/token", data={"username": "admin@test.com", "password": "adminpass"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_sc1_login_wrong_password(client: AsyncClient):
    """SC-1: 잘못된 패스워드 → 401"""
    resp = await client.post("/api/auth/token", data={"username": "admin@test.com", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sc2_unauth_access_blocked(client: AsyncClient):
    """SC-2: 미인증 접근 차단 → 401"""
    resp = await client.get("/api/users/")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_sc3_admin_can_list_users(client: AsyncClient):
    """SC-3: Admin 사용자 목록 조회 가능"""
    token = await get_token(client, "admin@test.com", "adminpass")
    resp = await client.get("/api/users/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


@pytest.mark.asyncio
async def test_sc3_admin_create_user(client: AsyncClient):
    """SC-3: Admin 신규 계정 생성 가능"""
    token = await get_token(client, "admin@test.com", "adminpass")
    resp = await client.post(
        "/api/users/",
        json={"email": "new@test.com", "password": "newpass", "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "new@test.com"
    assert resp.json()["role"] == "member"


@pytest.mark.asyncio
async def test_sc4_member_cannot_access_users(client: AsyncClient):
    """SC-4: Member는 사용자 관리 불가 → 403"""
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.get("/api/users/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sc4_member_cannot_create_user(client: AsyncClient):
    """SC-4: Member는 계정 생성 불가 → 403"""
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.post(
        "/api/users/",
        json={"email": "another@test.com", "password": "pass", "role": "member"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sc5_password_change(client: AsyncClient):
    """SC-5: 비밀번호 변경"""
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.post(
        "/api/auth/change-password",
        json={"current_password": "memberpass", "new_password": "newpass123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    # Old token may still work (JWT not invalidated in MVP) but new password should work
    resp2 = await client.post("/api/auth/token", data={"username": "member@test.com", "password": "newpass123"})
    assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_jobs_tab_member_sees_own_jobs(client: AsyncClient):
    """SC-17-a: Member는 본인 Job만 조회"""
    token = await get_token(client, "member@test.com", "memberpass")
    resp = await client.get("/api/jobs/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_jobs_tab_admin_sees_all_jobs(client: AsyncClient):
    """SC-17-b: Admin은 전체 Job 조회"""
    token = await get_token(client, "admin@test.com", "adminpass")
    resp = await client.get("/api/jobs/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
