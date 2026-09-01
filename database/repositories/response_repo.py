from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import CustomResponse

class CustomResponseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_or_update_response(self, trigger: str, response_text: str) -> CustomResponse:
        """إضافة رد تلقائي جديد أو تحديث رد موجود"""
        result = await self.session.execute(select(CustomResponse).filter_by(trigger=trigger))
        custom_resp = result.scalars().first()
        
        if custom_resp:
            custom_resp.response = response_text
        else:
            custom_resp = CustomResponse(trigger=trigger, response=response_text)
            self.session.add(custom_resp)
            
        await self.session.commit()
        await self.session.refresh(custom_resp)
        return custom_resp

    async def get_response(self, trigger: str) -> str | None:
        """جلب الرد التلقائي المقترن بالكلمة المفتاحية"""
        result = await self.session.execute(select(CustomResponse).filter_by(trigger=trigger))
        custom_resp = result.scalars().first()
        return custom_resp.response if custom_resp else None

    async def delete_response(self, trigger: str) -> bool:
        """حذف رد تلقائي"""
        result = await self.session.execute(select(CustomResponse).filter_by(trigger=trigger))
        custom_resp = result.scalars().first()
        if custom_resp:
            await self.session.delete(custom_resp)
            await self.session.commit()
            return True
        return False
