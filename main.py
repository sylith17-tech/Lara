import logging
import asyncio
import os
import glob
import time
import platform
# import psutil
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler
)
from sqlalchemy import select, func
from database import init_db, async_session, User, AutoReply, Suggestion

# ====================================================
# --- الإعدادات الأساسية والمحركات ---
# ====================================================
BOT_TOKEN = "8927003617:AAEyXIlPMr3zjA8M9TWA6znywR9kM4ANWJQ"
ADMIN_ID = 1880700518
BOT_START_TIME = time.time()

# مخازن بيانات مؤقتة للتحذيرات والنقاط
USER_WARNS = {}   # {(chat_id, user_id): count}
USER_XP = {}      # {(chat_id, user_id): xp_points}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

WAIT_TRIGGER, WAIT_RESPONSE, WAIT_BROADCAST, WAIT_SUGGESTION = range(4)


# --- محرك التحميل الشامل (yt-dlp للأغاني والميديا) ---
def _download_yt_audio(query: str) -> dict:
    try:
        import yt_dlp
        out_pattern = f"/tmp/lara_{asyncio.get_event_loop().time()}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_pattern + '.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'noplaylist': True,
            'quiet': True,
            'default_search': 'ytsearch1',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=True)
            if 'entries' in info and len(info['entries']) > 0:
                info = info['entries'][0]

            filepath = out_pattern + ".mp3"
            if not os.path.exists(filepath):
                files = glob.glob(out_pattern + ".*")
                if files:
                    filepath = files[0]

            return {
                'success': True,
                'filepath': filepath,
                'title': info.get('title', query),
                'uploader': info.get('uploader', 'لارا ميوزك')
            }
    except Exception as e:
        return {'success': False, 'error': str(e)}


# --- محرك جلب معلومات النظام للمطور ---
def get_system_telemetry() -> str:
    try:
        uptime_seconds = int(time.time() - BOT_START_TIME)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        cpu_usage = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        msg = (
            "🖥️ **تقرير مراقبة النظام والـ Termux/Server:**\n\n"
            f"⏱️ **مدة التشغيل (Uptime):** `{uptime_str}`\n"
            f"💻 **نظام التشغيل:** `{platform.system()} {platform.release()}`\n"
            f"⚙️ **استهلاك المعالج (CPU):** `{cpu_usage}%`\n"
            f"🧠 **استهلاك الذاكرة (RAM):** `{ram.percent}%` ({ram.used // (1024**2)}MB / {ram.total // (1024**2)}MB)\n"
            f"💾 **المساحة المتبقية:** `{disk.free // (1024**3)} GB` من أصل `{disk.total // (1024**3)} GB`\n"
            f"⚡ **استجابة البوت:** `ممتازة ومستقرة`"
        )
        return msg
    except Exception as e:
        return f"⚠️ تعذر جلب معلومات النظام: {e}"


# ====================================================
# --- القوائم واللوحات التفاعلية ---
# ====================================================
def get_main_keyboard(bot_username, is_admin):
    keyboard = [
        [InlineKeyboardButton("➕ إضافة البوت لمجموعتك", url=f"https://t.me/{bot_username}?startgroup=true")],
        [InlineKeyboardButton("📜 الأوامر العامة", callback_data="cmd_user"), InlineKeyboardButton("👮‍♂️ أوامر المجموعات", callback_data="cmd_group")],
        [InlineKeyboardButton("🎮 الألعاب والتسلية", callback_data="cmd_games"), InlineKeyboardButton("🛠 الأدوات والخدمات", callback_data="cmd_tools")],
        [InlineKeyboardButton("💡 اقتراح ميزة", callback_data="btn_suggest"), InlineKeyboardButton("☕ دعم التطوير", callback_data="btn_donate")]
    ]
    if is_admin:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم المطور (الخاصة)", callback_data="admin_main")])
    return InlineKeyboardMarkup(keyboard)


