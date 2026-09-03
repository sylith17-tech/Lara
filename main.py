import threading, http.server, socketserver, os, logging, asyncio, glob, time, random, urllib.request
from datetime import datetime
import platform
import psutil

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
# --- سيرفر وهمي للعمل على Render ---
# ====================================================
def run_dummy_server():
    PORT = int(os.environ.get("PORT", 10000))
    Handler = http.server.SimpleHTTPRequestHandler
    try:
        with socketserver.TCPServer(("", PORT), Handler) as httpd:
            httpd.serve_forever()
    except Exception:
        pass

threading.Thread(target=run_dummy_server, daemon=True).start()

# ====================================================
# --- نظام النبضات للحفاظ على السيرفر نشطاً 24/7 ---
# ====================================================
def keep_alive_ping():
    port = os.environ.get("PORT", 10000)
    url = f"http://127.0.0.1:{port}"
    while True:
        try:
            urllib.request.urlopen(url)
        except Exception:
            pass
        time.sleep(300)

threading.Thread(target=keep_alive_ping, daemon=True).start()

# ====================================================
# --- الإعدادات الأساسية والثوابت ---
# ====================================================
BOT_TOKEN = "8927003617:AAHcYjFSWmIW4ZSfIi-frY5cjxaPFnPss2g"
ADMIN_ID = 1880700518
BOT_START_TIME = time.time()

USER_WARNS = {}   # {(chat_id, user_id): count}
USER_XP = {}      # {(chat_id, user_id): xp_points}
XO_GAMES = {}     # {chat_id: {"board": [...], "turn": "❌", "p1": id}}
TRIVIA_GAMES = {} # {chat_id: {"q": str, "a": str}}

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("VIP_ARM_LEGENDARY")

WAIT_TRIGGER, WAIT_RESPONSE, WAIT_BROADCAST, WAIT_SUGGESTION = range(4)

ROASTS = [
    "يا زلمة لو الغباء يطير كان زمانك قمر صناعي 🛰️😂",
    "وجهك ولا شاشة مكسورة؟ 📱💔",
    "أنت لو يوزنوا عقلك بيطلع أخف من ريشة عصفور 🪶",
    "مفكر حالك حلو؟ روح شوف المراية بتلاقيها عم تبكي 🪞😭",
    "أنا ذكاء اصطناعي بس بصراحة غبائك طبيعي 100% 🤖😂"
]

JOKES = [
    "مرة واحد غبي راح للدكتور، قاله الدكتور: لازم تمشي كل يوم 5 كيلو، بعد شهر اتصل الغبي بالدكتور قاله: أنا هلأ على حدود العراق شو أعمل؟ 😂",
    "في نملة ماتت يوم عرسها ليش؟ ... سكر عليها الباب 😂",
    "محشش سألوه شو رأيك بالزواج المبكر؟ قال: يعني أي ساعة تقريباً؟ 🕒😂",
    "مرة أستاذ رياضيات اتجوز مدرسة رياضيات خلفوا ولد سموه شبه منحرف 📐😂"
]

TRIVIA_QUESTIONS = [
    {"q": "ما هي عاصمة أستراليا؟", "a": "كانبيرا"},
    {"q": "كم عدد سور القرآن الكريم؟", "a": "114"},
    {"q": "ما هو العنصر الكيميائي الذي يرمز له بـ Au؟", "a": "الذهب"},
    {"q": "في أي سنة أبحرت سفينة تايتانيك وغرقت؟", "a": "1912"},
    {"q": "ما هو أسرع حيوان بري في العالم؟", "a": "الفهد"},
    {"q": "ما هو أكبر كوكب في المجموعة الشمسية؟", "a": "المشتري"},
    {"q": "من هو النبي الذي لقب بـ كليم الله؟", "a": "موسى"},
    {"q": "كم عدد كواكب المجموعة الشمسية؟", "a": "8"}
]

