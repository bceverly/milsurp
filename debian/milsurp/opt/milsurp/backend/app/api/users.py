"""User administration. Every route here is admin-only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from ..deps import AdminUser, AppConfig, DbSession
from ..models import EmailPreference, User, UserRole
from ..schemas import UserCreate, UserOut, UserUpdate
from ..security import PasswordPolicyError, hash_password, validate_password

router = APIRouter(prefix="/users", tags=["users"])


def _admin_count(session: DbSession) -> int:
    return session.execute(
        select(func.count(User.id)).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    ).scalar_one()


@router.get("", response_model=list[UserOut])
def list_users(_admin: AdminUser, session: DbSession) -> list[UserOut]:
    users = session.execute(select(User).order_by(User.username)).scalars().all()
    return [UserOut.model_validate(user) for user in users]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate, _admin: AdminUser, session: DbSession, config: AppConfig
) -> UserOut:
    try:
        validate_password(payload.password, config)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    existing = (
        session.execute(
            select(User).where(
                (User.username == payload.username) | (User.email == str(payload.email))
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        field = "username" if existing.username == payload.username else "email address"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That {field} is already in use.",
        )

    user = User(
        username=payload.username,
        email=str(payload.email),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password, config),
        role=UserRole(payload.role),
        is_active=payload.is_active,
    )
    session.add(user)
    session.flush()
    # Every user gets a preferences row up front, so the settings page never
    # has to special-case its absence.
    session.add(EmailPreference(user_id=user.id))
    session.commit()
    return UserOut.model_validate(user)


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, _admin: AdminUser, session: DbSession) -> UserOut:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user.")
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    _admin: AdminUser,
    session: DbSession,
    config: AppConfig,
) -> UserOut:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user.")

    # Guard against an admin locking everyone out of administration. Both
    # checks look at the *last* remaining active admin, including self-edits.
    removing_admin = (
        payload.role is not None
        and payload.role != UserRole.ADMIN.value
        and user.role == UserRole.ADMIN
    )
    deactivating = payload.is_active is False and user.is_active
    if (
        (removing_admin or deactivating)
        and user.role == UserRole.ADMIN
        and user.is_active
        and _admin_count(session) <= 1
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This is the only active administrator; promote another first.",
        )

    if payload.email is not None and str(payload.email) != user.email:
        clash = (
            session.execute(
                select(User).where(User.email == str(payload.email), User.id != user.id)
            )
            .scalars()
            .first()
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That email address is already in use.",
            )
        user.email = str(payload.email)

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.role is not None:
        user.role = UserRole(payload.role)
    if payload.is_active is not None:
        user.is_active = payload.is_active

    if payload.password is not None:
        try:
            validate_password(payload.password, config)
        except PasswordPolicyError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        user.password_hash = hash_password(payload.password, config)
        # An admin reset must sign the user out everywhere.
        user.token_version += 1

    session.commit()
    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, admin: AdminUser, session: DbSession) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user.")
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot delete your own account.",
        )
    # Only an *active* admin counts toward the floor. Deleting an admin who is
    # already disabled cannot leave the system without an administrator, so
    # blocking that was wrong.
    if user.role == UserRole.ADMIN and user.is_active and _admin_count(session) <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This is the only active administrator; promote another first.",
        )
    session.delete(user)
    session.commit()