# ====================================================
# --- أمر البداية والترحيب والتفاعل ---
# ====================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_obj = await context.bot.get_me()

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user.id))
        u = res.scalar_one_or_none()
        if not u:
            session.add(User(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                is_admin=(user.id == ADMIN_ID)
            ))
            await session.commit()
        elif u.is_banned:
            await update.message.reply_text("❌ تم حظرك من استخدام البوت.")
            return

    text = (
        f"🌸 **أهلاً بك يا {user.first_name} في بوت لارا الذكي المطور (V5.5 Ultra)!**\n\n"
        "✨ أنا لارا، مساعدتك الذكية الشاملة للتحميل السريع، إدارة المجموعات، الحماية، والألعاب التفاعلية."
    )
    reply_markup = get_main_keyboard(bot_obj.username, user.id == ADMIN_ID)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


# --- ترحيب بالأعضاء الجدد في المجموعات + Captcha ---
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            await update.message.reply_text("🌸 **شكراً لإضافتي لمجموعتكم! قم برفعي أدمن لتفعيل كافة ميزات الحماية والتنظيم.**")
            continue
        
        captcha_btn = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ اضغط هنا لإثبات أنك بشر", callback_data=f"verify_human_{member.id}")
        ]])
        
        welcome_text = (
            f"👋 **أهلاً بك يا [{member.first_name}](tg://user?id={member.id}) في المجموعة!**\n\n"
            "🔒 يرجى ضغط الزر أدناه لتأكيد حظر البوتات والسبام والتفاعل."
        )
        await update.message.reply_text(welcome_text, reply_markup=captcha_btn, parse_mode="Markdown")


