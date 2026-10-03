import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Group, GroupMember, RoleEnum, User

class PermissionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def check_permission(self, telegram_user_id: int, telegram_group_id: int, required_role: RoleEnum) -> bool:
        role_hierarchy = {
            RoleEnum.MEMBER: 1,
            RoleEnum.ADMIN: 3,
            RoleEnum.OWNER: 4
        }
        if required_role not in role_hierarchy:
            return False
        result = await self.session.execute(
            select(GroupMember.role)
            .join(Group, GroupMember.group_id == Group.id)
            .join(User, GroupMember.user_id == User.id)
            .where(Group.telegram_id == telegram_group_id,
                   User.telegram_id == telegram_user_id)
        )
        actual_role = result.scalar_one_or_none()
        return actual_role in role_hierarchy and role_hierarchy[actual_role] >= role_hierarchy[required_role]
