from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    APP_NAME: str = "Lara"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = Field(..., min_length=32)

    DATABASE_URL: str
    REDIS_URL: str

    TELEGRAM_BOT_TOKEN: str
    WEBHOOK_SECRET: str

    OPENAI_API_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
