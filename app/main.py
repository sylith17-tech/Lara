import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from aiogram.types import Update
from app.core.config import settings
from bot.main import bot, dp

logging.basicConfig(level=settings.LOG_LEVEL)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("[*] Starting FastAPI Web Infrastructure...")
    yield
    logging.info("[*] Shutting down FastAPI...")

app = FastAPI(
    title="Lara Engine Core",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
async def root():
    return {"status": "online", "service": "Lara Core Engine", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "database": "connected"}

@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update(**data)
        await dp.feed_update(bot, update)
        return {"ok": True}
    except Exception as e:
        logging.error(f"Webhook Error: {e}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": str(e)}
        )