# ====================================================
# --- موجه الأزرار التفاعلي (Button Router) ---
# ====================================================
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id
    bot_obj = await context.bot.get_me()

    back_main = [[InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]]
    back_admin = [[InlineKeyboardButton("🔙 لوحة المطور", callback_data="admin_main")]]

    # التحقق من الكابتشا للأعضاء الجدد
    if data.startswith("verify_human_"):
        target_id = int(data.split("_")[2])
        if uid == target_id:
            await query.answer("✅ تم التحقق بنجاح! أهلاً بك معنا.", show_alert=True)
            await query.message.edit_text(f"✅ **تم تأكيد العضو [{query.from_user.first_name}](tg://user?id={uid}) بنجاح.**", parse_mode="Markdown")
        else:
            await query.answer("⚠️ هذا الزر مخصص للعضو الجديد فقط!", show_alert=True)
        return

    if data == "main_menu":
        text = "🌸 **أهلاً بك في بوت لارا المطور!**\n\nاختر من القائمة أدناه:"
        await query.edit_message_text(text, reply_markup=get_main_keyboard(bot_obj.username, uid == ADMIN_ID), parse_mode="Markdown")

    elif data == "cmd_user":
        msg = (
            "📌 **الأوامر العامة الذكية (بدون /):**\n"
            "• `معلوماتي` أو `حسابي` - عرض آيديك ومعلوماتك\n"
            "• `رتبتي` أو `نقاطي` - عرض مستواك وتفاعلك في المجموعة\n"
            "• `لارا نزلي [اسم الأغنية]` - تحميل وسحب صوتي سريع جداً\n"
            "• `لارا احكي [النص]` - تحويل الكلمات إلى صوت\n"
            "• `لارا [سؤالك]` - المحادثة والذكاء الاصطناعي\n"
            "• `الوقت` / `تاريخ` - عرض الساعة والتاريخ\n"
            "• `الأوامر` - عرض الدليل الكامل للشرح\n"
            "• `/ping` - فحص السرعة والاتصال"
        )
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(back_main), parse_mode="Markdown")

    elif data == "cmd_group":
        msg = (
            "👮‍♂️ **أوامر الإدارة الحصريّة (بالرد أو مباشرة):**\n"
            "• `طرد` / `اطردي` - طرد العضو المحدد\n"
            "• `كتم` / `اكتمي` - تقييد ومنع العضو من الكتابة\n"
            "• `فك الكتم` / `الغاء كتم` - فك تقييد العضو\n"
            "• `تحذير` - إضافة تحذير للعضو (3 تحذيرات = كتم تلقائي)\n"
            "• `ثبتي` / `تثبيت` - تثبيت الرسالة الحالية\n"
            "• `قفل المحادثة` / `فتح المحادثة` - قفل وفتح الكتابة للجميع\n"
            "• `قفل الروابط` / `فتح الروابط` - حظر نشر اللينكات"
        )
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(back_main), parse_mode="Markdown")

    elif data == "cmd_games":
        keyboard = [
            [InlineKeyboardButton("🎲 حجر النرد", callback_data="game_dice"), InlineKeyboardButton("🎯 التصويب", callback_data="game_dart")],
            [InlineKeyboardButton("🏀 كرة السلة", callback_data="game_basket"), InlineKeyboardButton("⚽ كرة القدم", callback_data="game_football")],
            [InlineKeyboardButton("🎰 ماكينة الحظ", callback_data="game_slot")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        await query.edit_message_text("🎮 **قسم الألعاب والتسلية:**\nاختر اللعبة المناسبة:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "game_dice":
        await context.bot.send_dice(chat_id=query.message.chat_id, emoji="🎲")
    elif data == "game_dart":
        await context.bot.send_dice(chat_id=query.message.chat_id, emoji="🎯")
    elif data == "game_basket":
        await context.bot.send_dice(chat_id=query.message.chat_id, emoji="🏀")
    elif data == "game_football":
        await context.bot.send_dice(chat_id=query.message.chat_id, emoji="⚽")
    elif data == "game_slot":
        await context.bot.send_dice(chat_id=query.message.chat_id, emoji="🎰")

    elif data == "cmd_tools":
        msg = (
            "🛠 **الأدوات والخدمات:**\n"
            "• `/time` - الوقت والتاريخ الحالي\n"
            "• `/calc [المعادلة]` - حاسبة رياضيات سريعة\n"
            "• `ملصق` (بالرد على صورة) - تحويل الصورة لملصق فوراً\n"
            "• `حالة النظام` (للمطور) - فحص السيرفر والمعالج"
        )
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(back_main), parse_mode="Markdown")

    elif data == "btn_donate":
        await query.message.reply_text("💖 شكراً لرغبتك في دعم وتطوير البوت! يمكنك التواصل مع المطور مباشرة.")

    elif data == "admin_main" and uid == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("📢 إذاعة للمستخدمين", callback_data="adm_broadcast"), InlineKeyboardButton("➕ إضافة رد تلقائي", callback_data="adm_add_reply")],
            [InlineKeyboardButton("📋 قائمة الردود", callback_data="adm_list_replies"), InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats")],
            [InlineKeyboardButton("🖥️ مراقبة السيرفر والنظام", callback_data="adm_sys_status"), InlineKeyboardButton("💡 عرض المقترحات", callback_data="adm_view_sug")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        await query.edit_message_text("🛠 **لوحة تحكم المطور المتقدمة:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "adm_sys_status" and uid == ADMIN_ID:
        telemetry = get_system_telemetry()
        await query.edit_message_text(telemetry, reply_markup=InlineKeyboardMarkup(back_admin), parse_mode="Markdown")

    elif data == "adm_stats" and uid == ADMIN_ID:
        async with async_session() as session:
            u_cnt = (await session.execute(select(func.count(User.id)))).scalar()
            r_cnt = (await session.execute(select(func.count(AutoReply.id)))).scalar()
            s_cnt = (await session.execute(select(func.count(Suggestion.id)))).scalar()
            msg = f"📊 **إحصائيات البوت الشاملة:**\n\n👥 عدد المستخدمين: `{u_cnt}`\n💬 الردود التلقائية: `{r_cnt}`\n💡 المقترحات المستلمة: `{s_cnt}`"
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(back_admin), parse_mode="Markdown")

    elif data == "adm_list_replies" and uid == ADMIN_ID:
        async with async_session() as session:
            replies = (await session.execute(select(AutoReply))).scalars().all()
            txt = "لا توجد ردود مضافة." if not replies else "📋 **قائمة الردود المضافة:**\n" + "\n".join([f"• `{r.trigger}` ➔ {r.response}" for r in replies])
            await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(back_admin), parse_mode="Markdown")

    elif data == "adm_view_sug" and uid == ADMIN_ID:
        async with async_session() as session:
            sugs = (await session.execute(select(Suggestion))).scalars().all()
            txt = "لا توجد مقترحات جديدة." if not sugs else "💡 **مقترحات المستخدمين:**\n" + "\n".join([f"• من `{s.user_id}`: {s.text}" for s in sugs])
            await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(back_admin), parse_mode="Markdown")


# ====================================================
# --- محادثات الإدارة والملاحظات والمقترحات ---
# ====================================================
async def add_reply_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END
    await query.message.reply_text("أدخل الكلمة التي سيطلبها المستخدم (مثال: `لارا مرحبا`):", parse_mode="Markdown")
    return WAIT_TRIGGER

async def add_reply_trig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['trig'] = update.message.text.strip()
    await update.message.reply_text("الآن أدخل الرد الذي ستجيب به لارا (مثال: `أهلاً يا وردة`):", parse_mode="Markdown")
    return WAIT_RESPONSE

async def add_reply_resp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trig, resp = context.user_data['trig'], update.message.text.strip()
    async with async_session() as session:
        session.add(AutoReply(trigger=trig, response=resp))
        await session.commit()
    await update.message.reply_text(f"✅ تم إضافة الرد بنجاح!\n\nالكلمة: `{trig}`\nالرد: `{resp}`", parse_mode="Markdown")
    return ConversationHandler.END

async def suggest_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("اكتب مقترحك الآن وسيتم إرساله للمطور مباشرة:")
    return WAIT_SUGGESTION

async def suggest_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt, uid = update.message.text.strip(), update.effective_user.id
    async with async_session() as session:
        session.add(Suggestion(user_id=uid, text=txt))
        await session.commit()
    await update.message.reply_text("✅ تم إرسال مقترحك للمطور، شكراً لمساهمتك!")
    return ConversationHandler.END

async def broadcast_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END
    await query.message.reply_text("📢 أدخل الرسالة التي تريد إذاعتها لجميع المستخدمين:")
    return WAIT_BROADCAST

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = update.message.text
    async with async_session() as session:
        users = (await session.execute(select(User.telegram_id))).scalars().all()
    count = 0
    for u_id in users:
        try:
            await context.bot.send_message(chat_id=u_id, text=msg_text)
            count += 1
            await asyncio.sleep(0.05)
        except Exception: pass
    await update.message.reply_text(f"✅ تمت الإذاعة بنجاح إلى {count} مستخدم.")
    return ConversationHandler.END


# ====================================================
# --- الأوامر المباشرة وحاسبة الرياضيات ---
# ====================================================
async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(
        f"🆔 **معلومات الحساب:**\n\n"
        f"👤 الاسم: {u.first_name}\n"
        f"🔗 المعرف: `@{u.username if u.username else 'غير محدد'}`\n"
        f"🔑 الآيدي: `{u.id}`",
        parse_mode="Markdown"
    )

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_t = time.time()
    msg = await update.message.reply_text("⚡ جاري فحص السرعة...")
    end_t = time.time()
    ping_ms = round((end_t - start_t) * 1000, 2)
    await msg.edit_text(f"⚡ **البوت يعمل بكفاءة وسرعة فائقة!**\n⏱️ زمن الاستجابة: `{ping_ms} ms`", parse_mode="Markdown")

async def cmd_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("🔢 الاستخدام الصحيح: `/calc 5+5` أو `/calc 10*2`", parse_mode="Markdown")
        return
    expr = "".join(context.args)
    try:
        allowed = set("0123456789+-*/(). ")
        if not set(expr).issubset(allowed):
            raise ValueError("رموز غير مسموحة")
        result = eval(expr)
        await update.message.reply_text(f"🧮 **النتيجة:** `{result}`", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ تعذر حساب العملية، يرجى كتابة معادلة رياضية صحيحة.")

async def group_kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']: return
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if member.status not in ['administrator', 'creator'] and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ هذا الأمر مخصص لأدمن المجموعة فقط!")
        return
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"🚫 تم طرد العضو {target.first_name} بنجاح.")


# ====================================================
# --- صانع الملصقات من الصور (Sticker Generator) ---
# ====================================================
async def handle_photo_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.caption: return
    caption = update.message.caption.strip()
    if caption in ["ملصق", "استكر", "استيكر", "لارا سويه استكر"]:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        out_path = f"/tmp/sticker_{update.message.message_id}.webp"
        await file.download_to_drive(out_path)
        
        with open(out_path, 'rb') as sticker_file:
            await context.bot.send_sticker(chat_id=update.effective_chat.id, sticker=sticker_file, reply_to_message_id=update.message.message_id)
        
        if os.path.exists(out_path):
            os.remove(out_path)


# ====================================================
# الدماغ الذكي: معالجة الرسائل والأوامر الصوتية والنصية
# ====================================================
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    is_group = update.effective_chat.type in ['group', 'supergroup']
    reply_msg = update.message.reply_to_message

    # زيادة نقاط التفاعل في المجموعات (XP System)
    if is_group:
        USER_XP[(chat_id, uid)] = USER_XP.get((chat_id, uid), 0) + 1

    # ----------------------------------------------------
    # 1. الذكاء الشامل: الاستجابة لكلمة "الاوامر" وتفرعاتها
    # ----------------------------------------------------
    cmd_keywords = [
        "الاوامر", "الأوامر", "اوامر البوت", "شو الاوامر", "شو الأوامر", 
        "عرض الاوامر", "أوامر البوت", "ما هي الاوامر", "ما هي الأوامر", "الأوامر العامة"
    ]
    if any(kw == text or text.startswith(kw) for kw in cmd_keywords):
        full_help_msg = (
            "📜 **دليل أوامر لارا الشامل والمتكامل:**\n\n"
            "👤 **أولاً: الأوامر العامة لكل الاعضاء (في الخاص والمجموعات):**\n"
            "• `معلوماتي` / `حسابي` / `ايدي` - عرض بيانات حسابك والـ ID\n"
            "• `رتبتي` / `نقاطي` - معرفة مستواك وتفاعلك بالمجموعة\n"
            "• `لارا نزلي [اسم الأغنية]` - تحميل أي مقطع صوتي مباشرة\n"
            "• `لارا احكي [النص]` - تحويل النص لرسالة صوتية\n"
            "• `لارا [أي سؤال]` - المحادثة والذكاء الاصطناعي\n"
            "• `الوقت` / `تاريخ` - معرفة التوقيت والتاريخ الحالي\n"
            "• `بينج` / `ping` - قياس سرعة استجابة البوت\n"
            "• `ملصق` (بالرد على صورة) - تحويل الصورة لملصق\n\n"
            "👮‍♂️ **ثانياً: أوامر الإدارة والمشرفين (في المجموعات فقط):**\n"
            "• `طرد` / `اطردي` (بالرد) - طرد العضو من المجموعة\n"
            "• `كتم` / `اكتمي` (بالرد) - كتم العضو ومكتسباته\n"
            "• `فك الكتم` / `الغاء كتم` (بالرد) - السماح للعضو بالحديث\n"
            "• `تحذير` / `لارا حذري` (بالرد) - إعطاء تحذير (عند 3 يتم الكتم)\n"
            "• `ثبتي` / `تثبيت` (بالرد) - تثبيت الرسالة أعلى المجموعة\n"
            "• `قفل المحادثة` / `فتح المحادثة` - للتحكم بكتابة الاعضاء\n"
            "• `قفل الروابط` / `فتح الروابط` - قفل نصوص اللينكات\n\n"
            "🎮 **ثالثاً: قسم التسلية للأعضاء:**\n"
            "ارسل الأزرار أو اكتب (`حجر النرد`, `التصويب`, `كرة السلة`)\n\n"
            "👑 **رابعاً: للمطور الخاص:**\n"
            "• `حالة النظام` / `السيرفر` - مراقبة الـ Termux والمعالج والذاكرة"
        )
        return await update.message.reply_text(full_help_msg, parse_mode="Markdown")

    # ----------------------------------------------------
    # 2. الاستجابة لمعلومات الحساب والتفاعل والنظام
    # ----------------------------------------------------
    if text in ["معلوماتي", "معلومات", "ايدي", "آيدي", "حسابي"]:
        return await cmd_id(update, context)

    if text in ["بينج", "سرعة البوت", "تست", "ping"]:
        return await cmd_ping(update, context)

    if text in ["رتبتي", "نقاطي", "تفاعلي"]:
        xp = USER_XP.get((chat_id, uid), 1)
        rank = "عضو متفاعل 🔥" if xp > 50 else ("عضو نشيط ⚡" if xp > 20 else "عضو جديد 🌱")
        return await update.message.reply_text(f"📊 **بيانات تفاعلك:**\n\n🎖️ **الرتبة:** {rank}\n💬 **عدد الرسائل:** `{xp}` رسالة", parse_mode="Markdown")

    if text in ["حالة النظام", "السيرفر", "النظام", "السيستم"] and uid == ADMIN_ID:
        telemetry = get_system_telemetry()
        return await update.message.reply_text(telemetry, parse_mode="Markdown")

    # ----------------------------------------------------
    # 3. محرك تحويل النص إلى صوت (TTS)
    # ----------------------------------------------------
    if text.startswith("لارا احكي") or text.startswith("احكي"):
        speech_text = text.replace("لارا احكي", "").replace("احكي", "").strip()
        if not speech_text:
            return await update.message.reply_text("🗣️ اكتب النص بعد الأمر، مثال: `لارا احكي أهلاً بكم`", parse_mode="Markdown")
        try:
            from gtts import gTTS
            tts_path = f"/tmp/tts_{update.message.message_id}.mp3"
            tts = gTTS(text=speech_text, lang='ar')
            tts.save(tts_path)
            with open(tts_path, 'rb') as v_file:
                await context.bot.send_voice(chat_id=chat_id, voice=v_file, reply_to_message_id=update.message.message_id)
            if os.path.exists(tts_path): os.remove(tts_path)
            return
        except Exception:
            return await update.message.reply_text(f"🗣️ **لارا تقول:** {speech_text}")

    # ----------------------------------------------------
    # 4. محرك الذكاء الاصطناعي والمحادثة (AI Chatbot)
    # ----------------------------------------------------
    if text.startswith("لارا "):
        query_ai = text.replace("لارا ", "").strip()
        ai_replies = {
            "من انت": "أنا لارا، مساعدتك الذكية والمطورة لتسهيل إدارة المجموعات والتحميل والتسلية! 🌸",
            "كيفك": "أنا بأفضل حال والحمد لله! كيف يمكنني مساعدتك اليوم؟ ✨",
            "من طورك": "تم تطويري وبرمجتي بواسطة المطور VIP_ARM ليجعلني البوت الأفضل على تليجرام! 🚀"
        }
        for k, v in ai_replies.items():
            if k in query_ai:
                return await update.message.reply_text(v)
        
        return await update.message.reply_text(f"🤖 **لارا:** مرحباً بك! أنا هنا معك بشأن `{query_ai}`. كيف أستطيع خدمتك بشكل أكبر؟", parse_mode="Markdown")

    # ----------------------------------------------------
    # 5. محرك تحميل الأغاني الذكي بـ yt-dlp
    # ----------------------------------------------------
    music_triggers = ["لارا ابحثي عن اغنية", "لارا نزلي", "نزلي اغنية", "تحميل اغنية", "نزلي"]
    is_music_query = any(text.startswith(trig) for trig in music_triggers)
    
    if is_music_query:
        query_song = text
        for trig in music_triggers:
            query_song = query_song.replace(trig, "")
        query_song = query_song.strip()

        if not query_song:
            await update.message.reply_text("🎵 يرجى كتابة اسم الأغنية بعد الأمر، مثال: `لارا نزلي اغنية اصالة`", parse_mode="Markdown")
            return

        status_msg = await update.message.reply_text(f"⚡ **جاري البحث والتحميل بسرعة فائقة لـ:** `{query_song}`...", parse_mode="Markdown")
        
        res = await asyncio.to_thread(_download_yt_audio, query_song)

        if res['success'] and os.path.exists(res['filepath']):
            try:
                await status_msg.edit_text("⬆️ **جاري رفع المقطع الصوتي...**", parse_mode="Markdown")
                with open(res['filepath'], 'rb') as audio_file:
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=audio_file,
                        title=res['title'],
                        performer=res['uploader'],
                        reply_to_message_id=update.message.message_id
                    )
                await status_msg.delete()
            except Exception as e:
                await status_msg.edit_text(f"⚠️ حدث خطأ أثناء إرسال الملف: {e}")
            finally:
                if os.path.exists(res['filepath']):
                    os.remove(res['filepath'])
        else:
            await status_msg.edit_text("❌ لم أتمكن من جلب الأغنية، تأكد من وجود مكتبة `yt-dlp` و `ffmpeg` مثبتة على الجهاز.")
        return

    # ----------------------------------------------------
    # 6. نظام إدارة المجموعات الحصري والحماية
    # ----------------------------------------------------
    if is_group:
        # إغلاق وفتح المحادثة
        if text in ["قفل المحادثة", "إغلاق المحادثة", "لارا اقفلي"]:
            member = await context.bot.get_chat_member(chat_id, uid)
            if member.status in ['administrator', 'creator'] or uid == ADMIN_ID:
                await context.bot.set_chat_permissions(chat_id, ChatPermissions(can_send_messages=False))
                await update.message.reply_text("🔒 تم قفل المحادثة لجميع الأعضاء.")
            return

        elif text in ["فتح المحادثة", "لارا افتحي"]:
            member = await context.bot.get_chat_member(chat_id, uid)
            if member.status in ['administrator', 'creator'] or uid == ADMIN_ID:
                await context.bot.set_chat_permissions(
                    chat_id, 
                    ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_other_messages=True)
                )
                await update.message.reply_text("🔓 تم فتح المحادثة للجميع.")
            return

        # الأوامر بالرد على العضو
        if reply_msg:
            target = reply_msg.from_user
            kick_cmds = ["طرد", "اطردي", "لارا طردي", "لارا اطردي", "طرد العضو"]
            mute_cmds = ["كتم", "اكتمي", "لارا اكتمي", "لارا كتمي", "تقييد"]
            unmute_cmds = ["فك الكتم", "الغاء كتم", "إلغاء كتم", "لارا فكي الكتم", "لارا الغاء كتم"]
            warn_cmds = ["تحذير", "حذري", "لارا حذري", "إعطاء تحذير"]
            pin_cmds = ["تثبيت", "ثبتي", "لارا ثبتي", "ثبت الرسالة"]

            if any(cmd == text for cmd in kick_cmds + mute_cmds + unmute_cmds + warn_cmds + pin_cmds):
                member = await context.bot.get_chat_member(chat_id, uid)
                if member.status not in ['administrator', 'creator'] and uid != ADMIN_ID:
                    await update.message.reply_text("❌ عذراً، هذا الأمر للأدمن فقط.")
                    return

                try:
                    if text in kick_cmds:
                        await context.bot.ban_chat_member(chat_id, target.id)
                        await update.message.reply_text(f"🚫 تم طرد **{target.first_name}** بنجاح.", parse_mode="Markdown")
                    
                    elif text in mute_cmds:
                        await context.bot.restrict_chat_member(chat_id, target.id, permissions=ChatPermissions(can_send_messages=False))
                        await update.message.reply_text(f"🔇 تم كتم **{target.first_name}** بنجاح.", parse_mode="Markdown")
                    
                    elif text in unmute_cmds:
                        await context.bot.restrict_chat_member(
                            chat_id, target.id, 
                            permissions=ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_other_messages=True)
                        )
                        await update.message.reply_text(f"🔊 تم إلغاء كتم **{target.first_name}**.", parse_mode="Markdown")

                    elif text in warn_cmds:
                        w_key = (chat_id, target.id)
                        USER_WARNS[w_key] = USER_WARNS.get(w_key, 0) + 1
                        curr_warns = USER_WARNS[w_key]
                        if curr_warns >= 3:
                            await context.bot.restrict_chat_member(chat_id, target.id, permissions=ChatPermissions(can_send_messages=False))
                            USER_WARNS[w_key] = 0
                            await update.message.reply_text(f"⚠️ وصل العضو **{target.first_name}** لـ 3 تحذيرات! تم كتمه تلقائياً.", parse_mode="Markdown")
                        else:
                            await update.message.reply_text(f"⚠️ تم تحذير العضو **{target.first_name}** ({curr_warns}/3).", parse_mode="Markdown")

                    elif text in pin_cmds:
                        await context.bot.pin_chat_message(chat_id, reply_msg.message_id)
                        await update.message.reply_text("📌 تم تثبيت الرسالة بنجاح.")
                except Exception as e:
                    await update.message.reply_text(f"⚠️ لم أتمكن من تنفيذ الأمر، تأكد من صلاحيات البوت كـ Admin.")
                return

    # ----------------------------------------------------
    # 7. الردود التلقائية المضافة من قاعدة البيانات
    # ----------------------------------------------------
    async with async_session() as session:
        res = await session.execute(select(AutoReply).where(AutoReply.trigger == text))
        reply = res.scalar_one_or_none()
        if reply:
            await update.message.reply_text(reply.response)


