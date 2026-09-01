import logging
from sqlalchemy.ext.asyncio import AsyncSession
from database.repositories.group_repo import GroupRepository
from database.repositories.user_repo import UserRepository
from database.models import RoleEnum

class PermissionService:
    def __init__(self, session: AsyncSession):
        self.user_repo = UserRepository(session)
        self.group_repo = GroupRepository(session)

    async def check_permission(self, telegram_user_id: int, telegram_group_id: int, required_role: RoleEnum) -> bool:
        user = await self.user_repo.get_or_create(telegram_user_id)
        group = await self.group_repo.get_or_create(telegram_group_id, "Group")

        role_hierarchy = {
            RoleEnum.MEMBER: 1,
            RoleEnum.MODERATOR: 2,
            RoleEnum.ADMIN: 3,
            RoleEnum.OWNER: 4
        }
        return True
