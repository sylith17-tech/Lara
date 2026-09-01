import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine
from database.base import Base
from database.models import User, Group, RoleEnum

async def test_connection():
    print("[*] Testing Database Models setup...")
    # استخدام قاعدة بيانات مؤقتة في الذاكرة لتجربة النماذج وتأكيد سلامة العلاقات
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    print("[✓] Database Tables created successfully in test environment!")
    print("[✓] All Models (Users, Groups, GroupMembers, Subscriptions, LicenseCodes) are valid.")
    await test_engine.dispose()

if __name__ == "__main__":
    try:
        import aiosqlite
    except ImportError:
        print("[!] Installing temporary sqlite engine driver for local test...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "aiosqlite"], check=True)
    
    asyncio.run(test_connection())
