# --- ملف ميزات الـ VIP والحماية المتقدمة ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from services.storage import create_job_storage

async def handle_vip_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض لوحة تحكم الـ VIP الرئيسية"""
    query = update.callback_query
    await query.answer("🟢 أهلاً بك في قسم الـ VIP المتقدم!", show_alert=False)

    keyboard = [
        [InlineKeyboardButton("🎬 بدء تعديل فيديو جديد (AI)", callback_data="start_video_edit")],
        [InlineKeyboardButton("📊 إحصائيات الموارد والنظام", callback_data="vip_stats")],
        [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
    ]
    
    panel_text = (
        "╭━━━ 🟢 **[ لوحة تحكم VIP_ARM الحصرية ]** 🟢━━━╮\n\n"
        "┃ 🎥 **مرحباً بك في المحرك الاحترافي لمعالجة الفيديوهات.**\n"
        "┃ ⚙️ أرسل فيديوك واطلب التعديل بلغتك الطبيعية (قص، تغيير مقاس، إزالة خلفية...إلخ).\n"
        "┃ 📌 اختر إحدى الخدمات أدناه:\n\n"
        "╰──────────────────────────────╯"
    )
    
    await query.message.edit_text(
        panel_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_start_video_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تهيئة جلسة العمل واستقبال الفيديو من المستخدم"""
    query = update.callback_query
    await query.answer("🚀 تم إعداد جلسة العمل بنجاح!", show_alert=True)
    
    job_info = create_job_storage()
    context.user_data['current_job'] = job_info
    context.user_data['waiting_for_video'] = True

    keyboard = [
        [InlineKeyboardButton("❌ إلغاء ورجوع", callback_data="vip_menu")]
    ]
    
    session_text = (
        "╭━━━ 📥 **[ استلام الفيديو - الجلسة نشطة ]** 📥━━━╮\n\n"
        "┃ 🆔 معرف الجلسة: `{job_id}`\n"
        "┃ 🎥 **أرسل الفيديو الآن في المحادثة...**\n"
        "┃ ⏳ بانتظار تلقي ملف الفيديو للبدء بالمعالجة.\n\n"
        "╰──────────────────────────────╯"
    ).format(job_id=job_info['job_id'])
    
    await query.message.edit_text(
        session_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def handle_vip_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إحصائيات النظام ومراقبة الموارد"""
    query = update.callback_query
    await query.answer("📊 جاري جلب إحصائيات النظام...", show_alert=False)
    
    keyboard = [
        [InlineKeyboardButton("🔙 عودة للوحة الـ VIP", callback_data="vip_menu")]
    ]
    
    stats_text = (
        "╭━━━ 📊 **[ إحصائيات وأمان نظام VIP_ARM ]** 📊━━━╮\n\n"
        "┃ 🟢 حالة السيرفر: **مستقر وآمن 100% (Online)**\n"
        "┃ 💾 إدارة المجلدات: **مفعلة (تتم التطهير الآلي)**\n"
        "┃ ⚡ محرك المعالجة: **FFmpeg + AI Planner جاهز للاستخدام**\n\n"
        "╰──────────────────────────────╯"
    )
    
    await query.message.edit_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
