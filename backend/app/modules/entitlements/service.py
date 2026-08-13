"""Book-level entitlements (desk separation / "Chinese walls").

Design: a book is entitlement-*restricted* only once it's assigned to a Desk
(`Book.desk_id` set). A book with no desk is unrestricted -- any authenticated user
with the right role (TRADER, RISK_MANAGER, ...) can act on it, exactly like every book
behaved before this module existed. This is a deliberate opt-in: rolling this out
without it would instantly lock every existing book/test/deployment out for every
non-admin user the moment this code shipped, which is a worse operational failure mode
than "entitlements aren't enforced yet on books nobody has walled off." An operator
turns on the wall for a book by creating a Desk, assigning the book to it, and granting
BookMembership rows for whoever should still have access.

ADMIN always bypasses -- this is the intentional "someone can always see everything"
break-glass role, consistent with how require_role already treats ADMIN as a superset
of every other role's endpoints.

This is enforced in the *service* layer (TradeCaptureService, ValuationService,
RiskService, LimitService, ExportService), not in routers -- every one of those
services' book-scoped methods takes the acting User and calls into this service before
touching book-scoped data, the same way volume-limit enforcement lives in
TradeCaptureService rather than being a router-level check. A router-level check alone
would miss any other caller of these services (a future background job, another
module) and would need to be duplicated at every route instead of living once at the
data-access boundary.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import UserRole
from app.common.exceptions import ForbiddenError, NotFoundError
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.entitlements.models import BookMembership, Desk
from app.modules.entitlements.repository import EntitlementRepository
from app.modules.trade_capture.repository import ReferenceDataRepository


def _role(user: User) -> UserRole:
    # user.role may be a plain str (a fresh-from-DB ORM object on a String-typed
    # column comes back that way) or the real enum -- normalize either.
    return UserRole(user.role.value if hasattr(user.role, "value") else user.role)


class EntitlementService:
    def __init__(self, session: AsyncSession):
        self._repo = EntitlementRepository(session)
        self._ref_data_repo = ReferenceDataRepository(session)
        self._user_repo = UserRepository(session)

    async def assert_can_access_book(self, actor: User, book_id: uuid.UUID) -> None:
        """Raises ForbiddenError if `actor` isn't entitled to `book_id`; raises
        NotFoundError if the book doesn't exist at all (never leaks "book exists but
        you can't see it" vs. "book doesn't exist" -- NotFoundError and ForbiddenError
        map to different HTTP statuses, 404 vs 403, and a caller with no visibility
        into a desk shouldn't learn a book id is even valid from a 403 rather than a
        404 -- though v1 accepts that gap for simplicity; see FUTURE_WORK.md)."""
        if _role(actor) == UserRole.ADMIN:
            return
        restricted = await self._repo.is_book_restricted(book_id)
        if restricted is None:
            raise NotFoundError("Book", book_id)
        if not restricted:
            return
        if not await self._repo.has_membership(book_id, actor.id):
            raise ForbiddenError(
                f"user {actor.id} is not a member of the desk book {book_id} belongs to"
            )

    async def accessible_book_ids(self, actor: User) -> set[uuid.UUID] | None:
        """None means "unrestricted, don't filter" (ADMIN). Otherwise the set of book
        ids `actor` may see: every unrestricted book plus every book they're an
        explicit member of."""
        if _role(actor) == UserRole.ADMIN:
            return None
        return await self._repo.accessible_book_ids(actor.id)

    # -- admin management (desks, book-desk assignment, memberships) -----------------

    async def create_desk(self, name: str, description: str | None) -> Desk:
        return await self._repo.add_desk(Desk(name=name, description=description))

    async def list_desks(self) -> list[Desk]:
        return await self._repo.list_desks()

    async def assign_book_desk(self, book_id: uuid.UUID, desk_id: uuid.UUID | None) -> None:
        """Setting desk_id turns entitlement enforcement ON for this book (only
        members can access it from then on); setting it back to None turns it back
        OFF (unrestricted again). Raises NotFoundError if the book or the desk (when
        not None) doesn't exist."""
        book = await self._ref_data_repo.get_book(book_id)
        if book is None:
            raise NotFoundError("Book", book_id)
        if desk_id is not None and await self._repo.get_desk(desk_id) is None:
            raise NotFoundError("Desk", desk_id)
        await self._repo.assign_book_to_desk(book, desk_id)

    async def grant_membership(
        self, book_id: uuid.UUID, user_id: uuid.UUID, granted_by: User
    ) -> BookMembership:
        book = await self._ref_data_repo.get_book(book_id)
        if book is None:
            raise NotFoundError("Book", book_id)
        if await self._user_repo.get_by_id(user_id) is None:
            raise NotFoundError("User", user_id)
        return await self._repo.add_membership(
            BookMembership(book_id=book_id, user_id=user_id, granted_by_user_id=granted_by.id)
        )

    async def revoke_membership(self, book_id: uuid.UUID, user_id: uuid.UUID) -> None:
        removed = await self._repo.remove_membership(book_id, user_id)
        if not removed:
            raise NotFoundError("BookMembership", f"book={book_id} user={user_id}")

    async def list_memberships(self, book_id: uuid.UUID) -> list[BookMembership]:
        if await self._ref_data_repo.get_book(book_id) is None:
            raise NotFoundError("Book", book_id)
        return await self._repo.list_memberships_for_book(book_id)
