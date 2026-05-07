from __future__ import annotations
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, EmailStr
from ..db import get_db
from ..models.user import User, Role
from ..services.auth_service import hash_password, require_admin, get_current_user

router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: Role = Role.member


class UserResponse(BaseModel):
    id: int
    email: str
    role: Role
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RoleUpdate(BaseModel):
    role: Role


class ActiveUpdate(BaseModel):
    is_active: bool


async def _active_admin_count(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(User.id)).where(User.role == Role.admin, User.is_active == True)
    )
    return result.scalar_one()


def _ensure_not_self(actor: User, target_id: int):
    if actor.id == target_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot modify your own role or active status",
        )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/", response_model=List[UserResponse])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User))
    return result.scalars().all()


@router.post("/", response_model=UserResponse, status_code=201)
async def create_user(
    body: UserCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}/role", response_model=UserResponse)
async def update_role(
    user_id: int,
    body: RoleUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _ensure_not_self(admin, user_id)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if (
        user.role == Role.admin
        and user.is_active
        and body.role != Role.admin
        and await _active_admin_count(db) <= 1
    ):
        raise HTTPException(
            status_code=400,
            detail="Cannot demote the last active admin",
        )

    user.role = body.role
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}/active", response_model=UserResponse)
async def update_active(
    user_id: int,
    body: ActiveUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _ensure_not_self(admin, user_id)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if (
        user.role == Role.admin
        and user.is_active
        and body.is_active is False
        and await _active_admin_count(db) <= 1
    ):
        raise HTTPException(
            status_code=400,
            detail="Cannot deactivate the last active admin",
        )

    user.is_active = body.is_active
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
async def deactivate_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    _ensure_not_self(admin, user_id)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if (
        user.role == Role.admin
        and user.is_active
        and await _active_admin_count(db) <= 1
    ):
        raise HTTPException(
            status_code=400,
            detail="Cannot deactivate the last active admin",
        )
    user.is_active = False
    db.add(user)
    await db.commit()
