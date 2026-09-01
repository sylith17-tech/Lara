from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User

class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create(self, telegram_id: int, username: str = None, first_name: str = "User") -> User:
        result = await self.session.execute(select(User).filter_by(telegram_id=telegram_id))
        user = result.scalars().first()
        if not user:
            user = User(telegram_id=telegram_id, username=username, first_name=first_name or "User")
            self.session.add(user)
            await self.session.commit()
            await self.session.refresh(user)
        else:
            if user.username != username or user.first_name != (first_name or "User"):
                user.username = username
                if first_name:
                    user.first_name = first_name
                await self.session.commit()
        return user
