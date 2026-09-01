import logging
from telegram import ChatPermissions, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

async def ban_user_in_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int) -> bool:
    """حظر عضو فعلياً من المجموعة"""
    try:
        await context.bot.ban_chat_member(chat_id=update.effective_chat.id, user_id=target_user_id)
        return True
    except Exception as e:
        logger.error(f"Failed to ban user {target_user_id}: {e}")
        return False

async def mute_user_in_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int) -> bool:
    """كتم عضو فعلياً (سلب صلاحية إرسال الرسائل)"""
    try:
        # تحديد صلاحيات فارغة لمنعه من إرسال النص/الميديا
        no_permissions = ChatPermissions(
            can_send_messages=False,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target_user_id,
            permissions=no_permissions
        )
        return True
    except Exception as e:
        logger.error(f"Failed to mute user {target_user_id}: {e}")
        return False

async def unban_user_in_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int) -> bool:
    """فك حظر/كتم عضو في المجموعة"""
    try:
        await context.bot.unban_chat_member(chat_id=update.effective_chat.id, user_id=target_user_id, only_if_banned=True)
        return True
    except Exception as e:
        logger.error(f"Failed to unban user {target_user_id}: {e}")
        return False
