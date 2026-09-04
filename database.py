import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, BigInteger, Text, Boolean, Integer, DateTime, func

DATABASE_URL = "sqlite+aiosqlite:///lara.db"
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    stars_donated: Mapped[int] = mapped_column(Integer, default=0)

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
