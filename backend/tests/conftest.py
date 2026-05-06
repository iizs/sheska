import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from app.db import Base, get_db
from app.main import app
from app.models.user import User, Role
from app.services.auth_service import hash_password


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    # Seed admin user
    admin = User(
        email="admin@test.com",
        hashed_password=hash_password("adminpass"),
        role=Role.admin,
    )
    member = User(
        email="member@test.com",
        hashed_password=hash_password("memberpass"),
        role=Role.member,
    )
    db_session.add_all([admin, member])
    await db_session.commit()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


async def get_token(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post("/api/auth/token", data={"username": email, "password": password})
    return resp.json()["access_token"]
