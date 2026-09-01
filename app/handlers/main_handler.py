import os
import logging
from telegram import Update
from telegram.ext import ContextTypes
from database.db import AsyncSessionLocal
from database.repositories.user_repo import UserRepository
from database.repositories.group_repo import GroupRepository
from database.repositories.response_repo import CustomResponseRepository
from app.handlers.admin_and_stars import COMMANDS_GUIDE, send_stars_invoice
from app.utils.telegram_ops import ban_user_in_telegram, mute_user_in_telegram, unban_user_in_telegram
from app.utils.music import search_and_download_song

logger = logging.getLogger(__name__)

ADMIN_IDS = [123456789]

class MessageDispatcher:
    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
        if not update.message or not update.message.text:
            return ""

        user = update.effective_user
        chat = update.effective_chat
        text = update.message.text.strip()

        # 1. ميزة البحث عن الأغاني وتحميلها
        music_triggers = ["لارا ابحثي عن اغنية", "ابحثي عن اغنية", "اغنية", "/song"]
        is_music_query = False
        song_query = ""

        for trigger in music_triggers:
            if text.startswith(trigger):
                is_music_query = True
                song_query = text.replace(trigger, "").strip()
                break

        if is_music_query:
            if not song_query:
                return "🎵 يرجى كتابة اسم الأغنية بعد الأمر، مثال:\n`لارا ابحثي عن اغنية اسم الأغنية`"
            
            # إرسال رسالة انتظار للمستخدم
            msg = await update.message.reply_text(f"🔍 جاري البحث عن أغنية **{song_query}** وتحميلها...")
            
            # إجراء عملية البحث والتحميل
            file_path, title = await search_and_download_song(song_query)
            
            if file_path and os.path.exists(file_path):
                await msg.edit_text("⚡ جاري إرسال الملف الصوتي...")
                with open(file_path, 'rb') as audio:
                    await update.message.reply_audio(
                        audio=audio,
                        title=title,
                        caption=f"🎧 تم التحميل بواسطة **لارا**\nطلب: {user.first_name}"
                    )
                await msg.delete()
                # حذف الملف من السيرفر لتوفير المساحة
                os.remove(file_path)
                return ""
            else:
                await msg.edit_text("❌ عذراً، لم أتمكن من العثور على الأغنية أو حدث خطأ أثناء التحميل.")
                return ""

        async with AsyncSessionLocal() as session:
            user_repo = UserRepository(session)
            group_repo = GroupRepository(session)
            response_repo = CustomResponseRepository(session)

            db_user = await user_repo.get_or_create(user.id, user.username, user.first_name)
            db_group = await group_repo.get_or_create(chat.id, chat.title or "خاص")
            await group_repo.add_or_update_member(db_group.id, db_user.id)

            # لوحة الإدارة: إضافة رد تلقائي
            if user.id in ADMIN_IDS and text.startswith("/add_response"):
                try:
                    payload = text.replace("/add_response", "").strip()
                    parts = payload.split("|")
                    trigger = parts[0].strip()
                    response_text = parts[1].strip()
                    await response_repo.add_or_update_response(trigger, response_text)
                    return f"✅ تم إضافه/تحديث الرد التلقائي: **{trigger}**"
                except Exception:
                    return "⚠️ الصيغة: `/add_response الكلمة | الرد`"

            # الردود التلقائية
            db_custom_response = await response_repo.get_response(text)
            if db_custom_response:
                return db_custom_response

            if text in ["الاوامر", "أوامر", "تعليمات", "/help"]:
                return COMMANDS_GUIDE

            if text == "/buy_premium":
                await send_stars_invoice(update, context)
                return ""

            # أوامر الإشراف
            if text in ["حظر", "احظر"]:
                if update.message.reply_to_message:
                    target_id = update.message.reply_to_message.from_user.id
                    target_name = update.message.reply_to_message.from_user.first_name
                    success = await ban_user_in_telegram(update, context, target_id)
                    return f"🚫 تم حظر {target_name}" if success else "❌ فشل الحظر."
                return "⚠️ قم بالرد على رسالة الشخص المراد حظره."

            elif text in ["كتم", "اسكت"]:
                if update.message.reply_to_message:
                    target_id = update.message.reply_to_message.from_user.id
                    target_name = update.message.reply_to_message.from_user.first_name
                    success = await mute_user_in_telegram(update, context, target_id)
                    return f"🔇 تم كتم {target_name}" if success else "❌ فشل الكتم."
                return "⚠️ قم بالرد على رسالة الشخص المراد كتمه."

            elif text in ["فك حظر", "فك الكتم"]:
                if update.message.reply_to_message:
                    target_id = update.message.reply_to_message.from_user.id
                    success = await unban_user_in_telegram(update, context, target_id)
                    return "✅ تم فك الحظر/الكتم" if success else "❌ فشل الإجراء."

            elif text in ["ايدي", "معلومات"]:
                return f"ℹ️ **بيانات الحساب:**\n• الاسم: {user.first_name}\n• ID: `{user.id}`\n• المجموعة: {chat.title}"

            return ""
