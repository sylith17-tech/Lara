from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Group, GroupMember, RoleEnum

class GroupRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, telegram_id: int, title: str) -> Group:
        result = await self.session.execute(select(Group).filter_by(telegram_id=telegram_id))
        group = result.scalars().first()
        if not group:
            group = Group(telegram_id=telegram_id, title=title)
            self.session.add(group)
            await self.session.commit()
            await self.session.refresh(group)
        return group

    async def add_or_update_member(self, group_id: int, user_id: int, role: RoleEnum = RoleEnum.MEMBER) -> GroupMember:
        result = await self.session.execute(
            select(GroupMember).filter_by(group_id=group_id, user_id=user_id)
        )
        member = result.scalars().first()
        if not member:
            member = GroupMember(group_id=group_id, user_id=user_id, role=role)
            self.session.add(member)
        else:
            member.role = role
        await self.session.commit()
        return member