# ====================================================
# --- محرك تحميل الأغاني الذكي (yt-dlp) ---
# ====================================================
def _download_yt_audio(query: str) -> dict:
    try:
        import yt_dlp
        out_pattern = f"/tmp/lara_{int(time.time() * 1000)}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_pattern + '.%(ext)s',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'noplaylist': True, 'quiet': True, 'default_search': 'ytsearch1',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=True)
            if 'entries' in info and len(info['entries']) > 0:
                info = info['entries'][0]
            filepath = out_pattern + ".mp3"
            if not os.path.exists(filepath):
                files = glob.glob(out_pattern + ".*")
                if files: filepath = files[0]
            return {'success': True, 'filepath': filepath, 'title': info.get('title', query), 'uploader': info.get('uploader', 'غير معروف')}
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ====================================================
# --- نظام مراقبة السيرفر وفلتر الشتائم ---
# ====================================================
def get_system_telemetry() -> str:
    try:
        uptime_seconds = int(time.time() - BOT_START_TIME)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        cpu_usage = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        return (
            f"🖥️ **معلومات السيستم (VIP_ARM OS v5.9):**\n\n"
            f"⏱️ **التشغيل:** `{hours}h {minutes}m {seconds}s`\n"
            f"💻 **النظام:** `{platform.system()} {platform.release()}`\n"
            f"⚙️ **المعالج (CPU):** `{cpu_usage}%`\n"
            f"🧠 **الرام (RAM):** `{ram.percent}%` ({ram.used // (1024**2)}MB)\n"
            f"💾 **المساحة الحرة:** `{disk.free // (1024**3)} GB`"
        )
    except Exception as e:
        return f"⚠️ خطأ جلب الإحصائيات: {e}"

async def check_bad_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat and update.effective_chat.type in ["group", "supergroup"]:
        if update.message and update.message.text:
            bad_words = ["شتمة1", "شتمة2"] # أضف الألفاظ غير المرغوبة هنا
            msg_lower = update.message.text.lower()
            if any(w in msg_lower for w in bad_words):
                try:
                    await update.message.delete()
                    await update.message.reply_text(f"⚠️ تنبيه: ممنوع استخدام الألفاظ النابية هنا يا {update.message.from_user.first_name}!")
                except Exception:
                    pass
                return True
    return False

# ====================================================
# --- أزرار القوائم الأساسية ---
# ====================================================
def get_main_keyboard(bot_username, is_admin):
    keyboard = [
        [InlineKeyboardButton("➕ تفعيل البوت بمجموعة", url=f"https://t.me/{bot_username}?startgroup=true")],
        [InlineKeyboardButton("📜 أوامر الأعضاء", callback_data="cmd_user"), InlineKeyboardButton("👮 أوامر المجموعة", callback_data="cmd_group")],
        [InlineKeyboardButton("🎮 الألعاب والترفيه", callback_data="cmd_games"), InlineKeyboardButton("🛠️ أدوات وميديا", callback_data="cmd_tools")],
        [InlineKeyboardButton("💡 تقديم مقترح", callback_data="btn_suggest"), InlineKeyboardButton("☕ دعم المطور", callback_data="btn_donate")]
    ]
    if is_admin:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم المطور (خاص)", callback_data="admin_main")])
    return InlineKeyboardMarkup(keyboard)

def get_xo_keyboard(board):
    keyboard = []
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            val = board[idx] if board[idx] else "⬜"
            row.append(InlineKeyboardButton(val, callback_data=f"xo_move_{idx}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ إنهاء اللعبة", callback_data="xo_stop")])
    return InlineKeyboardMarkup(keyboard)

# ====================================================
# --- الأوامر الأساسية ---
# ====================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_obj = await context.bot.get_me()
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user.id))
        u = res.scalar_one_or_none()
        if not u:
            session.add(User(telegram_id=user.id, username=user.username, first_name=user.first_name, is_admin=(user.id == ADMIN_ID)))
            await session.commit()
    text = f"🌸 **أهلاً بك يا {user.first_name} في بوت لارا (V5.9 Legendary - VIP_ARM)!**\n\n✨ أنا مساعدتك الذكية المتكاملة للأغاني، الألعاب التفاعلية، والإدارة الفائقة."
    markup = get_main_keyboard(bot_obj.username, user.id == ADMIN_ID)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(f"🆔 **معلوماتك:**\n👤 الاسم: {u.first_name}\n🔑 الآيدي: `{u.id}`", parse_mode="Markdown")

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_t = time.time()
    msg = await update.message.reply_text("⚡ جاري قياس السرعة...")
    ping_ms = round((time.time() - start_t) * 1000, 2)
    await msg.edit_text(f"⚡ **سرعة الاستجابة:** `{ping_ms} ms`", parse_mode="Markdown")

