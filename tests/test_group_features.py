from __future__ import annotations

import asyncio
import ast
import re
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base
from handlers.group_owner import (
    FLOW_KEY,
    _valid_custom_name,
    handle_owner_callback,
    is_group_owner,
    render_welcome,
)
from services.group_features import ACTION_REGISTRY, GroupFeatureStore


def test_custom_command_and_settings_persist_with_group_isolation():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        store = GroupFeatureStore(factory)

        await store.update_settings(-100, welcome_enabled=False,
                                    welcome_template="أهلًا {name} في {chat_name}")
        command = await store.create_command(chat_id=-100, name="كتم عضو", action="MUTE",
                                             parameters={"duration_seconds": 600}, created_by=99)
        await store.create_command(chat_id=-200, name="كتم عضو", action="BAN",
                                   parameters={}, created_by=88)

        restarted_store = GroupFeatureStore(factory)
        settings = await restarted_store.get_settings(-100)
        assert settings and not settings.welcome_enabled
        assert settings.welcome_template == "أهلًا {name} في {chat_name}"
        assert (await restarted_store.find_command(-100, "كتم عضو")).id == command.id
        assert (await restarted_store.find_command(-200, "كتم عضو")).action == "BAN"
        assert await restarted_store.find_command(-300, "كتم عضو") is None
        assert (await restarted_store.command_by_id(-100, command.id)).created_by == 99
        await restarted_store.set_enabled(-100, command.id, False)
        assert await restarted_store.find_command(-100, "كتم عضو") is None
        assert not (await restarted_store.list_commands(-100))[0].enabled
        assert await restarted_store.rename_command(-100, command.id, "كتم مؤقت")
        assert (await restarted_store.command_by_id(-100, command.id)).name == "كتم مؤقت"
        await restarted_store.set_enabled(-100, command.id, True)
        assert (await restarted_store.find_command(-100, "كتم مؤقت")).id == command.id
        assert await restarted_store.delete_command(-100, command.id)
        assert await restarted_store.command_by_id(-100, command.id) is None
        with pytest.raises(ValueError):
            await restarted_store.create_command(chat_id=-200, name="كتم عضو", action="MUTE",
                                                 parameters={}, created_by=88)
        await engine.dispose()

    asyncio.run(scenario())


def test_welcome_placeholders_and_unknown_names_are_safe():
    rendered = render_welcome("{name} @{username} {user_id} {chat_name} {unknown}",
                              name="Lina", username="lina", user_id=42,
                              chat_name="Study group")
    assert rendered == "Lina @lina 42 Study group {unknown}"
    assert render_welcome(None, name="Lina", username=None,
                          user_id=42, chat_name=None) is None


@pytest.mark.parametrize("status,expected", [
    ("creator", True), ("owner", True), ("administrator", False), ("member", False),
])
def test_group_settings_require_actual_owner_status(status, expected):
    async def scenario():
        chat = SimpleNamespace(id=-100, type="supergroup")
        user = SimpleNamespace(id=7)
        update = SimpleNamespace(effective_chat=chat, effective_user=user)
        context = SimpleNamespace(bot=SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status=status))))
        return await is_group_owner(update, context)
    assert asyncio.run(scenario()) is expected


def test_member_cannot_use_owner_callback_even_with_forged_data(monkeypatch):
    async def scenario():
        query = SimpleNamespace(data="owner_group:welcome_disable", answer=AsyncMock(),
                                message=SimpleNamespace(reply_text=AsyncMock()))
        update = SimpleNamespace(callback_query=query,
                                 effective_chat=SimpleNamespace(id=-100, type="supergroup"),
                                 effective_user=SimpleNamespace(id=8))
        context = SimpleNamespace(bot=SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member"))),
            user_data={FLOW_KEY: {"chat_id": -100, "step": "welcome"}})
        assert await handle_owner_callback(update, context)
        query.answer.assert_awaited_once_with("هذه الإعدادات متاحة لمالك المجموعة فقط.", show_alert=True)
        assert query.message.reply_text.await_count == 0
        assert context.user_data[FLOW_KEY]["step"] == "welcome"

    asyncio.run(scenario())


