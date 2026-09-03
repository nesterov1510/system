"""Production seed must remain safe after administrators add more admins."""
import asyncio

from sqlalchemy import func, select

from app.db.models import User, UserRole
from app.db.seed import seed
from app.db.session import async_session_factory


def test_seed_allows_multiple_admin_users(client, admin_headers):
    created = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "name": "Второй администратор",
            "email": "second-admin@msb.local",
            "password": "second-admin-123",
            "role": UserRole.ADMIN.value,
        },
    )
    assert created.status_code == 201, created.text

    async def reseed() -> tuple[int, int]:
        async with async_session_factory() as db:
            count = select(func.count(User.id)).where(
                User.role == UserRole.ADMIN.value
            )
            before = int(await db.scalar(count) or 0)
            await seed(db)
            after = int(await db.scalar(count) or 0)
            return before, after

    before, after = asyncio.run(reseed())
    assert before >= 2
    assert after == before
