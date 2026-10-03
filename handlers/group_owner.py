"""Owner-only, group-scoped setup UI for welcome messages and safe commands."""
from __future__ import annotations

import re
from collections.abc import Mapping

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from services.group_features import ACTION_REGISTRY, group_feature_store


FLOW_KEY = "lara_group_owner_flow"
RESERVED_COMMANDS = {
    "طرد", "كتم", "فك الكتم", "فك الحظر", "حظر", "تحذير", "مسح", "قفل المحادثة",
    "فتح المحادثة", "معلوماتي", "رتبتي", "اكس او", "لارا نكتة", "لارا قصف",
    "نزلي", "حملي", "تحميل", "لارا احكي", "تغيير رسالة الترحيب", "إعدادات المجموعة",
    "قفل الصور", "فتح الصور", "قفل الفيديو", "فتح الفيديو", "قفل الروابط", "فتح الروابط",
    "قفل الملصقات", "فتح الملصقات", "قفل الصوتيات", "فتح الصوتيات", "تنظيف الصور",
    "نقاطي", "تفاعلي", "الجائزة اليومية", "استبدال النقاط", "نسبة الحب", "اختراق",
}
OVERLOADABLE_ADMIN_PREFIXES = (
    "طرد", "اطردي", "لارا طردي", "لارا اطردي", "كتم", "اكتمي", "كتمي",
    "لارا اكتمي", "فك الكتم", "فكي الكتم", "لارا فكي الكتم", "تحذير", "حذري",
    "لارا حذري", "تثبيت", "ثبتي", "لارا ثبتي", "قفل المحادثة", "لارا اقفلي",
    "قفل الجروب", "فتح المحادثة", "فتح الجروب", "لارا افتحي", "حظر", "احظر",
    "الغاء الحظر", "فك الحظر",
)


async def is_group_owner(update, context, chat_id: int | None = None) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    target_chat_id = chat_id if chat_id is not None else (chat.id if chat else None)
    if not chat or chat.type not in ("group", "supergroup") or not user or target_chat_id != chat.id:
        return False
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
    except Exception:
        return False
    return getattr(member, "status", "") in {"creator", "owner"}


async def is_group_admin(update, context) -> bool:
    chat, user = update.effective_chat, update.effective_user
    if not chat or chat.type not in ("group", "supergroup") or not user:
        return False
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
    except Exception:
        return False
    return getattr(member, "status", "") in {"administrator", "creator", "owner"}


def owner_menu_keyboard(settings) -> InlineKeyboardMarkup:
    command_label = "🟢 تعطيل الأوامر المخصصة" if settings.custom_commands_enabled else "🔴 تفعيل الأوامر المخصصة"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة أمر", callback_data="owner_group:add")],
        [InlineKeyboardButton("📋 أوامري", callback_data="owner_group:list")],
        [InlineKeyboardButton("👋 إعدادات الترحيب", callback_data="owner_group:welcome")],
        [InlineKeyboardButton(command_label, callback_data="owner_group:commands_toggle")],
    ])


async def show_owner_menu(message, chat_id: int) -> None:
    settings = await group_feature_store.settings_for(chat_id)
    await message.reply_text("⚙️ إعدادات المالك لهذه المجموعة:", reply_markup=owner_menu_keyboard(settings))


def _welcome_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    toggle = "🔴 تعطيل الترحيب" if enabled else "🟢 تفعيل الترحيب"
    action = "disable" if enabled else "enable"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle, callback_data=f"owner_group:welcome_{action}")],
        [InlineKeyboardButton("✏️ تغيير رسالة الترحيب", callback_data="owner_group:welcome_edit")],
        [InlineKeyboardButton("👀 معاينة الرسالة", callback_data="owner_group:welcome_preview")],
        [InlineKeyboardButton("↩️ استعادة الافتراضية", callback_data="owner_group:welcome_reset")],
        [InlineKeyboardButton("↩️ رجوع", callback_data="owner_group:open")],
    ])


async def _show_welcome(message, chat_id: int) -> None:
    settings = await group_feature_store.settings_for(chat_id)
    status = "مفعّل" if settings.welcome_enabled else "متوقف"
    current = settings.welcome_template or "الرسالة الترحيبية الافتراضية القديمة"
    await message.reply_text(f"👋 إعدادات الترحيب ({status})\nالرسالة: {current}", reply_markup=_welcome_keyboard(settings.welcome_enabled))


def _action_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(spec["label"], callback_data=f"owner_group:action_{action}")]
            for action, spec in ACTION_REGISTRY.items()]
    rows.append([InlineKeyboardButton("↩️ إلغاء", callback_data="owner_group:open")])
    return InlineKeyboardMarkup(rows)