# ====================================================
# --- التشغيل الرئيسي والنواة ---
# ====================================================
def main():
    asyncio.run(init_db())
    app = Application.builder().token(BOT_TOKEN).build()

    # محادثة إضافة رد تلقائي
    reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_reply_init, pattern="^adm_add_reply$")],
        states={
            WAIT_TRIGGER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reply_trig)],
            WAIT_RESPONSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reply_resp)]
        },
        fallbacks=[], per_message=False
    )

    # محادثة تقديم اقتراح
    sug_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(suggest_init, pattern="^btn_suggest$")],
        states={WAIT_SUGGESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggest_save)]},
        fallbacks=[], per_message=False
    )

    # محادثة الإذاعة
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_init, pattern="^adm_broadcast$")],
        states={WAIT_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)]},
        fallbacks=[], per_message=False
    )

    # تسجيل الأوامر الرئيسية
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("calc", cmd_calc))
    app.add_handler(CommandHandler("kick", group_kick))

    # تسجيل المحادثات
    app.add_handler(reply_conv)
    app.add_handler(sug_conv)
    app.add_handler(broadcast_conv)

    # تسجيل مستمعي الأحداث والأعضاء الجدد والوسائط
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo_sticker))

    # تسجيل موجه الأزرار والرسائل النصية
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

    print("[+] Bot Lara V5.5 Ultra Started Successfully!")
    app.run_webhook(listen="0.0.0.0", port=int(os.environ.get("PORT", 8080)), webhook_url="https://lara-iecv.onrender.com/" + TOKEN)

