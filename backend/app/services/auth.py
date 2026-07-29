from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.core.passwords import hash_password, verify_password
from app.core.config import settings
from app.core.tokens import decode_token, issue_token
from app.db import session_scope
from app.db_models import RevokedTokenTable, UserTable
from app.models import (
    AuthenticatedUser,
    PasswordChangeRequest,
    TokenResponse,
    UserCreate,
    UserRecord,
    UserRole,
    UserUpdate,
    utc_now,
)


class AuthService:
    def _token_bundle(self, username: str, role: UserRole) -> TokenResponse:
        access_token = issue_token(
            subject=username,
            role=role,
            token_kind="access",
            expires_delta=timedelta(minutes=settings.auth_token_expiry_minutes),
        )
        refresh_token = issue_token(
            subject=username,
            role=role,
            token_kind="refresh",
            expires_delta=timedelta(minutes=settings.auth_refresh_expiry_minutes),
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            role=role,
            expires_in_seconds=settings.auth_token_expiry_minutes * 60,
        )

    def _is_revoked(self, session, payload: dict) -> bool:
        jti = payload.get("jti")
        if not jti:
            return False
        self._prune_expired_revocations(session)
        return session.query(RevokedTokenTable.jti).filter(RevokedTokenTable.jti == jti).first() is not None

    def _prune_expired_revocations(self, session) -> None:
        session.query(RevokedTokenTable).filter(RevokedTokenTable.expires_at < utc_now()).delete()

    def _revoke_payload(self, session, payload: dict) -> None:
        jti = payload.get("jti")
        if not jti:
            return
        exists = session.query(RevokedTokenTable.jti).filter(RevokedTokenTable.jti == jti).first()
        if exists:
            return
        session.add(
            RevokedTokenTable(
                jti=jti,
                username=payload["sub"],
                token_kind=payload["kind"],
                expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
                revoked_at=utc_now(),
            )
        )

    def _active_admin_count(self, session) -> int:
        return (
            session.query(UserTable)
            .filter(UserTable.role == UserRole.ADMIN.value, UserTable.active.is_(True))
            .count()
        )

    def ensure_default_users(self) -> None:
        with session_scope() as session:
            existing = session.query(UserTable.user_id).first()
            if existing:
                return
            for username, password, role in (
                ("admin", "prometheus-admin", UserRole.ADMIN),
                ("operator", "prometheus-operator", UserRole.OPERATOR),
                ("viewer", "prometheus-viewer", UserRole.VIEWER),
            ):
                now = utc_now()
                session.add(
                    UserTable(
                        user_id=f"user-{username}",
                        username=username,
                        password_hash=hash_password(password),
                        role=role.value,
                        active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )

    def login(self, username: str, password: str) -> TokenResponse:
        with session_scope() as session:
            user = session.query(UserTable).filter(UserTable.username == username).one_or_none()
            if not user or not user.active or not verify_password(password, user.password_hash):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password.")
            role = UserRole(user.role)
        return self._token_bundle(username=username, role=role)

    def refresh(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(refresh_token, expected_kind="refresh")
        username = payload["sub"]
        with session_scope() as session:
            if self._is_revoked(session, payload):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been revoked.")
            user = session.query(UserTable).filter(UserTable.username == username).one_or_none()
            if not user or not user.active:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown refresh token subject.")
            role = UserRole(user.role)
            self._revoke_payload(session, payload)
        return self._token_bundle(username=username, role=role)

    def authenticate_bearer(self, token: str) -> AuthenticatedUser:
        payload = decode_token(token, expected_kind="access")
        username = payload["sub"]
        with session_scope() as session:
            if self._is_revoked(session, payload):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token has been revoked.")
            user = session.query(UserTable).filter(UserTable.username == username).one_or_none()
            if not user or not user.active:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or missing user.")
            return AuthenticatedUser(username=user.username, role=UserRole(user.role))

    def list_users(self) -> list[UserRecord]:
        with session_scope() as session:
            users = session.query(UserTable).order_by(UserTable.username.asc()).all()
            return [
                UserRecord(
                    user_id=user.user_id,
                    username=user.username,
                    role=UserRole(user.role),
                    active=user.active,
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )
                for user in users
            ]

    def create_user(self, payload: UserCreate) -> UserRecord:
        with session_scope() as session:
            existing = session.query(UserTable).filter(UserTable.username == payload.username).one_or_none()
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists.")
            now = utc_now()
            user = UserTable(
                user_id=f"user-{payload.username}-{int(now.timestamp())}",
                username=payload.username,
                password_hash=hash_password(payload.password),
                role=payload.role.value,
                active=payload.active,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            session.flush()
            return UserRecord(
                user_id=user.user_id,
                username=user.username,
                role=UserRole(user.role),
                active=user.active,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )

    def update_user(self, user_id: str, payload: UserUpdate) -> UserRecord:
        with session_scope() as session:
            user = session.query(UserTable).filter(UserTable.user_id == user_id).one_or_none()
            if not user:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
            prior_role = UserRole(user.role)
            prior_active = user.active
            if payload.role is not None:
                user.role = payload.role.value
            if payload.active is not None:
                user.active = payload.active
            if payload.password:
                user.password_hash = hash_password(payload.password)
            if (
                prior_role == UserRole.ADMIN
                and prior_active
                and (user.role != UserRole.ADMIN.value or not user.active)
                and self._active_admin_count(session) <= 1
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Prometheus requires at least one active admin user.",
                )
            user.updated_at = utc_now()
            session.flush()
            return UserRecord(
                user_id=user.user_id,
                username=user.username,
                role=UserRole(user.role),
                active=user.active,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )

    def change_password(self, current_user: AuthenticatedUser, payload: PasswordChangeRequest) -> None:
        with session_scope() as session:
            user = session.query(UserTable).filter(UserTable.username == current_user.username).one_or_none()
            if not user or not user.active:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
            if not verify_password(payload.current_password, user.password_hash):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect.")
            if verify_password(payload.new_password, user.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="New password must be different from the current password.",
                )
            user.password_hash = hash_password(payload.new_password)
            user.updated_at = utc_now()

    def logout(self, access_token: str, refresh_token: str | None = None) -> None:
        access_payload = decode_token(access_token, expected_kind="access")
        with session_scope() as session:
            if not self._is_revoked(session, access_payload):
                self._revoke_payload(session, access_payload)
            if refresh_token:
                refresh_payload = decode_token(refresh_token, expected_kind="refresh")
                if refresh_payload["sub"] != access_payload["sub"]:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Refresh token does not belong to the current user.",
                    )
                self._revoke_payload(session, refresh_payload)


auth_service = AuthService()