def test_every_action_shown_in_registry_has_a_backend_role_and_target():
    expected = {"MUTE", "UNMUTE", "KICK", "BAN", "UNBAN", "WARN", "DELETE", "PIN", "UNPIN", "SEND_MESSAGE"}
    assert set(ACTION_REGISTRY) == expected
    assert all(item["role"] == "ADMIN" and item["target"] for item in ACTION_REGISTRY.values())


def test_custom_admin_alias_can_extend_legacy_prefix_without_replacing_it():
    assert _valid_custom_name("كتم العضو")
    assert not _valid_custom_name("كتم")
    assert not _valid_custom_name("معلوماتي")


def test_member_cannot_execute_owner_created_custom_moderation_command(monkeypatch):
    async def scenario():
        import main

        command = SimpleNamespace(
            id=1, chat_id=-100, name="حظر سريع", normalized_name="حظر سريع",
            enabled=True, required_role="ADMIN", action="BAN", target_type="USER",
            parameters={}, created_by=99,
        )
        class FakeStore:
            async def get_settings(self, chat_id):
                return SimpleNamespace(custom_commands_enabled=True)
            async def list_commands(self, chat_id):
                return [command]

        monkeypatch.setattr(main, "group_feature_store", FakeStore())
        message = SimpleNamespace(text="حظر سريع", reply_to_message=None,
                                  entities=[], reply_text=AsyncMock())
        actor = SimpleNamespace(id=8)
        chat = SimpleNamespace(id=-100, type="supergroup")
        update = SimpleNamespace(effective_message=message, effective_chat=chat,
                                 effective_user=actor)
        bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
                              ban_chat_member=AsyncMock(), unban_chat_member=AsyncMock())
        context = SimpleNamespace(bot=bot)
        assert await main._run_group_custom_command(update, context)
        message.reply_text.assert_awaited_once_with("❌ هذا الأمر مخصص لمشرفي المجموعة.")
        bot.ban_chat_member.assert_not_awaited()

    asyncio.run(scenario())


def test_admin_custom_ban_executes_real_telegram_action(monkeypatch):
    async def scenario():
        import main

        command = SimpleNamespace(
            id=3, name="حظر سريع", normalized_name="حظر سريع", enabled=True,
            required_role="ADMIN", action="BAN", target_type="USER", parameters={}, created_by=99,
        )
        class FakeStore:
            async def get_settings(self, chat_id):
                return SimpleNamespace(custom_commands_enabled=True)
            async def list_commands(self, chat_id):
                return [command]

        monkeypatch.setattr(main, "group_feature_store", FakeStore())
        target = SimpleNamespace(id=55, first_name="Target", username="target")
        message = SimpleNamespace(text="حظر سريع", reply_to_message=SimpleNamespace(from_user=target),
                                  entities=[], reply_text=AsyncMock())
        actor = SimpleNamespace(id=8)
        chat = SimpleNamespace(id=-100, type="supergroup")
        update = SimpleNamespace(effective_message=message, effective_chat=chat,
                                 effective_user=actor)
        bot = SimpleNamespace(id=0,
            get_chat_member=AsyncMock(side_effect=[SimpleNamespace(status="administrator"),
                                                   SimpleNamespace(status="member", user=target)]),
            ban_chat_member=AsyncMock(), unban_chat_member=AsyncMock())
        context = SimpleNamespace(bot=bot)
        assert await main._run_group_custom_command(update, context)
        bot.ban_chat_member.assert_awaited_once_with(-100, 55)
        message.reply_text.assert_awaited_once_with("🚫 تم حظر Target.")

    asyncio.run(scenario())


def test_admin_custom_action_resolves_username_only_after_member_verification(monkeypatch):
    async def scenario():
        import main
        command = SimpleNamespace(name="حظر سريع", normalized_name="حظر سريع", enabled=True,
                                  required_role="ADMIN", action="BAN", target_type="USER",
                                  parameters={}, created_by=99)
        class FakeStore:
            async def get_settings(self, chat_id):
                return SimpleNamespace(custom_commands_enabled=True)
            async def list_commands(self, chat_id):
                return [command]
        class FakeSession:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def scalar(self, statement):
                return SimpleNamespace(telegram_id=55, first_name="Target")

        monkeypatch.setattr(main, "group_feature_store", FakeStore())
        monkeypatch.setattr(main, "async_session", lambda: FakeSession())
        member = SimpleNamespace(id=55, first_name="Target", username="target")
        message = SimpleNamespace(text="حظر سريع @target", reply_to_message=None,
                                  entities=[], reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=message,
            effective_chat=SimpleNamespace(id=-100, type="supergroup"),
            effective_user=SimpleNamespace(id=8))
        bot = SimpleNamespace(id=0,
            get_chat_member=AsyncMock(side_effect=[SimpleNamespace(status="administrator"),
                                                   SimpleNamespace(status="member", user=member)]),
            ban_chat_member=AsyncMock())
        assert await main._run_group_custom_command(update, SimpleNamespace(bot=bot))
        bot.ban_chat_member.assert_awaited_once_with(-100, 55)
    asyncio.run(scenario())


