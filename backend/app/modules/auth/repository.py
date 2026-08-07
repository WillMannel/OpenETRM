import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(select(User).where(User.username == username))
        return result.scalars().first()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def list_all(self) -> list[User]:
        result = await self._session.execute(select(User).order_by(User.username))
        return list(result.scalars().all())
