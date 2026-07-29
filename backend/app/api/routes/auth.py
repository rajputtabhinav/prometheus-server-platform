from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.core.security import get_current_user, require_role
from app.models import (
    AuthenticatedUser,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    PasswordChangeRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserRecord,
    UserRole,
    UserUpdate,
)
from app.services.auth import auth_service


router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    return auth_service.login(payload.username, payload.password)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest) -> TokenResponse:
    return auth_service.refresh(payload.refresh_token)


@router.post("/logout", response_model=MessageResponse)
def logout(
    payload: LogoutRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    authorization: str | None = Header(default=None),
) -> MessageResponse:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required.")
    auth_service.logout(authorization.split(" ", 1)[1].strip(), payload.refresh_token)
    return MessageResponse(message=f"Signed out {current_user.username}.")


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: PasswordChangeRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> MessageResponse:
    auth_service.change_password(current_user, payload)
    return MessageResponse(message="Password updated successfully.")


@router.get("/users", response_model=list[UserRecord])
def list_users(_: UserRole = Depends(require_role(UserRole.ADMIN))) -> list[UserRecord]:
    return auth_service.list_users()


@router.post("/users", response_model=UserRecord)
def create_user(payload: UserCreate, _: UserRole = Depends(require_role(UserRole.ADMIN))) -> UserRecord:
    return auth_service.create_user(payload)


@router.patch("/users/{user_id}", response_model=UserRecord)
def update_user(
    user_id: str,
    payload: UserUpdate,
    _: UserRole = Depends(require_role(UserRole.ADMIN)),
) -> UserRecord:
    return auth_service.update_user(user_id, payload)
