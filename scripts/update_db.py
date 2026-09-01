import asyncio
from database.db import init_db

async def main():
    await init_db()
    print("[✓] Dynamic Custom Responses table verified/created in database!")

if __name__ == "__main__":
    asyncio.run(main())
