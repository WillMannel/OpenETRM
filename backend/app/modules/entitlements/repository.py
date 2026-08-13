import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.entitlements.models import BookMembership, Desk
from app.modules.trade_capture.models import Book


class EntitlementRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add_desk(self, desk: Desk) -> Desk:
        self._session.add(desk)
        await self._session.commit()
        await self._session.refresh(desk)
        return desk

    async def list_desks(self) -> list[Desk]:
        result = await self._session.execute(select(Desk).order_by(Desk.name))
        return list(result.scalars().all())

    async def get_desk(self, desk_id: uuid.UUID) -> Desk | None:
        return await self._session.get(Desk, desk_id)

    async def assign_book_to_desk(self, book: Book, desk_id: uuid.UUID | None) -> Book:
        book.desk_id = desk_id
        self._session.add(book)
        await self._session.commit()
        await self._session.refresh(book)
        return book

    async def add_membership(self, membership: BookMembership) -> BookMembership:
        self._session.add(membership)
        await self._session.commit()
        await self._session.refresh(membership)
        return membership

    async def remove_membership(self, book_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = select(BookMembership).where(
            BookMembership.book_id == book_id, BookMembership.user_id == user_id
        )
        result = await self._session.execute(stmt)
        membership = result.scalars().first()
        if membership is None:
            return False
        await self._session.delete(membership)
        await self._session.commit()
        return True

    async def list_memberships_for_book(self, book_id: uuid.UUID) -> list[BookMembership]:
        stmt = select(BookMembership).where(BookMembership.book_id == book_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def has_membership(self, book_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = select(BookMembership.id).where(
            BookMembership.book_id == book_id, BookMembership.user_id == user_id
        )
        result = await self._session.execute(stmt)
        return result.scalars().first() is not None

    async def accessible_book_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        """Every book with no desk assigned (unrestricted, see Desk's docstring) plus
        every book this user has an explicit BookMembership for."""
        unrestricted_stmt = select(Book.id).where(Book.desk_id.is_(None))
        member_stmt = select(BookMembership.book_id).where(BookMembership.user_id == user_id)
        unrestricted = (await self._session.execute(unrestricted_stmt)).scalars().all()
        member_of = (await self._session.execute(member_stmt)).scalars().all()
        return set(unrestricted) | set(member_of)

    async def is_book_restricted(self, book_id: uuid.UUID) -> bool | None:
        """True if the book has a desk (entitlement-enforced), False if unrestricted,
        None if the book doesn't exist. A single row fetch, not two queries -- `.first()`
        alone can't distinguish "no such book" from "book exists with desk_id NULL"."""
        result = await self._session.execute(select(Book.desk_id).where(Book.id == book_id))
        row = result.first()
        if row is None:
            return None
        return row[0] is not None