async def _show_command_list(message, chat_id: int) -> None:
    commands = await group_feature_store.list_commands(chat_id)
    if not commands:
        await message.reply_text("لا توجد أوامر مخصصة في هذه المجموعة بعد.")
        return
    for command in commands:
        status = "🟢 فعال" if command.enabled else "🔴 متوقف"
        action_label = ACTION_REGISTRY.get(command.action, {}).get("label", command.action)
        target = {"USER": "عضو بالرد أو ID/@mention", "USER_ID": "Telegram user ID",
                  "MESSAGE": "رسالة بالرد", "NONE": "لا يحتاج هدفًا"}.get(command.target_type, command.target_type)
        text = f"📋 {command.name}\nالحالة: {status}\nالإجراء: {action_label}\nالهدف: {target}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ إعادة تسمية", callback_data=f"owner_group:rename_{command.id}"),
             InlineKeyboardButton("🟢 تفعيل" if not command.enabled else "🔴 تعطيل",
                                  callback_data=f"owner_group:toggle_{command.id}")],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"owner_group:delete_{command.id}")],
        ])
        await message.reply_text(text, reply_markup=keyboard)


def _valid_custom_name(name: str) -> bool:
    normalized = " ".join(name.split()).casefold()
    from arsyra.conversation import is_existing_feature_command
    legacy = is_existing_feature_command(normalized)
    explicit_admin_overload = any(normalized.startswith(prefix + " ")
                                  for prefix in OVERLOADABLE_ADMIN_PREFIXES)
    return bool(normalized and len(normalized) <= 48 and not normalized.startswith("/")
                and normalized not in RESERVED_COMMANDS
                and (not legacy or explicit_admin_overload)
                and not re.fullmatch(r"[\W_]+", normalized))


def _format_template(template: str, values: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(values[key]) if key in values else match.group(0)
    return re.sub(r"\{([^{}]+)\}", replace, template)


def render_welcome(template: str | None, *, name: str, username: str | None,
                   user_id: int, chat_name: str | None) -> str | None:
    if not template:
        return None
    return _format_template(template, {
        "name": name or "عضو جديد",
        "username": username or "بدون معرف",
        "user_id": str(user_id),
        "chat_name": chat_name or "المجموعة",
    })


async def handle_owner_callback(update, context) -> bool:
    query = update.callback_query
    chat, user = update.effective_chat, update.effective_user
    if not query or not chat or not user:
        return True
    if not await is_group_owner(update, context):
        await query.answer("هذه الإعدادات متاحة لمالك المجموعة فقط.", show_alert=True)
        return True
    try:
        await query.answer()
    except Exception:
        pass
    data = query.data or ""
    if data == "owner_group:open":
        await show_owner_menu(query.message, chat.id)
    elif data == "owner_group:add":
        context.user_data[FLOW_KEY] = {"chat_id": chat.id, "step": "name"}
        await query.message.reply_text("📝 أرسل اسم الأمر الجديد (48 حرفًا كحد أقصى).")
    elif data == "owner_group:list":
        await _show_command_list(query.message, chat.id)
    elif data == "owner_group:welcome":
        await _show_welcome(query.message, chat.id)
    elif data in {"owner_group:welcome_enable", "owner_group:welcome_disable"}:
        enabled = data.endswith("enable")
        await group_feature_store.update_settings(chat.id, welcome_enabled=enabled)
        await _show_welcome(query.message, chat.id)
    elif data == "owner_group:welcome_edit":
        context.user_data[FLOW_KEY] = {"chat_id": chat.id, "step": "welcome"}
        await query.message.reply_text("📝 أرسل نص الترحيب. المتغيرات: {name} {username} {user_id} {chat_name}")
    elif data == "owner_group:welcome_preview":
        settings = await group_feature_store.settings_for(chat.id)
        preview = render_welcome(settings.welcome_template, name=user.first_name or "عضو",
                                 username=user.username, user_id=user.id, chat_name=chat.title)
        if preview is None:
            preview = f"🎉 أهلاً بك يا {user.first_name or 'عضو'} في مجموعتنا! هذه معاينة للترحيب الافتراضي."
        await query.message.reply_text(preview)
    elif data == "owner_group:welcome_reset":
        await group_feature_store.update_settings(chat.id, welcome_template=None)
        await _show_welcome(query.message, chat.id)
    elif data == "owner_group:commands_toggle":
        settings = await group_feature_store.settings_for(chat.id)
        await group_feature_store.update_settings(chat.id, custom_commands_enabled=not settings.custom_commands_enabled)
        await show_owner_menu(query.message, chat.id)
    elif data.startswith("owner_group:action_"):
        action = data.removeprefix("owner_group:action_")
        flow = context.user_data.get(FLOW_KEY, {})
        if flow.get("chat_id") != chat.id or flow.get("step") != "action" or action not in ACTION_REGISTRY:
            await query.message.reply_text("انتهت خطوة إنشاء الأمر. ابدأ من جديد من لوحة المالك.")
        elif action == "MUTE":
            flow["action"] = action
            flow["step"] = "mute_duration"
            context.user_data[FLOW_KEY] = flow
            await query.message.reply_text("اختر مدة الكتم:", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("5 دقائق", callback_data="owner_group:duration_300"),
                 InlineKeyboardButton("10 دقائق", callback_data="owner_group:duration_600")],
                [InlineKeyboardButton("ساعة", callback_data="owner_group:duration_3600"),
                 InlineKeyboardButton("دائم حتى فكّه", callback_data="owner_group:duration_0")],
            ]))
        elif action == "SEND_MESSAGE":
            flow["action"] = action
            flow["step"] = "body"
            context.user_data[FLOW_KEY] = flow
            await query.message.reply_text("📢 أرسل نص الرسالة التي سينشرها الأمر.")
        else:
            try:
                await group_feature_store.create_command(chat_id=chat.id, name=flow["name"], action=action,
                                                         parameters={}, created_by=user.id)
            except ValueError as exc:
                await query.message.reply_text(str(exc))
            else:
                context.user_data.pop(FLOW_KEY, None)
                await query.message.reply_text("✅ تم إنشاء الأمر وحفظه لهذه المجموعة.")
    elif data.startswith("owner_group:duration_"):
        flow = context.user_data.get(FLOW_KEY, {})
        raw_seconds = data.removeprefix("owner_group:duration_")
        if not raw_seconds.isdigit():
            await query.message.reply_text("مدة غير صالحة.")
            return True
        seconds = int(raw_seconds)
        if flow.get("chat_id") != chat.id or flow.get("step") != "mute_duration" or seconds not in {0, 300, 600, 3600}:
            await query.message.reply_text("انتهت خطوة إنشاء الأمر. ابدأ من جديد.")
        else:
            try:
                await group_feature_store.create_command(chat_id=chat.id, name=flow["name"], action="MUTE",
                                                         parameters={"duration_seconds": seconds}, created_by=user.id)
            except ValueError as exc:
                await query.message.reply_text(str(exc))
            else:
                context.user_data.pop(FLOW_KEY, None)
                await query.message.reply_text("✅ تم إنشاء أمر الكتم.")
    elif re.fullmatch(r"owner_group:(toggle|delete|rename)_\d+", data):
        action, raw_id = data.split(":", 1)[1].split("_", 1)
        command_id = int(raw_id)
        command = await group_feature_store.command_by_id(chat.id, command_id)
        if not command:
            await query.message.reply_text("الأمر غير موجود في هذه المجموعة.")
        elif action == "toggle":
            await group_feature_store.set_enabled(chat.id, command_id, not command.enabled)
            await _show_command_list(query.message, chat.id)
        elif action == "delete":
            await group_feature_store.delete_command(chat.id, command_id)
            await query.message.reply_text("🗑 حُذف الأمر من هذه المجموعة.")
        else:
            context.user_data[FLOW_KEY] = {"chat_id": chat.id, "step": "rename", "command_id": command_id}
            await query.message.reply_text("✏️ أرسل الاسم الجديد للأمر.")
    else:
        await query.message.reply_text("إجراء غير معروف.")
    return True