def test_legacy_commands_callbacks_buttons_and_handlers_are_not_removed():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    tracked = ("main.py", "main_vip.py", "handlers/video_editor.py")
    def old_source(name):
        return subprocess.check_output(["git", "show", f"HEAD:{name}"], cwd=root, text=True)
    def current_source(name):
        return (root / name).read_text(encoding="utf-8")
    def public_literals(source):
        tree = ast.parse(source)
        functions = {node.name for node in ast.walk(tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        strings = {node.value for node in ast.walk(tree)
                   if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        return functions, strings

    for name in tracked:
        old, current = old_source(name), current_source(name)
        old_functions, old_strings = public_literals(old)
        current_functions, current_strings = public_literals(current)
        assert old_functions <= current_functions, f"legacy handler/function removed in {name}"
        old_callbacks = set(re.findall(r'callback_data\s*=\s*"([^"]+)"', old))
        new_callbacks = set(re.findall(r'callback_data\s*=\s*"([^"]+)"', current))
        assert old_callbacks <= new_callbacks, f"legacy callback removed in {name}"
        old_buttons = set(re.findall(r'InlineKeyboardButton\(\s*"([^"]+)"', old))
        new_buttons = set(re.findall(r'InlineKeyboardButton\(\s*"([^"]+)"', current))
        assert old_buttons <= new_buttons, f"legacy button removed in {name}"
        old_commands = set(re.findall(r'CommandHandler\(\s*"([^"]+)"', old))
        new_commands = set(re.findall(r'CommandHandler\(\s*"([^"]+)"', current))
        assert old_commands <= new_commands, f"legacy Telegram command removed in {name}"


def test_telegram_calc_rejects_code_and_keeps_normal_arithmetic():
    async def scenario():
        import main
        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        context = SimpleNamespace(args=["12", "+", "3"])
        await main.cmd_calc(update, context)
        update.message.reply_text.assert_awaited_once_with("🔢 **النتيجة:** `15`", parse_mode=None)

        update.message.reply_text.reset_mock()
        context.args = ["1+__import__('os').system('id')"]
        await main.cmd_calc(update, context)
        update.message.reply_text.assert_awaited_once_with("⚠️ خطأ في المعادلة.")

    asyncio.run(scenario())


def test_alternate_permission_service_uses_persisted_role_instead_of_allow_all(monkeypatch):
    async def scenario():
        monkeypatch.setenv("SECRET_KEY", "unit-test-secret-that-is-at-least-32-chars")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("WEBHOOK_SECRET", "test-webhook-secret")
        from app.services.permission_service import PermissionService
        from database.db import Base as AppBase
        from database.models import Group, GroupMember, RoleEnum, User

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(AppBase.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            group = Group(telegram_id=-100, title="Test")
            admin = User(telegram_id=10, username="admin", first_name="Admin")
            owner = User(telegram_id=11, username="owner", first_name="Owner")
            session.add_all([group, admin, owner])
            await session.flush()
            session.add_all([
                GroupMember(group_id=group.id, user_id=admin.id, role=RoleEnum.ADMIN),
                GroupMember(group_id=group.id, user_id=owner.id, role=RoleEnum.OWNER),
            ])
            await session.commit()
            permissions = PermissionService(session)
            assert await permissions.check_permission(10, -100, RoleEnum.ADMIN)
            assert not await permissions.check_permission(10, -100, RoleEnum.OWNER)
            assert await permissions.check_permission(11, -100, RoleEnum.OWNER)
            assert not await permissions.check_permission(99, -100, RoleEnum.MEMBER)
        await engine.dispose()

    asyncio.run(scenario())
