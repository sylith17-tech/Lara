import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./lara.db")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

settings = Settings()