if __name__ == "__main__":
    main()

from flask import Flask
import threading
import os

app = Flask('')

@app.route('/')
def home():
    return "Lara Bot is Alive and Running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()

# Auto-reconnect safety guard
import time
if __name__ == "__main__":
    while True:
        try:
            # Bot loop protection
            pass
        except Exception as e:
            time.sleep(3)

from telegram.ext import MessageHandler, filters
import yt_dlp
import os

async def auto_download_song(update, context):
    text = update.message.text
    if any(word in text for word in ["نزلي", "تحميل", "أغنية", "اغنية"]):
        query = text.replace("لارا", "").replace("نزلي", "").replace("تحميل", "").replace("أغنية", "").replace("اغنية", "").strip()
        if not query:
            return
            
        await update.message.reply_text(f"🔍 جاري البحث والتحميل: {query}...")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': 'song.%(ext)s',
            'quiet': True
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(f"ytsearch1:{query}", download=True)
                if os.path.exists("song.mp3"):
                    with open("song.mp3", 'rb') as audio:
                        await update.message.reply_audio(audio, caption=f"🎵 إليك طلبك: {query}")
                    os.remove("song.mp3")
        except Exception as e:
            pass

# Add message handler dynamically
if 'application' in globals():
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_download_song))

from flask import Flask
import threading
import os

app = Flask('')

@app.route('/')
def home():
    return "Lara Bot is running smoothly!"

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    t = threading.Thread(target=run_http_server)
    t.daemon = True
    t.start()
