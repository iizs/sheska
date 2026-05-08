"""Sheska 환경 초기화 스크립트.

기능:
  - DB 스키마 생성 (없으면)
  - Source store / Wiki store 디렉토리 + git 초기화
  - Admin 계정 생성

사용법 (interactive):
    python scripts/init_env.py

옵션:
    --reset                 모든 데이터 삭제 후 재생성 (DB, source store, wiki store)
    --admin-email EMAIL     Admin 이메일 (interactive default)
    --admin-password PWD    Admin 패스워드 (interactive default — 보안상 비권장)
    --non-interactive       Prompt 없이 환경변수/인자만 사용
    --yes                   --reset 시 확인 prompt 스킵 (CI 자동화용)

환경변수 (interactive default 또는 non-interactive 입력):
    INITIAL_ADMIN_EMAIL
    INITIAL_ADMIN_PASSWORD
"""
from __future__ import annotations
import argparse
import asyncio
import getpass
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from app.db import init_db_globals, create_tables  # noqa: E402
from app.models.user import User, Role  # noqa: E402
from app.services.auth_service import hash_password  # noqa: E402
from app.services import wiki_store  # noqa: E402
from app.config import get_settings  # noqa: E402


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 8


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialize Sheska environment")
    p.add_argument("--reset", action="store_true", help="Wipe DB and stores before init")
    p.add_argument("--admin-email", default=None)
    p.add_argument("--admin-password", default=None)
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--yes", action="store_true", help="Skip --reset confirmation")
    return p.parse_args()


def prompt(label: str, default: str | None = None, secret: bool = False) -> str:
    if secret:
        while True:
            value = getpass.getpass(f"{label}: ")
            confirm = getpass.getpass(f"{label} (confirm): ")
            if value == confirm:
                return value
            print("  Passwords do not match. Try again.")
    suffix = f" [{default}]" if default else ""
    while True:
        raw = input(f"{label}{suffix}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        print("  Value required.")


def resolve_admin_credentials(args: argparse.Namespace) -> tuple[str, str]:
    env_email = os.environ.get("INITIAL_ADMIN_EMAIL")
    env_password = os.environ.get("INITIAL_ADMIN_PASSWORD")

    email_default = args.admin_email or env_email
    password_default = args.admin_password or env_password

    if args.non_interactive:
        if not email_default:
            sys.exit("Error: --non-interactive requires --admin-email or INITIAL_ADMIN_EMAIL")
        if not password_default:
            sys.exit("Error: --non-interactive requires --admin-password or INITIAL_ADMIN_PASSWORD")
        email, password = email_default, password_default
    else:
        email = prompt("Admin email", default=email_default)
        if password_default:
            print("Admin password (using environment/CLI value)")
            password = password_default
        else:
            password = prompt("Admin password", secret=True)

    if not EMAIL_RE.match(email):
        sys.exit(f"Error: invalid email format: {email}")
    if len(password) < MIN_PASSWORD_LEN:
        sys.exit(f"Error: password must be at least {MIN_PASSWORD_LEN} characters")

    return email, password


def confirm_reset(yes: bool) -> bool:
    if yes:
        return True
    print("⚠️  --reset will DELETE the database, source-store, and wiki-store directories.")
    answer = input("Type 'yes' to confirm: ").strip()
    return answer == "yes"


def wipe_environment() -> None:
    settings = get_settings()
    backend_root = Path(__file__).resolve().parent.parent

    db_url = settings.database_url
    if db_url.startswith("sqlite"):
        db_path_str = db_url.split("///", 1)[-1]
        db_path = Path(db_path_str)
        if not db_path.is_absolute():
            db_path = backend_root / db_path
        if db_path.exists():
            db_path.unlink()
            print(f"  removed DB: {db_path}")

    for label, raw_path in (("source-store", settings.source_store_path),
                            ("wiki-store", settings.wiki_store_path)):
        path = Path(raw_path)
        if not path.is_absolute():
            path = backend_root / path
        if path.exists():
            shutil.rmtree(path)
            print(f"  removed {label}: {path}")


async def init_admin(email: str, password: str) -> None:
    init_db_globals()
    await create_tables()

    from app.db import _session_factory as factory
    async with factory() as session:
        existing = await session.scalar(select(User).where(User.email == email))
        if existing:
            print(f"User {email} already exists (role={existing.role.value}). Skipping admin create (safe).")
            return
        user = User(
            email=email,
            hashed_password=hash_password(password),
            role=Role.admin,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        print(f"Admin created: {email}")


def init_stores() -> None:
    settings = get_settings()
    backend_root = Path(__file__).resolve().parent.parent

    for label, raw_path in (("source-store", settings.source_store_path),
                            ("wiki-store", settings.wiki_store_path)):
        path = Path(raw_path)
        if not path.is_absolute():
            path = backend_root / path
        path.mkdir(parents=True, exist_ok=True)
        print(f"  ensured {label}: {path}")

    wiki_path = Path(settings.wiki_store_path)
    if not wiki_path.is_absolute():
        wiki_path = backend_root / wiki_path
    wiki_store._get_repo(wiki_path)
    wiki_store.ensure_sheska_yaml(wiki_path, settings.source_base_url)
    print(f"  initialized git wiki at: {wiki_path}")


async def main() -> None:
    args = parse_args()

    if args.reset:
        if not confirm_reset(args.yes):
            print("Reset cancelled.")
            sys.exit(1)
        print("Resetting environment...")
        wipe_environment()

    print("Initializing stores...")
    init_stores()

    print("Configuring admin credentials...")
    email, password = resolve_admin_credentials(args)

    print("Creating admin account...")
    await init_admin(email, password)

    print("Done. Sheska environment initialized.")


if __name__ == "__main__":
    asyncio.run(main())
