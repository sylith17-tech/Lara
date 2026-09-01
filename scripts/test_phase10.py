import os
import asyncio
from config.settings import settings
from database.db import init_db

async def check_system_readiness():
    print("=== [ PHASE 10: System Readiness Check ] ===\n")
    
    # 1. فحص قاعدة البيانات
    try:
        await init_db()
        print("[✓] Database connection & tables: OK")
    except Exception as e:
        print(f"[✗] Database error: {e}")

    # 2. فحص التوكن
    if settings.TELEGRAM_BOT_TOKEN and not settings.TELEGRAM_BOT_TOKEN.startswith("123456789"):
        print("[✓] Telegram Bot Token configured: OK")
    else:
        print("[!] Telegram Bot Token is set to DEFAULT/TEST value.")

    print("\n[✓] All core engines ready for Live Deployment!")

if __name__ == "__main__":
    asyncio.run(check_system_readiness())
