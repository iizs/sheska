"""
초기 Admin 계정 시딩 스크립트.

사용법:
    cd backend
    source .venv/bin/activate
    python scripts/seed_admin.py admin@example.com mypassword
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.db import init_db_globals, create_tables, _session_factory
from app.models.user import User, Role
from app.services.auth_service import hash_password


async def seed_admin(email: str, password: str) -> None:
    init_db_globals()
    await create_tables()

    from app.db import _session_factory as factory
    async with factory() as session:
        existing = await session.scalar(select(User).where(User.email == email))
        if existing:
            print(f"이미 존재하는 계정: {email} (role={existing.role.value})")
            if existing.role != Role.admin:
                existing.role = Role.admin
                await session.commit()
                print(f"  → admin으로 승격 완료")
            return

        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=Role.admin,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        print(f"Admin 계정 생성 완료: {email}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python scripts/seed_admin.py <email> <password>")
        sys.exit(1)

    asyncio.run(seed_admin(sys.argv[1], sys.argv[2]))
