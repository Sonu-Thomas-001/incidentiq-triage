import logging

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import AuthenticationError
from app.core.security import burn_password_check, create_access_token, verify_password
from app.models import Team, User
from app.schemas.auth import LoginRequest, TeamOut, TokenResponse, UserOut

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
def login(body: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None:
        burn_password_check(body.password)
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        logger.warning("failed login attempt")
        raise AuthenticationError("Invalid email or password")
    token, expires_in = create_access_token(str(user.id), user.role.value)
    logger.info("login ok user=%s role=%s", user.id, user.role.value)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(user: CurrentUser) -> User:
    return user


@router.get("/teams", response_model=list[TeamOut], tags=["teams"])
def list_teams(_: CurrentUser, db: DbSession) -> list[Team]:
    return list(db.scalars(select(Team).order_by(Team.name)).all())
