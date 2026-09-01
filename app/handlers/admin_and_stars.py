import logging
from telegram import Update, LabeledPrice
from telegram.ext import ContextTypes
from config.settings import settings

logger = logging.getLogger(__name__)

# قائمة الأوامر والدليل الكامل لـ لارا
COMMANDS_GUIDE = """
🤖 **أهلاً بك! أنا لارا - بوت الإشراف والتنظيم الذكي**

📌 **دليل الأوامر الإشرافية المتاحة للجميع:**
• `احظر` أو `حظر` (بالرد): حظر العضو من المجموعة.
• `كتم` أو `اسكت` (بالرد): منع العضو من إرسال الرسائل.
• `فك حظر` (بالرد): إلغاء الحظر أو الكتم عن العضو.
• `معلومات` أو `ايدي`: عرض بياناتك وبيانات المجموعة.

⭐ **الميزات المدفوعة (تفعيل عبر نجوم تليجرام):**
• الردود التلقائية المخصصة بدون حدود.
• نظام الفلترة الذكية للروابط والإعلانات.
• لتفعيل الميزات المدفوعة أرسل: `/buy_premium`
"""

async def welcome_new_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال دليل الأوامر فور إضافة البوت لمجموعة جديدة"""
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            await update.message.reply_text(COMMANDS_GUIDE, parse_mode="Markdown")

async def send_stars_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال فاتورة دفع بنجوم تليجرام لشراء الميزات المدفوعة"""
    chat_id = update.effective_chat.id
    title = "تفعيل لارا بريميوم للمجموعة"
    description = "تفعيل الردود التلقائية المخصصة والفلترة المتقدمة لمدة شهر"
    payload = f"group_premium_{chat_id}"
    currency = "XTR"  # رمز نجوم تليجرام (Telegram Stars)
    prices = [LabeledPrice("الاشتراك الشهري", 50)]  # 50 نجمة تليجرام

    await context.bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",  # يترك فارغاً لنجوم تليجرام
        currency=currency,
        prices=prices
    )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """الموافقة الفورية على الدفع بالنجوم"""
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تفعيل الميزة للمجموعة فور نجاح عملية الدفع"""
    await update.message.reply_text("🎉 تم استلام 50 نجمة بنجاح! تم تفعيل ميزات لارا بريميوم لهذه المجموعة.")
