import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.common.exceptions import NotFoundError, ValidationFailedError
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import AdminUserCreate, LoginRequest, UserRegister
from app.modules.auth.security import create_access_token, hash_password, verify_password


class AuthService:
    def __init__(self, session: AsyncSession):
        self._repo = UserRepository(session)

    async def register(self, payload: UserRegister) -> User:
        """Self-service signup. Always VIEWER -- elevated roles come from an admin."""
        return await self._create_user(
            payload.username, payload.email, payload.password, UserRole.VIEWER
        )

    async def create_user_as_admin(self, payload: AdminUserCreate) -> User:
        return await self._create_user(
            payload.username, payload.email, payload.password, payload.role
        )

    async def _create_user(self, username: str, email: str, password: str, role: UserRole) -> User:
        if await self._repo.get_by_username(username) is not None:
            raise ValidationFailedError(f"username already taken: {username}")
        user = User(
            username=username, email=email, hashed_password=hash_password(password), role=role
        )
        return await self._repo.add(user)

    async def authenticate(self, payload: LoginRequest) -> str:
        """Returns a JWT access token, or raises ValidationFailedError on bad
        credentials/inactive account -- deliberately the same error for "no such user"
        and "wrong password" so login doesn't leak which usernames exist."""
        user = await self._repo.get_by_username(payload.username)
        if (
            user is None
            or not user.is_active
            or not verify_password(payload.password, user.hashed_password)
        ):
            raise ValidationFailedError("invalid username or password")
        return create_access_token(user.id, user.role)

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self._repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User", user_id)
        return user

    async def list_users(self) -> list[User]:
        return await self._repo.list_all()
