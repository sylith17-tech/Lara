from pathlib import Path as _Path
from sqlalchemy import Column, Integer, String, BigInteger, Boolean, text, Text
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Column, Integer, String, BigInteger, Boolean, text, Text

DATABASE_URL = "sqlite+aiosqlite:///lara.db"
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase): pass

# Keep this legacy module usable as the parent of the existing database/ package.
# `database.py` remains the active polling bot's DB facade; the path only enables
# explicit imports such as `database.models` used by the separate app/ stack.
__path__ = [str(_Path(__file__).with_name("database"))]

class User(Base):
    referred_by = Column(Integer, nullable=True)
    invites_count = Column(Integer, default=0)
    points = Column(Integer, default=0)
    last_daily = Column(String, nullable=True)
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    stars_donated: Mapped[int] = mapped_column(Integer, default=0)


class ModerationWarning(Base):
    __tablename__ = 'moderation_warnings'

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reason: Mapped[str] = mapped_column(Text, nullable=True)
    last_message_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=True)

class AutoReply(Base):
    __tablename__ = 'auto_replies'
    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    response: Mapped[str] = mapped_column(Text)

class Suggestion(Base):
    __tablename__ = 'suggestions'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text)

class Note(Base):
    __tablename__ = 'user_notes'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)

class GroupSettings(Base):
    __tablename__ = 'group_settings'
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lock_photos: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_videos: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_links: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_stickers: Mapped[bool] = mapped_column(Boolean, default=False)
    lock_voice: Mapped[bool] = mapped_column(Boolean, default=False)
    is_subscribed: Mapped[bool] = mapped_column(Boolean, default=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_moderation_warnings_chat_user "
            "ON moderation_warnings (chat_id, user_id)"
        ))
        for col, col_type in [("invites_count", "INTEGER DEFAULT 0"), ("points", "INTEGER DEFAULT 0"), ("last_daily", "VARCHAR")]:
            try:
                await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type}"))
            except Exception:
                pass
