import asyncio
from database.db import AsyncSessionLocal, init_db
from database.repositories.user_repo import UserRepository
from database.repositories.group_repo import GroupRepository

async def test_repositories():
    await init_db()
    async with AsyncSessionLocal() as session:
        user_repo = UserRepository(session)
        group_repo = GroupRepository(session)

        user = await user_repo.get_or_create(123456789, "vip_arm", "VIP ARM")
        group = await group_repo.get_or_create(-100123456789, "Lara Test Group")
        member = await group_repo.add_or_update_member(group.id, user.id)

        print(f"[✓] Created User: {user.username} (ID: {user.telegram_id})")
        print(f"[✓] Created Group: {group.title} (ID: {group.telegram_id})")
        print(f"[✓] Member Linked with Role: {member.role}")

if __name__ == "__main__":
    asyncio.run(test_repositories())
