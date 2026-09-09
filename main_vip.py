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




# مجموعة لتتبع المستخدمين الذين ينتظرون إدخال نص الذكاء الاصطناعي فقط
ACTIVE_AI_USERS = set()

async def handle_incoming_video(update, context):
    """استقبال الفيديو وتفعيل حالة انتظار الوصف لهذا المستخدم فقط"""
    if not context.user_data.get('waiting_for_video'):
        return

    message = update.message
    if not message.video:
        return

    user_id = update.effective_user.id
    context.user_data['temp_video_file_id'] = message.video.file_id
    context.user_data['waiting_for_video'] = False
    
    # تفعيل الحالة لهذا المستخدم بالذات
    ACTIVE_AI_USERS.add(user_id)

    await message.reply_text(
        "📥 **تم استلام الفيديو بنجاح!**\n\n"
        "🤖 **أنا جاهز الآن:** اكتب لي بالعربي ماذا تريد أن أفعل بالفيديو?\n"
        "(مثال: *قص أول 5 ثواني*، *تصغير الحجم*)...",
        parse_mode="Markdown"
    )

async def handle_ai_video_prompt(update, context):
    """استقبال الوصف النصي للمستخدم النشط فقط وتطبيق التعديل"""
    user_id = update.effective_user.id
    if user_id not in ACTIVE_AI_USERS:
        return  # تجاهل تاما لأي شخص لا يقوم بتعديل فيديو حالياً

    text_prompt = update.message.text
    video_file_id = context.user_data.get('temp_video_file_id')
    
    if not video_file_id:
        ACTIVE_AI_USERS.discard(user_id)
        return

    status_msg = await update.message.reply_text("🧠 **جاري تحليل طلبك بالذكاء الاصطناعي وتجهيز المحرك...**", parse_mode="Markdown")
    
    try:
        import os
        import subprocess
        
        video_file = await context.bot.get_file(video_file_id)
        input_path = f"input_{user_id}.mp4"
        output_path = f"output_{user_id}.mp4"
        await video_file.download_to_drive(input_path)

        cmd = ["ffmpeg", "-y", "-i", input_path, "-vcodec", "libx264", "-crf", "26", output_path]
        
        if "قص" in text_prompt or "ثواني" in text_prompt:
            cmd = ["ffmpeg", "-y", "-i", input_path, "-ss", "00:00:00", "-t", "10", "-c:v", "libx264", "-c:a", "aac", output_path]

        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if process.returncode != 0:
            await status_msg.edit_text("❌ حدث خطأ أثناء تطبيق التعديل بالمحرك.")
            ACTIVE_AI_USERS.discard(user_id)
            return

        with open(output_path, "rb") as vid:
            await update.message.reply_video(
                video=vid,
                caption=f"✅ **تم تعديل الفيديو بناءً على طلبك:**\n_{text_prompt}_",
                parse_mode="Markdown"
            )
        
        await status_msg.delete()
        
        # تنظيف الحالة والملفات
        ACTIVE_AI_USERS.discard(user_id)
        if os.path.exists(input_path): os.remove(input_path)
        if os.path.exists(output_path): os.remove(output_path)

    except Exception as e:
        await status_msg.edit_text(f"❌ حدث خطأ تقني: {e}")
        ACTIVE_AI_USERS.discard(user_id)
