"""Bootstrap the first ADMIN user directly against the database.

POST /auth/users (the normal way to create a TRADER/RISK_MANAGER/ADMIN account) itself
requires an ADMIN caller -- so the very first admin has to be created out of band. Run
this once per deployment, then use /auth/users for everyone after that.

Usage:
    python scripts/create_admin.py <username> <email> <password>
"""

import asyncio
import sys

from app.common.enums import UserRole
from app.core.db import async_session_factory
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.auth.security import hash_password


async def main(username: str, email: str, password: str) -> None:
    async with async_session_factory() as session:
        repo = UserRepository(session)
        if await repo.get_by_username(username) is not None:
            print(f"user {username!r} already exists -- nothing to do")
            return
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.ADMIN,
        )
        await repo.add(user)
        print(f"created admin user {username!r}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
