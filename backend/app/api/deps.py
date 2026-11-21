import uuid
from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User
from app.models.enums import Role

bearer_scheme = HTTPBearer(auto_error=False, description="JWT from POST /api/v1/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise AuthenticationError("Missing bearer token")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise AuthenticationError("Invalid or expired token") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid or expired token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[[User], User]:
    allowed = frozenset(roles)

    def checker(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionDeniedError(
                "Your role is not permitted to perform this action",
                {"required_any_of": sorted(r.value for r in allowed), "your_role": user.role.value},
            )
        return user

    return checker


ANALYST_OR_ADMIN = (Role.TRIAGE_ANALYST, Role.ADMIN)
STAFF = (Role.TRIAGE_ANALYST, Role.SUPPORT_ENGINEER, Role.ADMIN)


class Pagination:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> None:
        self.page = page
        self.page_size = page_size


Paging = Annotated[Pagination, Depends()]
