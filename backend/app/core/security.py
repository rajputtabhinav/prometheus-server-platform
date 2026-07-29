from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, status

from app.models import AuthenticatedUser, UserRole
from app.services.auth import auth_service


ROLE_ORDER = {
    UserRole.VIEWER: 0,
    UserRole.OPERATOR: 1,
    UserRole.ADMIN: 2,
}


def get_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required.")
    token = authorization.split(" ", 1)[1].strip()
    return auth_service.authenticate_bearer(token)


def require_role(required_role: UserRole) -> Callable[[AuthenticatedUser], UserRole]:
    def dependency(user: AuthenticatedUser = Depends(get_current_user)) -> UserRole:
        if ROLE_ORDER[user.role] < ROLE_ORDER[required_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{required_role.value} role required for this operation.",
            )
        return user.role

    return dependency
