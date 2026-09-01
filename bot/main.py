import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from app.core.config import settings
from bot.handlers import common

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s - %(levelname)s - %(message)s")

bot = Bot(
    token=settings.TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

dp.include_router(common.router)

async def start_bot():
    logging.info("[*] Starting Telegram Bot Engine...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(start_bot())