async def cmd_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("🔢 استخدم: `/calc 5+5`", parse_mode="Markdown")
    try:
        res = eval("".join(context.args))
        await update.message.reply_text(f"🔢 **النتيجة:** `{res}`", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("⚠️ خطأ في المعادلة.")

async def cmd_xo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    XO_GAMES[chat_id] = {"board": [""] * 9, "turn": "❌", "p1": update.effective_user.id}
    await update.message.reply_text("🎮 **لعبة إكس أو (XO) بدأت!**\nدور اللاعب: **❌**", reply_markup=get_xo_keyboard(XO_GAMES[chat_id]["board"]), parse_mode="Markdown")

# ====================================================
# --- موجه الأزرار (Button Router) ---
# ====================================================
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id
    chat_id = query.message.chat_id
    bot_obj = await context.bot.get_me()
    back_main = [[InlineKeyboardButton("🔙 عودة للرئيسية", callback_data="main_menu")]]

    if data == "main_menu":
        text = "🌸 **روبوت لارا (V5.9 Legendary):**\n\n✨ اختر من القائمة أدناه:"
        await query.message.edit_text(text, reply_markup=get_main_keyboard(bot_obj.username, uid == ADMIN_ID), parse_mode="Markdown")

    elif data == "cmd_user":
        msg = (
            "📌 **أوامر الأعضاء الشاملة:**\n"
            "• `معلوماتي` - عرض معلومات حسابك\n"
            "• `تست` أو `بينج` - قياس سرعة الاستجابة\n"
            "• `رتبتي` - معرفة تفاعلك ورتبتك\n"
            "• `لارا احكي [نص]` - تحويل النص لصوت (TTS)\n"
            "• `لارا [سؤال]` - التحدث مع الذكاء الاصطناعي\n"
            "• `نزلي [اسم الأغنية]` - تحميل وتحويل أغنية MP3\n"
            "• `/calc` - آلة حاسبة رياضية\n\n"
            "🎭 **أوامر التسلية الجديدة:**\n"
            "• `لارا نسبة الحب بين [الاسم] و [الاسم]`\n"
            "• `لارا قصف` (بالرد أو بدون) للمزح\n"
            "• `لارا نكتة` لجرعة ضحك\n"
            "• `لارا اختراق` (بالرد على شخص للمزاح)"
        )
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(back_main), parse_mode="Markdown")

    elif data == "cmd_group":
        msg = (
            "👮 **أوامر الإدارة والحماية (للمشرفين فقط):**\n"
            "• `طرد` (بالرد) - طرد العضو نهائياً\n"
            "• `كتم` (بالرد) - كتم العضو ومنعه من الكلام\n"
            "• `فك الكتم` (بالرد) - السماح للعضو بالكتابة\n"
            "• `تحذير` (بالرد) - إعطاء تحذير (عند 3 يتم الكتم تلقائياً)\n"
            "• `ثبتي` (بالرد) - تثبيت الرسالة أعلى المجموعة\n"
            "• `قفل المحادثة` / `فتح المحادثة` - للتحكم بكتابة الأعضاء"
        )
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(back_main), parse_mode="Markdown")

    elif data == "cmd_games":
        keyboard = [
            [InlineKeyboardButton("❌⭕ إكس أو", callback_data="start_xo"), InlineKeyboardButton("🧠 الأسئلة", callback_data="start_trivia")],
            [InlineKeyboardButton("✊✋✌️ حجرة ورقة مقص", callback_data="start_rps")],
            [InlineKeyboardButton("🎲 النرد", callback_data="g_dice"), InlineKeyboardButton("🎯 السهم", callback_data="g_dart")],
            [InlineKeyboardButton("🏀 السلة", callback_data="g_basket"), InlineKeyboardButton("⚽ القدم", callback_data="g_football")],
            [InlineKeyboardButton("🔙 عودة للرئيسية", callback_data="main_menu")]
        ]
        await query.message.edit_text("🎮 **قسم الألعاب والتسلية الخارق:**\n\nاختر لعبتك المفضلة:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "start_rps":
        kb = [
            [InlineKeyboardButton("✊ حجرة", callback_data="rps_rock"), InlineKeyboardButton("✋ ورقة", callback_data="rps_paper"), InlineKeyboardButton("✌️ مقص", callback_data="rps_scissors")]
        ]
        await query.message.edit_text("🎮 **لعبة حجرة ورقة مقص!**\n\nاختر حركتك:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    elif data.startswith("rps_"):
        user_choice = data.split("_")[1]
        bot_choice = random.choice(["rock", "paper", "scissors"])
        choices_ar = {"rock": "✊ حجرة", "paper": "✋ ورقة", "scissors": "✌️ مقص"}

        if user_choice == bot_choice:
            res_txt = "🤝 **تعادل!**"
        elif (user_choice == "rock" and bot_choice == "scissors") or \
             (user_choice == "paper" and bot_choice == "rock") or \
             (user_choice == "scissors" and bot_choice == "paper"):
            res_txt = "🎉 **أنت فزت! مبروك يا وحش**"
        else:
            res_txt = "😂 **أنا فزت! هاردلك**"

        final_msg = f"أنت اخترت: {choices_ar[user_choice]}\nلارا اختارت: {choices_ar[bot_choice]}\n\nالنتيجة: {res_txt}"
        await query.message.edit_text(final_msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 العب مرة تانية", callback_data="start_rps")], [InlineKeyboardButton("🔙 رجوع", callback_data="cmd_games")]]), parse_mode="Markdown")

    elif data == "start_xo":
        await query.message.delete()
        XO_GAMES[chat_id] = {"board": [""] * 9, "turn": "❌", "p1": uid}
        await context.bot.send_message(chat_id, "🎮 **لعبة إكس أو (XO) بدأت!**\nدور اللاعب: **❌**", reply_markup=get_xo_keyboard(XO_GAMES[chat_id]["board"]), parse_mode="Markdown")

    elif data.startswith("xo_move_"):
        if chat_id not in XO_GAMES:
            return await query.answer("⚠️ لا توجد لعبة نشطة حالياً!", show_alert=True)
        idx = int(data.split("_")[2])
        game = XO_GAMES[chat_id]
        if game["board"][idx] != "":
            return await query.answer("⚠️ هذا المكان محجوز!", show_alert=True)
        game["board"][idx] = game["turn"]
        b = game["board"]
        win_conditions = [(0,1,2), (3,4,5), (6,7,8), (0,3,6), (1,4,7), (2,5,8), (0,4,8), (2,4,6)]
        winner = None
        for w in win_conditions:
            if b[w[0]] != "" and b[w[0]] == b[w[1]] == b[w[2]]:
                winner = b[w[0]]
                break
        if winner:
            await query.message.edit_text(f"🏆 **انتهت اللعبة وفاز اللاعب {winner}!** 🎉", reply_markup=get_xo_keyboard(b), parse_mode="Markdown")
            del XO_GAMES[chat_id]
            return
        elif "" not in b:
            await query.message.edit_text("🤝 **تعادل الفريقان!**", reply_markup=get_xo_keyboard(b), parse_mode="Markdown")
            del XO_GAMES[chat_id]
            return
        game["turn"] = "⭕" if game["turn"] == "❌" else "❌"
        await query.message.edit_text(f"🎮 **لعبة XO جارية..**\nدور اللاعب: **{game['turn']}**", reply_markup=get_xo_keyboard(b), parse_mode="Markdown")

    elif data == "xo_stop":
        if chat_id in XO_GAMES: del XO_GAMES[chat_id]
        await query.message.edit_text("❌ تم إنهاء لعبة XO الحالية.")

    elif data == "start_trivia":
        await query.message.delete()
        q_data = random.choice(TRIVIA_QUESTIONS)
        TRIVIA_GAMES[chat_id] = {"q": q_data["q"], "a": q_data["a"]}
        await context.bot.send_message(chat_id, f"🧠 **لعبة الأسئلة الثقافية:**\n\n❓ **السؤال:** {q_data['q']}\n\n*(اكتب الإجابة بالدردشة الآن!)*", parse_mode="Markdown")

    elif data == "g_dice": await context.bot.send_dice(chat_id, emoji="🎲")
    elif data == "g_dart": await context.bot.send_dice(chat_id, emoji="🎯")
    elif data == "g_basket": await context.bot.send_dice(chat_id, emoji="🏀")
    elif data == "g_football": await context.bot.send_dice(chat_id, emoji="⚽")

    elif data == "cmd_tools":
        msg = "🛠️ **أدوات إضافية:**\n• `/calc` - حساب معادلات رياضية\n• `نزلي [اسم الأغنية]` - تحميل وسحب الأغاني mp3"
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(back_main), parse_mode="Markdown")

    elif data == "btn_donate":
        await query.message.reply_text("💖 شكراً لدعمك المطور VIP_ARM! البوت مستمر بفضلكم.")

    elif data == "admin_main" and uid == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("📢 إذاعة للكل", callback_data="adm_broadcast"), InlineKeyboardButton("➕ إضافة رد", callback_data="adm_add_reply")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats"), InlineKeyboardButton("🖥️ حالة السيرفر", callback_data="adm_sys_status")],
            [InlineKeyboardButton("🔙 عودة للرئيسية", callback_data="main_menu")]
        ]
        await query.message.edit_text("⚙️ **لوحة المطور الخاصة (VIP_ARM):**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "adm_sys_status" and uid == ADMIN_ID:
        await query.edit_message_text(get_system_telemetry(), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data="admin_main")]]), parse_mode="Markdown")

    elif data == "adm_stats" and uid == ADMIN_ID:
        async with async_session() as session:
            u_cnt = (await session.execute(select(func.count(User.id)))).scalar()
            r_cnt = (await session.execute(select(func.count(AutoReply.id)))).scalar()
        await query.edit_message_text(f"📊 **الإحصائيات:**\n👥 المستخدمون: `{u_cnt}`\n💡 الردود المحفوظة: `{r_cnt}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data="admin_main")]]), parse_mode="Markdown")

# ====================================================
# --- محادثات الإدارة والمدخلات ---
# ====================================================
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("↩️ تم الإلغاء والعودة للوضع الطبيعي.", parse_mode="Markdown")
    return ConversationHandler.END

async def add_reply_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END
    await query.message.reply_text("➕ أرسل كلمة المفتاح:\n*(أو /cancel للإلغاء)*", parse_mode="Markdown")
    return WAIT_TRIGGER

async def add_reply_trig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['trig'] = update.message.text.strip()
    await update.message.reply_text("💬 أرسل نص الرد:", parse_mode="Markdown")
    return WAIT_RESPONSE

async def add_reply_resp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trig, resp = context.user_data['trig'], update.message.text.strip()
    async with async_session() as session:
        session.add(AutoReply(trigger=trig, response=resp))
        await session.commit()
    await update.message.reply_text(f"✅ تم حفظ الرد بنجاح:\n`{trig}` -> `{resp}`", parse_mode="Markdown")
    return ConversationHandler.END

async def suggest_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("💡 أرسل مقترحك للمطور:\n*(أو /cancel للإلغاء)*", parse_mode="Markdown")
    return WAIT_SUGGESTION

async def suggest_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with async_session() as session:
        session.add(Suggestion(user_id=update.effective_user.id, text=update.message.text.strip()))
        await session.commit()
    await update.message.reply_text("✅ تم إرسال مقترحك بنجاح. شكراً لك! 🌸", parse_mode="Markdown")
    return ConversationHandler.END

async def broadcast_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END
    await query.message.reply_text("📢 أرسل رسالة الإذاعة للجميع:\n*(أو /cancel للإلغاء)*", parse_mode="Markdown")
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
            await asyncio.sleep(0.04)
        except Exception: pass
    await update.message.reply_text(f"✅ تمت الإذاعة إلى `{count}` مستخدم بنجاح.", parse_mode="Markdown")
    return ConversationHandler.END

# ====================================================
# --- موجه الرسائل النصية الشامل والآمن ---
# ====================================================
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return

    # 1. فلتر الكلمات النابية
    if await check_bad_words(update, context):
        return

    text = update.message.text.strip()
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    is_group = update.effective_chat.type in ['group', 'supergroup']
    reply_msg = update.message.reply_to_message

    # زيادة النقاط/التفاعل
    USER_XP[(chat_id, uid)] = USER_XP.get((chat_id, uid), 0) + 1

    # 2. فحص الردود التلقائية المخصصة من قاعدة البيانات أولاً
    async with async_session() as session:
        res = await session.execute(select(AutoReply).where(AutoReply.trigger == text))
        db_reply = res.scalar_one_or_none()
        if db_reply:
            return await update.message.reply_text(db_reply.response)

    # 3. الأسئلة الثقافية
    if chat_id in TRIVIA_GAMES:
        correct_ans = TRIVIA_GAMES[chat_id]["a"]
        if text.lower() == correct_ans.lower():
            del TRIVIA_GAMES[chat_id]
            return await update.message.reply_text(f"🎉 **إجابة صحيحة يا [{update.effective_user.first_name}](tg://user?id={uid})!** بطل الألعاب ✨", parse_mode="Markdown")

    # 4. قسم التسلية والترفيه
    if text in ["لارا اختراق", "اختراق"] and reply_msg:
        target_name = reply_msg.from_user.first_name
        hack_msg = await update.message.reply_text(f"💻 **[{update.effective_user.first_name}]** طلب تهيئة بيئة الاختراق...\n\n[▓░░░░░░░░░] 10%", parse_mode="Markdown")
        await asyncio.sleep(1)
        fake_ip = f"192.168.{random.randint(1,255)}.{random.randint(1,255)}"
        await hack_msg.edit_text(f"🔍 جاري البحث عن IP الهدف ({target_name})...\n\n[▓▓▓▓░░░░░░] 40%", parse_mode="Markdown")
        await asyncio.sleep(1.2)
        await hack_msg.edit_text(f"🎯 تم العثور على الهدف!\n🌐 IP: `{fake_ip}`\n🔓 جاري كسر تشفير الحماية...\n\n[▓▓▓▓▓▓▓░░░] 75%", parse_mode="Markdown")
        await asyncio.sleep(1.5)
        return await hack_msg.edit_text(f"✅ **تم الاختراق بنجاح!** 💀\nتم سحب الصور والملفات من جهاز {target_name}!\n\n*(بمزح بمزح، نظام حماية VIP_ARM أقوى من هيك بكتير 😂)*", parse_mode="Markdown")

    if text.startswith("لارا نسبة الحب"):
        names = text.replace("لارا نسبة الحب", "").strip()
        if not names:
            return await update.message.reply_text("❤️ اكتبي الاسمين بعد الأمر، مثال:\n`لارا نسبة الحب أحمد ومريم`", parse_mode="Markdown")
        love_percent = random.randint(0, 100)
        emoji = "🔥" if love_percent > 80 else ("💖" if love_percent > 50 else "💔")
        return await update.message.reply_text(f"❤️ **مقياس الحب الدقيق:**\n\nنسبة الحب بين {names} هي: **{love_percent}%** {emoji}", parse_mode="Markdown")

    if text in ["لارا قصف", "قصف", "اقصفي"]:
        roast = random.choice(ROASTS)
        if reply_msg:
            return await update.message.reply_text(f"🚀 موجه لـ {reply_msg.from_user.first_name}:\n{roast}")
        return await update.message.reply_text(roast)

    if text in ["لارا نكتة", "نكتة", "نكت", "لارا نكت"]:
        return await update.message.reply_text(f"😂 {random.choice(JOKES)}")

    # 5. الأوامر العامة والأدوات
    if text in ["اوامر", "الاوامر", "قائمة الأوامر", "مساعدة", "help", "/start"]:
        if text == "/start": return await start(update, context)
        return await update.message.reply_text(
            "📜 **قائمة أوامر بوت لارا (V5.9 Legendary):**\n\n"
            "• `معلوماتي` - عرض معلومات حسابك والآيدي\n"
            "• `تست` / `بينج` - قياس سرعة الاستجابة\n"
            "• `رتبتي` - معرفة تفاعلك وعدد رسائلك\n"
            "• `نزلي [اسم الأغنية]` - تحميل أغنية mp3\n"
            "• `لارا احكي [نص]` - تحويل النص إلى صوت (TTS)\n"
            "• `لارا [سؤال]` - التحدث مع المساعد الذكي\n"
            "• `لارا نكتة` / `لارا قصف` / `لارا اختراق [بالرد]` - للمتعة\n"
            "• `طرد` / `كتم` / `فك الكتم` / `تحذير` (بالرد للمجموعات)\n"
            "• `قفل المحادثة` / `فتح المحادثة` - للتحكم بالجروب",
            parse_mode="Markdown"
        )

    if text in ["معلوماتي", "معلومات", "ايدي", "آيدي", "حسابي"]:
        return await cmd_id(update, context)

    if text in ["بينج", "سرعة البوت", "تست", "ping"]:
        return await cmd_ping(update, context)

    if text in ["رتبتي", "نقاطي", "تفاعلي"]:
        xp = USER_XP.get((chat_id, uid), 1)
        try:
            member = await context.bot.get_chat_member(chat_id, uid)
            st = member.status
        except Exception:
            st = "member"
        if st in ["creator", "owner"]: rank = "مالك المجموعة 👑"
        elif st == "administrator": rank = "مشرف 🛡️"
        elif xp > 50: rank = "عضو متفاعل خارق 🔥"
        elif xp > 20: rank = "عضو نشيط ⚡"
        else: rank = "عضو جديد 🌱"
        return await update.message.reply_text(f"📊 **تفاعلك:**\n🎖️ الرتبة: {rank}\n💬 الرسائل: {xp}", parse_mode="Markdown")

    if text in ["اكس او", "إكس أو", "إكس او", "xo", "XO"]:
        return await cmd_xo(update, context)

    if text in ["حالة النظام", "السيرفر", "النظام"] and uid == ADMIN_ID:
        return await update.message.reply_text(get_system_telemetry(), parse_mode="Markdown")

    # 6. تحويل النص لصوت (TTS)
    if text.startswith("لارا احكي") or text.startswith("احكي"):
        speech_text = text.replace("لارا احكي", "").replace("احكي", "").strip()
        if not speech_text: return await update.message.reply_text("🗣️ اكتب النص بعد الأمر.")
        try:
            from gtts import gTTS
            tts_path = f"/tmp/tts_{update.message.message_id}.mp3"
            gTTS(text=speech_text, lang='ar').save(tts_path)
            with open(tts_path, 'rb') as v_file:
                await context.bot.send_voice(chat_id=chat_id, voice=v_file, reply_to_message_id=update.message.message_id)
            if os.path.exists(tts_path): os.remove(tts_path)
            return
        except Exception:
            return await update.message.reply_text(f"🗣️ **لارا تقول:** {speech_text}")

    # 7. تنزيل الأغاني الموسيقية
    music_triggers = ["نزلي", "حملي", "بدي غنية", "اغنية", "تحميل"]
    if any(text.startswith(trig) for trig in music_triggers):
        query_song = text
        for trig in music_triggers:
            query_song = query_song.replace(trig, "")
        query_song = query_song.strip()

        if not query_song:
            return await update.message.reply_text("❌ يرجى كتابة اسم الأغنية بعد الأمر، مثال:\n`نزلي أصالة`", parse_mode="Markdown")

        status_msg = await update.message.reply_text("🔎 **جاري البحث وتحميل الأغنية...**", parse_mode="Markdown")
        res = await asyncio.to_thread(_download_yt_audio, query_song)

        if res['success'] and os.path.exists(res['filepath']):
            try:
                await status_msg.edit_text("⬆️ **جاري رفع الملف الصوتي...**", parse_mode="Markdown")
                with open(res['filepath'], 'rb') as audio_file:
                    await context.bot.send_audio(chat_id=chat_id, audio=audio_file, title=res['title'], performer=res['uploader'], reply_to_message_id=update.message.message_id)
                await status_msg.delete()
            except Exception as e:
                await status_msg.edit_text(f"⚠️ خطأ بالإرسال: {e}")
            finally:
                if os.path.exists(res['filepath']): os.remove(res['filepath'])
        else:
            await status_msg.edit_text(f"❌ فشل تحميل الأغنية: {res.get('error', 'غير متوفرة')}")
        return

    # 8. الدردشة الذكية مع لارا
    if text.startswith("لارا "):
        query_ai = text.replace("لارا ", "").strip()
        if not query_ai or query_ai in ["نكتة", "نكت", "قصف", "احكي", "اختراق", "نسبة الحب"]: return

        ai_replies = {
            "من انت": "أنا لارا، مساعدتك الذكية والمطورة بواسطة المبدع VIP_ARM! 🌸",
            "كيفك": "بأفضل حال والحمد لله! كيف أساعدك اليوم؟ ✨",
            "من طورك": "تم برمجتي بواسطة المطور الأسطوري VIP_ARM 🚀"
        }
        for k, v in ai_replies.items():
            if k in query_ai: return await update.message.reply_text(v)
        return await update.message.reply_text(f"🤖 **لارا:** أنا هنا معك بخصوص `{query_ai}`. أقدر أساعدك بأي شيء تحتاجه!", parse_mode="Markdown")

    # 9. نظام الإدارة المحمي الشامل للمجموعات (خاص بالمشرفين فقط)
    if is_group:
        kick_cmds = ["طرد", "اطردي", "لارا طردي", "لارا اطردي"]
        mute_cmds = ["كتم", "اكتمي", "لارا اكتمي", "كتمي"]
        unmute_cmds = ["فك الكتم", "الغاء كتم", "لارا فكي الكتم", "فكي الكتم"]
        warn_cmds = ["تحذير", "حذري", "لارا حذري"]
        pin_cmds = ["تثبيت", "ثبتي", "لارا ثبتي"]
        lock_cmds = ["قفل المحادثة", "إغلاق المحادثة", "لارا اقفلي", "قفل الجروب"]
        unlock_cmds = ["فتح المحادثة", "فتح الجروب", "لارا افتحي"]

        all_admin_triggers = kick_cmds + mute_cmds + unmute_cmds + warn_cmds + pin_cmds + lock_cmds + unlock_cmds

        if any(text == cmd or text.startswith(cmd) for cmd in all_admin_triggers):
            member = await context.bot.get_chat_member(chat_id, uid)
            if member.status not in ['administrator', 'creator'] and uid != ADMIN_ID:
                return await update.message.reply_text("❌ هذا الأمر مخصص للمشرفين فقط!")

            if text in lock_cmds:
                try:
                    await context.bot.set_chat_permissions(chat_id, ChatPermissions(can_send_messages=False))
                    await update.message.reply_text("🔒 تم قفل المحادثة بنجاح.")
                except Exception:
                    await update.message.reply_text("⚠️ تأكد أن البوت مشرف ولديه صلاحيات التحكم بالمجموعة.")
                return

            if text in unlock_cmds:
                try:
                    perms = ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_other_messages=True)
                    await context.bot.set_chat_permissions(chat_id, perms)
                    await update.message.reply_text("🔓 تم فتح المحادثة للجميع.")
                except Exception:
                    await update.message.reply_text("⚠️ تأكد من صلاحيات البوت.")
                return

            if reply_msg:
                target = reply_msg.from_user
                try:
                    if text in kick_cmds:
                        await context.bot.ban_chat_member(chat_id, target.id)
                        await update.message.reply_text(f"🚫 تم طرد العضو **{target.first_name}**.", parse_mode="Markdown")
                    elif text in mute_cmds:
                        await context.bot.restrict_chat_member(chat_id, target.id, permissions=ChatPermissions(can_send_messages=False))
                        await update.message.reply_text(f"🔇 تم كتم العضو **{target.first_name}**.", parse_mode="Markdown")
                    elif text in unmute_cmds:
                        perms = ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_other_messages=True)
                        await context.bot.restrict_chat_member(chat_id, target.id, permissions=perms)
                        await update.message.reply_text(f"🔊 تم فك الكتم عن **{target.first_name}**.", parse_mode="Markdown")
                    elif text in warn_cmds:
                        w_key = (chat_id, target.id)
                        USER_WARNS[w_key] = USER_WARNS.get(w_key, 0) + 1
                        if USER_WARNS[w_key] >= 3:
                            await context.bot.restrict_chat_member(chat_id, target.id, permissions=ChatPermissions(can_send_messages=False))
                            USER_WARNS[w_key] = 0
                            await update.message.reply_text(f"⚠️ وصل العضو **{target.first_name}** لـ 3 تحذيرات! تم كتمه تلقائياً.", parse_mode="Markdown")
                        else:
                            await update.message.reply_text(f"⚠️ تحذير للعضو **{target.first_name}** (`{USER_WARNS[w_key]}/3`).", parse_mode="Markdown")
                    elif text in pin_cmds:
                        await context.bot.pin_chat_message(chat_id, reply_msg.message_id)
                        await update.message.reply_text("📌 تم تثبيت الرسالة بنجاح.")
                except Exception:
                    await update.message.reply_text("⚠️ فشل تنفيذ الأمر: تأكد من رفع البوت كأدمن بالمجموعة وإعطائه الصلاحيات الكاملة.")
                return
            else:
                if text in kick_cmds + mute_cmds + unmute_cmds + warn_cmds + pin_cmds:
                    return await update.message.reply_text("⚠️ يرجى استخدام هذا الأمر بالرد على رسالة العضو المطلوب!")