async def handle_owner_flow_message(update, context) -> bool:
    message, chat, user = update.effective_message, update.effective_chat, update.effective_user
    if not message or not message.text or not chat or not user:
        return False
    flow = context.user_data.get(FLOW_KEY)
    if not flow or flow.get("chat_id") != chat.id:
        return False
    if not await is_group_owner(update, context):
        context.user_data.pop(FLOW_KEY, None)
        await message.reply_text("انتهت صلاحية هذه الخطوة؛ إعدادات المجموعة للمالك فقط.")
        return True
    text = message.text.strip()
    step = flow.get("step")
    try:
        if step == "name":
            if not _valid_custom_name(text):
                await message.reply_text("اسم غير صالح أو يتعارض مع أمر قديم. أرسل اسمًا آخر.")
                return True
            flow["name"] = " ".join(text.split())
            flow["step"] = "action"
            context.user_data[FLOW_KEY] = flow
            await message.reply_text("اختر إجراءً مدعومًا:", reply_markup=_action_keyboard())
        elif step == "welcome":
            if not text or len(text) > 1500:
                await message.reply_text("النص مطلوب وبحد أقصى 1500 حرف.")
                return True
            await group_feature_store.update_settings(chat.id, welcome_template=text)
            context.user_data.pop(FLOW_KEY, None)
            await message.reply_text("✅ حُفظت رسالة الترحيب لهذه المجموعة.")
        elif step == "body":
            if not text or len(text) > 3000:
                await message.reply_text("النص مطلوب وبحد أقصى 3000 حرف.")
                return True
            await group_feature_store.create_command(chat_id=chat.id, name=flow["name"],
                                                     action="SEND_MESSAGE", parameters={"message": text},
                                                     created_by=user.id)
            context.user_data.pop(FLOW_KEY, None)
            await message.reply_text("✅ تم إنشاء أمر الإرسال للمشرفين.")
        elif step == "rename":
            await group_feature_store.rename_command(chat.id, int(flow["command_id"]), text)
            context.user_data.pop(FLOW_KEY, None)
            await message.reply_text("✅ تم تحديث اسم الأمر.")
        else:
            context.user_data.pop(FLOW_KEY, None)
            return False
    except ValueError as exc:
        await message.reply_text(str(exc))
    return True
