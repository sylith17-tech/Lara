"""Persistent, chat-scoped owner settings and safe custom command records."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, JSON, String, Text, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, async_session


class GroupBotSettings(Base):
    __tablename__ = "group_bot_settings"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    welcome_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_commands_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class GroupCustomCommand(Base):
    __tablename__ = "group_custom_commands"
    __table_args__ = (UniqueConstraint("chat_id", "normalized_name", name="uq_group_custom_command_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(48), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(48), nullable=False)
    description: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    required_role: Mapped[str] = mapped_column(String(16), default="ADMIN", nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


ACTION_REGISTRY: dict[str, dict[str, str]] = {
    "MUTE": {"label": "🔇 كتم (مدة قابلة للاختيار)", "target": "USER", "role": "ADMIN"},
    "UNMUTE": {"label": "🔊 فك الكتم", "target": "USER", "role": "ADMIN"},
    "KICK": {"label": "👢 طرد", "target": "USER", "role": "ADMIN"},
    "BAN": {"label": "🚫 حظر", "target": "USER", "role": "ADMIN"},
    "UNBAN": {"label": "♻️ فك الحظر", "target": "USER_ID", "role": "ADMIN"},
    "WARN": {"label": "⚠️ تحذير", "target": "USER", "role": "ADMIN"},
    "DELETE": {"label": "🗑 حذف الرسالة المردود عليها", "target": "MESSAGE", "role": "ADMIN"},
    "PIN": {"label": "📌 تثبيت الرسالة المردود عليها", "target": "MESSAGE", "role": "ADMIN"},
    "UNPIN": {"label": "📍 إزالة تثبيت الرسالة المردود عليها", "target": "MESSAGE", "role": "ADMIN"},
    "SEND_MESSAGE": {"label": "📢 إرسال رسالة ثابتة", "target": "NONE", "role": "ADMIN"},
}


def normalize_command_name(name: str) -> str:
    return " ".join(str(name or "").casefold().split()).strip()


class GroupFeatureStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] = async_session):
        self.session_factory = session_factory

    async def settings_for(self, chat_id: int) -> GroupBotSettings:
        async with self.session_factory() as session:
            row = await session.get(GroupBotSettings, int(chat_id))
            if row is None:
                row = GroupBotSettings(chat_id=int(chat_id))
                session.add(row)
                await session.commit()
                await session.refresh(row)
            return row

    async def get_settings(self, chat_id: int) -> GroupBotSettings | None:
        async with self.session_factory() as session:
            return await session.get(GroupBotSettings, int(chat_id))

    async def update_settings(self, chat_id: int, **values: Any) -> GroupBotSettings:
        allowed = {"welcome_enabled", "welcome_template", "custom_commands_enabled"}
        if not values or values.keys() - allowed:
            raise ValueError("Unsupported group setting")
        async with self.session_factory() as session:
            row = await session.get(GroupBotSettings, int(chat_id))
            if row is None:
                row = GroupBotSettings(chat_id=int(chat_id))
                session.add(row)
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(row)
            return row

    async def create_command(self, *, chat_id: int, name: str, action: str,
                             parameters: dict[str, Any], created_by: int,
                             description: str = "") -> GroupCustomCommand:
        normalized = normalize_command_name(name)
        if not normalized or len(normalized) > 48:
            raise ValueError("اسم الأمر مطلوب وبحد أقصى 48 حرفًا")
        if action not in ACTION_REGISTRY:
            raise ValueError("الإجراء غير مدعوم")
        spec = ACTION_REGISTRY[action]
        async with self.session_factory() as session:
            exists = await session.scalar(select(GroupCustomCommand.id).where(
                GroupCustomCommand.chat_id == int(chat_id),
                GroupCustomCommand.normalized_name == normalized,
            ))
            if exists is not None:
                raise ValueError("يوجد أمر بهذا الاسم في هذه المجموعة")
            row = GroupCustomCommand(
                chat_id=int(chat_id), name=name.strip(), normalized_name=normalized,
                description=description[:200], action=action,
                parameters=dict(parameters), target_type=spec["target"],
                required_role=spec["role"], created_by=int(created_by), enabled=True,
            )
            session.add(row)
            try:
                await session.commit()
            except Exception as exc:
                await session.rollback()
                if "unique" in str(exc).casefold() or "uq_group_custom_command_name" in str(exc):
                    raise ValueError("يوجد أمر بهذا الاسم في هذه المجموعة") from exc
                raise
            await session.refresh(row)
            return row

    async def list_commands(self, chat_id: int) -> list[GroupCustomCommand]:
        async with self.session_factory() as session:
            result = await session.scalars(select(GroupCustomCommand)
                .where(GroupCustomCommand.chat_id == int(chat_id))
                .order_by(GroupCustomCommand.id))
            return list(result.all())

    async def command_by_id(self, chat_id: int, command_id: int) -> GroupCustomCommand | None:
        async with self.session_factory() as session:
            return await session.scalar(select(GroupCustomCommand).where(
                GroupCustomCommand.chat_id == int(chat_id),
                GroupCustomCommand.id == int(command_id),
            ))

    async def find_command(self, chat_id: int, text: str) -> GroupCustomCommand | None:
        normalized = normalize_command_name(text)
        async with self.session_factory() as session:
            return await session.scalar(select(GroupCustomCommand).where(
                GroupCustomCommand.chat_id == int(chat_id),
                GroupCustomCommand.normalized_name == normalized,
                GroupCustomCommand.enabled.is_(True),
            ))

    async def set_enabled(self, chat_id: int, command_id: int, enabled: bool) -> bool:
        async with self.session_factory() as session:
            row = await session.scalar(select(GroupCustomCommand).where(
                GroupCustomCommand.chat_id == int(chat_id), GroupCustomCommand.id == int(command_id)))
            if row is None:
                return False
            row.enabled = bool(enabled)
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return True

    async def rename_command(self, chat_id: int, command_id: int, name: str) -> bool:
        normalized = normalize_command_name(name)
        if not normalized or len(normalized) > 48:
            raise ValueError("اسم الأمر مطلوب وبحد أقصى 48 حرفًا")
        async with self.session_factory() as session:
            row = await session.scalar(select(GroupCustomCommand).where(
                GroupCustomCommand.chat_id == int(chat_id), GroupCustomCommand.id == int(command_id)))
            if row is None:
                return False
            duplicate = await session.scalar(select(GroupCustomCommand.id).where(
                GroupCustomCommand.chat_id == int(chat_id),
                GroupCustomCommand.normalized_name == normalized,
                GroupCustomCommand.id != int(command_id)))
            if duplicate is not None:
                raise ValueError("يوجد أمر بهذا الاسم في هذه المجموعة")
            row.name, row.normalized_name = name.strip(), normalized
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return True

    async def delete_command(self, chat_id: int, command_id: int) -> bool:
        async with self.session_factory() as session:
            row = await session.scalar(select(GroupCustomCommand).where(
                GroupCustomCommand.chat_id == int(chat_id), GroupCustomCommand.id == int(command_id)))
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


group_feature_store = GroupFeatureStore()