# ====================================================
# --- التشغيل والنواة الأساسية ---
# ====================================================
def main():
    asyncio.run(init_db())
    app = Application.builder().token(BOT_TOKEN).build()

    reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_reply_init, pattern="^adm_add_reply$")],
        states={
            WAIT_TRIGGER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reply_trig)],
            WAIT_RESPONSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reply_resp)]
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation), MessageHandler(filters.COMMAND, cancel_conversation)],
        per_message=False
    )

    sug_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(suggest_init, pattern="^btn_suggest$")],
        states={WAIT_SUGGESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggest_save)]},
        fallbacks=[CommandHandler("cancel", cancel_conversation), MessageHandler(filters.COMMAND, cancel_conversation)],
        per_message=False
    )

    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_init, pattern="^adm_broadcast$")],
        states={WAIT_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)]},
        fallbacks=[CommandHandler("cancel", cancel_conversation), MessageHandler(filters.COMMAND, cancel_conversation)],
        per_message=False
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("calc", cmd_calc))
    app.add_handler(CommandHandler("xo", cmd_xo))

    app.add_handler(reply_conv)
    app.add_handler(sug_conv)
    app.add_handler(broadcast_conv)

    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

    print("[+] Bot Lara V5.9 Legendary (VIP_ARM Edition) Started Successfully!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
