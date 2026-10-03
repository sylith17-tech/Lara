# Names used in annotations must exist before those declarations.
import re
from telegram import Update
from telegram.ext import ContextTypes
from main_vip import handle_vip_menu, video_edit_init, video_receive_file, video_process_and_reply, cancel_video_edit, WAIT_VIDEO, WAIT_PROMPT, handle_incoming_video
from handlers.video_editor import (
    EDITOR_MEDIA_FILTER, handle_editor_media, handle_editor_text, video_editor_callback,
    video_editor_post_init, video_editor_post_shutdown,
)

from telegram.ext.filters import MessageFilter
from main_vip import ACTIVE_AI_USERS, handle_ai_video_prompt

class AILimitFilter(MessageFilter):
    def filter(self, message):
        if not message or not message.from_user:
            return False
        return message.from_user.id in ACTIVE_AI_USERS

from datetime import date

REQUIRED_CHANNEL = "@VIP_ARM0"

async def is_user_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if user_id == ADMIN_ID:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=REQUIRED_CHANNEL, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception as e:
        print(f"[Subscription Error]: {e}")
        return False

async def send_sub_required_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 الاشتراك في القناة", url="https://t.me/VIP_ARM0")],
        [InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data="check_sub")]
    ])
    msg = (
        "⚠️ **عذراً عزيزي! يجب عليك الاشتراك في قناة البوت أولاً لاستخدام الخدمات.**\n\n"
        "📢 القناة: @VIP_ARM0\n\n"
        "اشترك ثم اضغط على زر **تأكيد الاشتراك ✅** أدناه."
    )
    if update.callback_query:
        await update.callback_query.answer("⚠️ لم تشترك في القناة بعد!", show_alert=True)
        try:
            await update.callback_query.message.edit_text(msg, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def handle_check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if not user:
        return True

    is_sub = await is_user_subscribed(user.id, context)
    if is_sub:
        return True

    sub_text = """❌ لم تشترك في القناة بعد! يرجى الاشتراك أولاً لمتابعة استخدام البوت.

📢 قناة البوت: @VIP_ARM0"""
    
    sub_keyboard = [
        [InlineKeyboardButton("📢 اشترك في القناة", url="https://t.me/VIP_ARM0")],
        [InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data="check_subscription")]
    ]
    reply_markup = InlineKeyboardMarkup(sub_keyboard)

    if query:
        try:
            await query.answer("❌ لم تشترك في القناة بعد!", show_alert=True)
            await query.edit_message_text(sub_text, reply_markup=reply_markup)
        except Exception:
            await context.bot.send_message(chat_id=user.id, text=sub_text, reply_markup=reply_markup)
    else:
        if update.message:
            await update.message.reply_text(sub_text, reply_markup=reply_markup)
    return False
async def handle_get_ref_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await is_user_subscribed(update.effective_user.id, context):
        return await send_sub_required_msg(update, context)
        
    bot_obj = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_obj.username}?start=ref_{update.effective_user.id}"
    
    text = (
        f"🔗 **رابط الإحالة الخاص بك:**\n\n"
        f"`{ref_link}`\n\n"
        f"💡 **طريقة الاستخدام:**\n"
        f"قم بنسخ الرابط وإرساله لأصدقائك أو في المجموعات.\n"
        f"لكل شخص يدخل البوت عبر رابطك ستحصل على **100 نقطة** تلقائياً! 🎉"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للقائمة", callback_data="back_private_main")]])
    await query.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


import threading, http.server, socketserver, os, logging, asyncio, glob, time, random, urllib.request
from datetime import datetime
import platform
import psutil

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
)
from main_vip import handle_vip_menu, video_edit_init, video_receive_file, video_process_and_reply, cancel_video_edit, WAIT_VIDEO, WAIT_PROMPT, handle_ai_video_prompt, handle_incoming_video, handle_start_video_edit, handle_vip_stats
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler
)
from sqlalchemy import select, func
from database import GroupSettings, init_db, async_session, User, AutoReply, Suggestion, ModerationWarning
from handlers.group_owner import (
    FLOW_KEY as GROUP_OWNER_FLOW_KEY,
    handle_owner_callback,
    handle_owner_flow_message,
    is_group_admin,
    is_group_owner,
    render_welcome,
    show_owner_menu,
)
from services.group_features import ACTION_REGISTRY, group_feature_store

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


# ====================================================
# --- الإعدادات الأساسية والثوابت ---
# ====================================================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
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
logger = logging.getLogger("litharm_LEGENDARY")

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
        "extractor_args": {"youtube": {"player_client": ["android", "ios", "web"]}},
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
            f"🖥️ **معلومات السيستم (litharm OS v5.9):**\n\n"
            f"⏱️ **التشغيل:** `{hours}h {minutes}m {seconds}s`\n"
            f"💻 **النظام:** `{platform.system()} {platform.release()}`\n"
            f"⚙️ **المعالج (CPU):** `{cpu_usage}%`\n"
            f"🧠 **الرام (RAM):** `{ram.percent}%` ({ram.used // (1024**2)}MB)\n"
            f"💾 **المساحة الحرة:** `{disk.free // (1024**3)} GB`"
        )
    except Exception as e:
        return f"⚠️ خطأ جلب الإحصائيات: {e}"


def _normalize_moderation_text(text: str) -> str:
    """Normalize Arabic/Latin text to make common obfuscation harder."""
    import re
    if not text:
        return ""

    text = text.lower()

    replacements = {
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
        "ى": "ي", "ئ": "ي", "ؤ": "و",
        "ة": "ه", "ـ": "",
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
        "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    }
    text = "".join(replacements.get(ch, ch) for ch in text)

    # Remove invisible/control characters and collapse separators.
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", text)
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)
    return re.sub(r"\s+", " ", text).strip()


# Core phrases are intentionally kept separate from the old placeholder filter.
# This makes the moderation engine easy to expand without changing handle_msg.
MODERATION_OFFENSIVE_TERMS = {
    # إهانات عامة
    "غبي", "غبية", "غباء", "احمق", "أحمق", "حمقاء", "احمقك",
    "معتوه", "معتوهة", "اهبل", "أهبل", "هبلة", "متخلف", "متخلفة",
    "تافه", "تافهة", "سخيف", "سخيفة", "سفيه", "سفيهة",
    "حقير", "حقيرة", "وضيع", "وضيعة", "سافل", "سافلة",
    "قذر", "قذرة", "وسخ", "وسخة", "نجس", "نجسة", "مقرف", "مقرفة",
    "خبيث", "خبيثة", "كذاب", "كذابة", "كذابين", "كاذب", "كاذبة",
    "نصاب", "نصابة", "منافق", "منافقة", "خائن", "خائنة",
    "عديم الشرف", "عديمة الشرف", "جبان", "جبانة",
    "فاشل", "فاشلة", "فاشلين", "فاشلات",
    "تافهين", "تافهات", "اغبياء", "أغبياء", "غبيان",
    "احمقين", "حمقاء", "مهبول", "مهبولة", "مهابيل",
    "مخبول", "مخبولة", "مجانين", "مجنون", "مجنونة",
    "مختل", "مختلة", "مريض", "مريضة", "مقرفين", "وسخين",
    "قذرين", "حقيرين", "سافلين", "تافهين", "سخيفين",

    # تشبيهات وإهانات حيوانية
    "كلب", "كلبة", "كلاب", "كلابك", "كلبين", "كلبات",
    "حمار", "حمارة", "حمير", "حميرك", "حميرين",
    "جحش", "جحشة", "جحوش", "جحوشك",
    "بغل", "بغلة", "بغال", "بغلك",
    "خنزير", "خنزيرة", "خنازير",
    "جرذ", "جرذان", "جرذون",
    "قرد", "قردة", "قرود",
    "حشرة", "حشرات", "دودة", "ديدان",
    "صرصور", "صراصير", "ذباب", "بعوضة", "بعوض",
    "ثعلب", "ثعالب", "ضفدع", "ضفادع",
    "كلبة", "كلبوس", "خروف", "خرفان",
    "ثور", "ثيران", "بقرة", "بقر",
    "حيوان", "حيوانات", "حيواناتك",
    "يا حيوان", "يا حيوانات", "يا كلب", "يا كلاب",
    "يا حمار", "يا حمير", "يا جحش", "يا خنزير",
    "يا قرد", "يا جرذ", "يا حشرة", "يا بغل",

    # ألفاظ نابية وعبارات بذيئة
    "زبالة", "زباله", "زفت", "قرف", "خرا", "خراء",
    "خرا عليك", "خرا فيك", "خرا بوجهك", "خرا بوجهك",
    "خرا عليك وعلى", "كل خرا", "روح كل خرا", "اكل خرا",
    "تباً لك", "تبا لك", "تباً إلك", "تبا إلك",
    "تباً عليك", "تبا عليك", "يلعن شكلك", "يلعن وجهك",
    "يلعن أبوك", "يلعن ابوك", "يلعن امك", "يلعن أمك",
    "يلعن امك وابوك", "يلعن جدك", "يلعن اجدادك",
    "يلعن اصلك", "يلعن نسلك", "يلعن حظك",
    "ملعون", "ملعونة", "ملعونين", "ملعونينك",
    "الله يلعنك", "الله لا يوفقك", "الله ياخذك",
    "الله ينتقم منك", "الله لا يردك", "الله لا يبارك فيك",
    "فشرت", "فشر", "فاشل", "فاشلة",
    "انطم", "انطمي", "اسكت", "اسكتي", "خرس",
    "خرسي", "حل عني", "حل عن وجهي", "روح عني",

    # إهانات عائلية مركبة
    "ابن الحرام", "بنت الحرام", "ولد الحرام", "اولاد الحرام",
    "أولاد الحرام", "ابن الكلب", "بنت الكلبة", "ولد الكلب",
    "اولاد الكلب", "أولاد الكلب",
    "ابن الوسخة", "بنت الوسخة", "ولد الوسخ", "اولاد الوسخ",
    "أولاد الوسخ", "ابن القحبة", "بنت القحبة", "ولد القحبة",
    "اولاد القحاب", "أولاد القحاب",
    "ابن الشرموطة", "بنت الشرموطة", "ولد الشرموطة",
    "اولاد الشرموطة", "ابن الزانية", "بنت الزانية", "ولد الزانية",
    "ابن الفاجرة", "بنت الفاجر", "ابن الساقطة", "بنت الساقط",
    "ابن الكذا", "بنت الكذا", "ولد الكذا",

    # ألفاظ جنسية/مهينة صريحة شائعة
    "شرموط", "شرموطة", "شراميط", "شرموطات",
    "قحبة", "قحاب", "قحبات", "قحبه", "قحابك",
    "عاهر", "عاهرة", "عاهرات", "زاني", "زانية", "زناة",
    "فاجر", "فاجرة", "فاجرين", "فاسق", "فاسقة",
    "ساقط", "ساقطة", "ساقطين", "منيك", "منيكة",
    "مخنث", "مخنثة", "ديوث", "ديوثة",
    "عرص", "عراص", "عرصات", "منيوك",
    "منيوكة", "لوطي", "لواطي", "سحاقية",
    "شرموطه", "قحبه", "عهر", "دعارة", "زنا",
    "فجور", "فسق",

    # إهانات باللهجة الشامية/السورية
    "روح انقلع", "انقلع", "انقلعي", "انقلع من هون",
    "انقلع من وجهي", "انطم", "انطمي",
    "دبر حالك", "حل عني", "حل عن وجهي",
    "فك عني", "فكنا منك", "خلصنا منك",
    "لا تقرفني", "قرفتني", "قرفتنا",
    "يا غبي", "يا اهبل", "يا أهبل", "يا معتوه",
    "يا متخلف", "يا قذر", "يا وسخ", "يا حقير",
    "يا سافل", "يا تافه", "يا سخيف", "يا جبان",
    "يا فاشل", "يا كذاب", "يا نصاب", "يا منافق",
    "يا خائن", "يا نجس", "يا مقرف", "يا مهبول",
    "يا مجنون", "يا مخبول", "يا مختل",
    "شو هالغبا", "شو هالغباء", "شو هالحماقة",
    "شو هالتخلف", "شو هالقرف", "شو هالوساخة",
    "شو هالزبالة", "شو هالسخافة",

    # لهجات وصيغ عامية إضافية
    "هبل", "هبلة", "هبلان", "هبيلة", "هبيل",
    "غبا", "غباء", "غبيان", "غبيّة",
    "حماقة", "احمق", "أحمق", "حمق",
    "تخلف", "متخلف", "متخلفة", "متخلفين",
    "وساخة", "وسخ", "وسخة", "وسخين",
    "قذارة", "قذر", "قذرة", "قذرين",
    "حقارة", "حقير", "حقيرة", "حقيرين",
    "سفالة", "سافل", "سافلة", "سافلين",
    "تفاهة", "تافه", "تافهة", "تافهين",
    "سخافة", "سخيف", "سخيفة", "سخيفين",
    "نجاسة", "نجس", "نجسة",
    "كذب", "كذاب", "كذابة", "كذابين",
    "نصب", "نصاب", "نصابة", "نصابين",
    "نفاق", "منافق", "منافقة", "منافقين",

    # صيغ مخاطبة وإهانات مركبة
    "يا ابن الكلب", "يا ابن الحرام", "يا ابن الوسخة",
    "يا ابن القحبة", "يا ابن الشرموطة",
    "يا بنت الكلب", "يا بنت الحرام", "يا بنت الوسخة",
    "يا بنت القحبة", "يا بنت الشرموطة",
    "يا ولد الكلب", "يا ولد الحرام", "يا ولد الوسخة",
    "يا ولد القحبة", "يا ولد الشرموطة",
    "روح يا كلب", "روح يا حمار", "روح يا حيوان",
    "روح يا غبي", "روح يا اهبل", "روح يا قذر",
    "روح يا وسخ", "روح يا حقير", "روح يا تافه",
    "اسكت يا غبي", "اسكت يا حمار", "اسكت يا كلب",
    "انطم يا غبي", "انطم يا حمار", "انطم يا كلب",

    # صيغ هجائية وأخطاء شائعة
    "غبييي", "غبيييي", "غبييييي",
    "اهبللل", "اهبلللل", "أهبللل",
    "احمقكك", "احمقق", "حمارر", "حماررر",
    "كلبب", "كلببب", "وسخخ", "وسخخخ",
    "قذرر", "قذررر", "خراا", "خرااا",
    "زبالهه", "زبالةة", "قحبهه", "قحبةة",
    "شرموطه", "شرموط", "شرموطط",
    "منيكك", "عرصص", "ديوثث",
    "معتوهه", "معتوههه", "متخلفف", "متخلففف",
    "سافلل", "حقيرر", "تافهه", "سخيفف",
    "كذابب", "كذاببب", "نصابب", "منافقق",

    # صيغ بدون مسافات شائعة
    "ياكلب", "ياحمار", "ياحيوان", "ياغبي", "ياهبل",
    "ياقذر", "ياوسخ", "ياحقير", "ياسافل", "ياتافه",
    "يابنكلب", "يابنحرام", "يابنقحبة", "يابنشرموطة",
    "روحانقلع", "روحكلخرا", "كلخرا", "يلعنك",

    # عبارات إهانة إضافية
    "عديم الادب", "عديم الأدب", "قليل الادب", "قليل الأدب",
    "ما عندك ادب", "ما عندك أدب", "ما عندك احترام",
    "انسان تافه", "إنسان تافه", "انسان قذر", "إنسان قذر",
    "شخص تافه", "شخص قذر", "شخص حقير",
    "ما بتفهم", "ما تفهم", "ما الك قيمة", "ما إلك قيمة",
    "ما تسوى", "ما بتسوى", "ولا تسوى",
    "وجهك نحس", "وجهك قرف", "وجهك زبالة",
    "عقلك زبالة", "عقلك خرا", "مخك خرا",
    "مخك تعبان", "مخك فاضي",

    # العناصر القديمة للحفاظ على التوافق
    "شتمة1", "شتمة2",
}


MODERATION_HIGH_SEVERITY_TERMS = set()

MODERATION_WARNING_LIMIT = 3


async def get_moderation_warning(chat_id: int, user_id: int) -> int:
    async with async_session() as session:
        result = await session.execute(
            select(ModerationWarning).where(
                ModerationWarning.chat_id == chat_id,
                ModerationWarning.user_id == user_id,
            )
        )
        row = result.scalar_one_or_none()
        return int(row.count or 0) if row else 0


async def get_moderation_warning_stats(chat_id: int, user_id: int) -> tuple[int, int]:
    async with async_session() as session:
        result = await session.execute(
            select(ModerationWarning).where(
                ModerationWarning.chat_id == chat_id,
                ModerationWarning.user_id == user_id,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return 0, 0
        return int(row.count or 0), int(row.total_count or 0)


async def add_moderation_warning(
    chat_id: int,
    user_id: int,
    reason: str,
    message_id: int | None = None,
) -> int:
    """Persist and return the user's current warning count for this group."""
    import time

    async with async_session() as session:
        result = await session.execute(
            select(ModerationWarning).where(
                ModerationWarning.chat_id == chat_id,
                ModerationWarning.user_id == user_id,
            )
        )
        row = result.scalar_one_or_none()

        if row is None:
            row = ModerationWarning(
                chat_id=chat_id,
                user_id=user_id,
                count=1,
                total_count=1,
                last_reason=reason,
                last_message_id=message_id,
                updated_at=str(int(time.time())),
            )
            session.add(row)
        else:
            row.count = int(row.count or 0) + 1
            row.total_count = int(row.total_count or 0) + 1
            row.last_reason = reason
            row.last_message_id = message_id
            row.updated_at = str(int(time.time()))

        await session.commit()
        return int(row.count)


async def reset_moderation_warnings(chat_id: int, user_id: int) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(ModerationWarning).where(
                ModerationWarning.chat_id == chat_id,
                ModerationWarning.user_id == user_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.count = 0
            await session.commit()


def analyze_moderation_text(text: str):
    """
    Return (matched, severity, reason).
    This is deliberately local and deterministic; an AI classifier can be
    layered on later without replacing the persistent warning system.
    """
    normalized = _normalize_moderation_text(text)

    if not normalized:
        return False, 0, None

    # مطابقة دقيقة تمنع التقاط الكلمة داخل كلمة أخرى.
    # نضع مسافات حول النص والتعبير حتى تعمل الكلمات والعبارات متعددة الكلمات
    # بشكل صحيح، بينما تبقى الصيغ المكتوبة بدون مسافات التي أضيفت للقائمة مدعومة.
    padded_text = f" {normalized} "

    for term in MODERATION_HIGH_SEVERITY_TERMS:
        normalized_term = _normalize_moderation_text(term)
        if normalized_term and f" {normalized_term} " in padded_text:
            return True, 3, "إساءة شديدة"

    for term in MODERATION_OFFENSIVE_TERMS:
        normalized_term = _normalize_moderation_text(term)
        if normalized_term and f" {normalized_term} " in padded_text:
            return True, 1, "ألفاظ نابية"

    return False, 0, None


async def check_bad_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_chat or update.effective_chat.type not in ["group", "supergroup"]:
        return False

    if not update.message or not update.message.text or not update.effective_user:
        return False

    matched, severity, reason = analyze_moderation_text(update.message.text)
    if not matched:
        return False

    user = update.effective_user
    chat_id = update.effective_chat.id

    # المشرفون ومالك البوت لا يدخلون في نظام التحذيرات التلقائي.
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        if member.status in ["administrator", "creator"] or user.id == ADMIN_ID:
            return False
    except Exception:
        pass

    warning_count = await add_moderation_warning(
        chat_id=chat_id,
        user_id=user.id,
        reason=reason or "مخالفة",
        message_id=update.message.message_id,
    )

    try:
        await update.message.delete()
    except Exception:
        pass

    if warning_count >= MODERATION_WARNING_LIMIT:
        try:
            await context.bot.restrict_chat_member(
                chat_id,
                user.id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            await reset_moderation_warnings(chat_id, user.id)
            await context.bot.send_message(
                chat_id,
                f"🔇 تم كتم {user.first_name} تلقائياً بعد وصوله إلى "
                f"{MODERATION_WARNING_LIMIT} تحذيرات بسبب {reason or 'مخالفة قواعد المجموعة'}.",
            )
        except Exception:
            await context.bot.send_message(
                chat_id,
                f"⚠️ تم تسجيل التحذير الثالث على {user.first_name}، "
                "لكن تعذر تنفيذ الكتم تلقائياً.",
            )
    else:
        try:
            await context.bot.send_message(
                chat_id,
                f"⚠️ تحذير لـ {user.first_name}: {reason or 'مخالفة قواعد المجموعة'} "
                f"({warning_count}/{MODERATION_WARNING_LIMIT}).",
            )
        except Exception:
            pass

    return True

# ====================================================
# --- أزرار القوائم الأساسية ---
# ====================================================
def get_main_keyboard(bot_username, is_admin, is_group_owner=False):
    keyboard = [
        [InlineKeyboardButton("💎 ميزات VIP الحصرية", callback_data="vip_menu")],
            [InlineKeyboardButton("➕ تفعيل البوت بمجموعة", url=f"https://t.me/{bot_username}?startgroup=true")],
        [InlineKeyboardButton("📜 أوامر الأعضاء", callback_data="cmd_user"), InlineKeyboardButton("👮 أوامر المجموعة", callback_data="cmd_group")],
        [InlineKeyboardButton("🎮 الألعاب والترفيه", callback_data="cmd_games"), InlineKeyboardButton("🛠️ أدوات وميديا", callback_data="cmd_tools")],
        [InlineKeyboardButton("💰 نظام الربح الذاتي في سوريا", callback_data="earn_sys")],
            [InlineKeyboardButton("📖 دليل وشرح البوت", callback_data="bot_guide")],
        [InlineKeyboardButton("💡 تقديم مقترح", callback_data="btn_suggest"), InlineKeyboardButton("☕ دعم المطور", callback_data="btn_donate")]
    ]
    if is_admin:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم المطور (خاص)", callback_data="admin_main")])
    if is_group_owner:
        keyboard.append([InlineKeyboardButton("⚙️ إعدادات المجموعة", callback_data="owner_group:open")])
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
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    chat = update.effective_chat
    settings = await group_feature_store.settings_for(chat.id) if chat else None
    if settings and not settings.welcome_enabled:
        return
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            continue

        custom_text = render_welcome(
            settings.welcome_template if settings else None,
            name=member.first_name or "عضو جديد",
            username=member.username,
            user_id=member.id,
            chat_name=chat.title if chat else None,
        )
        if custom_text is not None:
            await update.message.reply_text(custom_text, parse_mode=None)
            continue
        
        user_mention = f"[{member.first_name}](tg://user?id={member.id})"
        user_handle = f"@{member.username}" if member.username else "بدون معرف"
        chat_title = update.effective_chat.title
        
        text = (
            f"🎉 **عضو جديد انضم إلى المجموعة!**\n\n"
            f"👤 **العضو:** {user_mention}\n"
            f"🆔 **الآيدي:** `{member.id}`\n"
            f"🏷️ **اليوزر:** {user_handle}\n"
            f"🏰 **المجموعة:** {chat_title}\n\n"
            f"🌸 **أهلاً بك في عائلتنا! نتمنى لك وقتاً ممتعاً ومفيداً.**"
        )
        
        keyboard = [
            [InlineKeyboardButton("📢 قناة البوت الرسمية", url=CHANNEL_URL)],
            [InlineKeyboardButton("🤖 تحدث مع لارا", url=f"https://t.me/{context.bot.username}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await update.message.reply_text(
                text, 
                reply_markup=reply_markup, 
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except Exception:
            await update.message.reply_text(text, parse_mode=None)

async def cmd_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    bot_obj = await context.bot.get_me()
    
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user.id))
        u = res.scalar_one_or_none()
        inv_count = u.invites_count if u and u.invites_count else 0

    ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user.id}"
    text = (
        f"🎁 **نظام المشاركة وجلب الأعضاء:**\n\n"
        f"🔗 **رابط الدعوة الخاص بك:**\n`{ref_link}`\n\n"
        f"📊 **عدد الأشخاص الذين دعوتهم:** `{inv_count}` شخص\n\n"
        f"💡 شارك الرابط مع أصدقائك وفي المجموعات لزيادة دعواتك!"
    )
    keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة", callback_data="back_main")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


# ==================== FINANCIAL & REWARDS SYSTEM ====================


async def private_start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
    if not await handle_check_sub(update, context):
        return
    bot_obj = await context.bot.get_me()
    
    # 1. قائمة نظام الإحالات والأرباح
    fin_keyboard = [
        [InlineKeyboardButton("📊 رصيدي وإحالاتي", callback_data="my_ref_status"), InlineKeyboardButton("🎁 الجائزة اليومية", callback_data="claim_daily")],
        [InlineKeyboardButton("💸 استبدال النقاط", callback_data="start_cashout")]
    ]
    fin_text = (
        "🌸 **أهلاً بك في بوت لارا!**\n\n"
        "💡 يمكنك جمع النقاط عبر إحالة أصدقائك واستبدالها برصيد أو تحويل سيريتل كاش حقيقي.\n\n"
        "👇 اختر من القائمة أدناه:"
    )

    # 2. قائمة خدمات البوت العامة والإدارة
    main_keyboard = [
        [InlineKeyboardButton("➕ تفعيل البوت بمجموعة", url=f"https://t.me/{bot_obj.username}?startgroup=true")],
        [InlineKeyboardButton("👮‍♂️ أوامر المجموعة", callback_data="cmd_group_help"), InlineKeyboardButton("📜 أوامر الأعضاء", callback_data="cmd_member_help")],
        [InlineKeyboardButton("🛠️ أدوات وميديا", callback_data="cmd_tools_help"), InlineKeyboardButton("🎮 الألعاب والترفيه", callback_data="cmd_games_help")],
        [InlineKeyboardButton("☕ دعم المطور", callback_data="btn_support"), InlineKeyboardButton("💡 تقديم اقتراح", callback_data="btn_suggest")]
    ]
    if update.effective_user and update.effective_user.id == ADMIN_ID:
        main_keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم المطور (خاص)", callback_data="adm_panel")])

    main_text = "🌸 **روبوت لارا (V5.9 Legendary):**\n\n✨ اختر من القائمة أدناه:"

    if update.message:
        await update.message.reply_text(fin_text, reply_markup=InlineKeyboardMarkup(fin_keyboard), parse_mode="Markdown")
        await update.message.reply_text(main_text, reply_markup=InlineKeyboardMarkup(main_keyboard), parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.edit_text(fin_text, reply_markup=InlineKeyboardMarkup(fin_keyboard), parse_mode="Markdown")

async def handle_ref_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    bot_obj = await context.bot.get_me()

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user.id))
        u = res.scalar_one_or_none()
        inv_count = u.invites_count if u and u.invites_count else 0
        pts = u.points if u and u.points else 0

    ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user.id}"
    text = (
        f"📊 **حسابك وإحالاتك:**\n\n"
        f"💰 **رصيد النقاط:** `{pts}` نقطة\n"
        f"👥 **عدد الإحالات:** `{inv_count}` مشترك\n\n"
        f"🎁 **مكافأة الإحالة:** 100 نقطة لكل شخص ينضم عبر رابطك!\n"
        f"🔗 **رابط الدعوة الخاص بك:**\n`{ref_link}`"
    )
    keyboard = [[InlineKeyboardButton("🔙 العودة للقائمة", callback_data="back_private_main")]]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_daily_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    today_str = str(date.today())

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user.id))
        u = res.scalar_one_or_none()
        if not u:
            u = User(
                telegram_id=user.id,
                first_name=user.first_name,
                username=user.username,
                points=0,
                invites_count=0
            )
            session.add(u)
            await session.commit()

        inv_count = u.invites_count or 0
        if inv_count < 1:
            await query.answer("⚠️ يجب أن تكون لديك إحالة واحدة على الأقل لتفعيل الجائزة اليومية!", show_alert=True)
            return

        if u.last_daily == today_str:
            await query.answer("⏳ لقد حصلت على جائزتك اليومية بالفعل! عد غداً.", show_alert=True)
            return

        u.points = (u.points or 0) + 10
        u.last_daily = today_str
        await session.commit()
        pts = u.points

    await query.answer(f"🎉 تم إضافة 10 نقاط لعملة الجائزة اليومية! رصيدك الآن: {pts} نقطة", show_alert=True)

async def handle_start_cashout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user.id))
        u = res.scalar_one_or_none()
        pts = u.points if u and u.points else 0

    if pts < 10000:
        needed = 10000 - pts
        text = (
            f"❌ **رصيدك غير كافٍ للاستبدال!**\n\n"
            f"💰 **رصيدك الحالي:** `{pts}` نقطة\n"
            f"🎯 **الحد الأدنى للسحب:** `10,000` نقطة (تساوي 10,000 ل.س / 100 ليرة جديدة)\n"
            f"⏳ **ينقصك:** `{needed}` نقطة لتتمكن من السحب."
        )
        keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="back_private_main")]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    text = (
        f"💸 **استبدال النقاط وسحب الأرباح:**\n\n"
        f"رصيدك الحالي: `{pts}` نقطة\n"
        f"سوف يتم استبدال `10,000` نقطة مقابل **10,000 ليرة سورية** (100 ليرة جديدة).\n\n"
        f"اختر طريقة الاستلام المناسبة لك:"
    )
    keyboard = [
        [InlineKeyboardButton("📱 سيريتل كاش", callback_data="cashout_type_syriatel"), InlineKeyboardButton("💳 رصيد تحويل", callback_data="cashout_type_balance")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="back_private_main")]
    ]
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_cashout_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pay_type = "سيريتل كاش" if query.data == "cashout_type_syriatel" else "رصيد تحويل"
    context.user_data["cashout_type"] = pay_type
    context.user_data["awaiting_phone"] = True

    text = (
        f"📱 **إدخال رقم الهاتف:**\n\n"
        f"طريقة الدفع المختارة: **{pay_type}**\n"
        f"يرجى إرسال رقم هاتفك المحمول (مثل `09xxxxxxx`) الآن في الرسالة القادمة:"
    )
    await query.message.edit_text(text, parse_mode="Markdown")

async def process_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_phone"):
        return False

    phone = update.message.text.strip()
    if not phone.isdigit() or len(phone) < 9:
        await update.message.reply_text("❌ رقم الهاتف غير صحيح. يرجى إرسال رقم هاتف محمول مكوّن من أرقام فقط (مثل `0912345678`):")
        return True

    context.user_data["awaiting_phone"] = False
    context.user_data["cashout_phone"] = phone
    pay_type = context.user_data.get("cashout_type", "سيريتل كاش")

    text = (
        f"📋 **تأكيد طلب السحب:**\n\n"
        f"💵 **المبلغ:** 10,000 ليرة سورية (100 ليرة جديدة)\n"
        f"💳 **طريقة الدفع:** {pay_type}\n"
        f"📱 **الرقم:** `{phone}`\n\n"
        f"هل أنت تأكد من صحة البيانات وتريد إتمام الطلب؟"
    )
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد الطلب", callback_data="confirm_cashout_final")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="back_private_main")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return True

async def handle_confirm_cashout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    phone = context.user_data.get("cashout_phone", "غير محدد")
    pay_type = context.user_data.get("cashout_type", "سيريتل كاش")

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user.id))
        u = res.scalar_one_or_none()
        if not u or (u.points or 0) < 10000:
            await query.message.edit_text("❌ تعذر إتمام الطلب، رصيدك أقل من 10,000 نقطة!")
            return

        u.points -= 10000
        await session.commit()

    # Notify User
    text_user = (
        f"✅ **تم تسجيل طلب السحب بنجاح!**\n\n"
        f"📱 **الرقم:** `{phone}`\n"
        f"💳 **النوع:** {pay_type}\n\n"
        f"⏳ **في غضون 12 ساعة سيتم تحويل المبلغ إلى حسابك.** شكراً لثقتك بنا!"
    )
    await query.message.edit_text(text_user, parse_mode="Markdown")

    # Notify Admin
    try:
        admin_text = (
            f"🚨 **طلب سحب جديد (استبدال نقاط)!**\n\n"
            f"👤 **العضو:** {user.first_name} ([{user.id}](tg://user?id={user.id}))\n"
            f"🏷️ **اليوزر:** @{user.username if user.username else 'بدون'}\n"
            f"📱 **الرقم للتحويل:** `{phone}`\n"
            f"💳 **الطريقة:** {pay_type}\n"
            f"💰 **المبلغ المطلوب:** 10,000 ل.س (مقابل 10,000 نقطة)"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode="Markdown")
    except Exception:
        pass

# ====================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    # 1. التحقق من الاشتراك الإجباري أولاً أو معالجته
    if not await handle_check_sub(update, context):
        return

    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user.id))
        u = res.scalar_one_or_none()
        
        if not u:
            # معالجة الإحالة إذا وجدت
            inviter_id = None
            if context.args and context.args[0].startswith("ref_"):
                try:
                    inviter_id = int(context.args[0].replace("ref_", ""))
                except ValueError:
                    pass

            # إنشاء المستخدم الجديد مع حفظ معرف المُحيل
            new_user = User(
                telegram_id=user.id,
                first_name=user.first_name,
                username=user.username,
                referred_by=inviter_id,
                points=0,
                invites_count=0
            )
            session.add(new_user)
            
            # إذا وجد مُحيل، نقوم بزيادة عداد الدعوات ونقاطه فوراً!
            if inviter_id and inviter_id != user.id:
                inviter_res = await session.execute(select(User).where(User.telegram_id == inviter_id))
                inviter = inviter_res.scalar_one_or_none()
                if inviter:
                    inviter.invites_count = (inviter.invites_count or 0) + 1
                    inviter.points = (inviter.points or 0) + 10  # إضافة 10 نقاط أو رصيد للمُحيل (يمكنك تعديلها حسب رغبتك)
            
            await session.commit()

    # إرسال القائمة الرئيسية للمستخدم بنجاح
    bot_obj = await context.bot.get_me()
    main_text = "🌸 **روبوت لارا (V5.9 Legendary):**\n\n✨ اختر من القائمة أدناه:"
    owner_here = await is_group_owner(update, context)
    await update.message.reply_text(
        main_text,
        reply_markup=get_main_keyboard(bot_obj.username, user.id == ADMIN_ID, owner_here),
        parse_mode="Markdown"
    )

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    chat = update.effective_chat
    reply_msg = update.message.reply_to_message if update.message else None

    # عند رد المشرف على رسالة عضو باستخدام "معلوماتي"، اعرض معلومات العضو المستهدف.
    if reply_msg and chat and chat.type in ["group", "supergroup"]:
        try:
            member = await context.bot.get_chat_member(chat.id, u.id)
            is_admin = member.status in ["administrator", "creator"] or u.id == ADMIN_ID
        except Exception:
            is_admin = u.id == ADMIN_ID

        if is_admin and reply_msg.from_user:
            target = reply_msg.from_user
            warning_count, total_warning_count = await get_moderation_warning_stats(chat.id, target.id)
            return await update.message.reply_text(
                f"👤 **معلومات العضو:**\n"
                f"الاسم: {target.first_name}\n"
                f"🔑 الآيدي: `{target.id}`\n"
                f"⚠️ التحذيرات الحالية: `{warning_count}/{MODERATION_WARNING_LIMIT}`\n"
        f"📊 إجمالي التحذيرات: `{total_warning_count}`",
                parse_mode=None,
            )

    warning_count = 0
    total_warning_count = 0
    if chat and chat.type in ["group", "supergroup"]:
        warning_count, total_warning_count = await get_moderation_warning_stats(chat.id, u.id)

    await update.message.reply_text(
        f"🆔 **معلوماتك:**\n"
        f"👤 الاسم: {u.first_name}\n"
        f"🔑 الآيدي: `{u.id}`\n"
        f"⚠️ التحذيرات الحالية: `{warning_count}/{MODERATION_WARNING_LIMIT}`\n"
        f"📊 إجمالي التحذيرات: `{total_warning_count}`",
        parse_mode=None,
    )

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_t = time.time()
    msg = await update.message.reply_text("⚡ جاري قياس السرعة...")
    ping_ms = round((time.time() - start_t) * 1000, 2)
    await msg.edit_text(f"⚡ **سرعة الاستجابة:** `{ping_ms} ms`", parse_mode=None)

async def cmd_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("🔢 استخدم: `/calc 5+5`", parse_mode=None)
    try:
        from arsyra.conversation import calculate_local_request
        expression = " ".join(context.args)
        if not re.fullmatch(
            r"\s*[-+]?\d+(?:\.\d+)?(?:\s*(?:\*\*|//|[+*/%\-])\s*[-+]?\d+(?:\.\d+)?)+\s*",
            expression,
        ):
            raise ValueError("invalid arithmetic expression")
        res = calculate_local_request(expression)
        if res is None:
            raise ValueError("invalid arithmetic expression")
        await update.message.reply_text(f"🔢 **النتيجة:** `{res}`", parse_mode=None)
    except Exception:
        await update.message.reply_text("⚠️ خطأ في المعادلة.")

async def cmd_xo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    XO_GAMES[chat_id] = {"board": [""] * 9, "turn": "❌", "p1": update.effective_user.id}
    await update.message.reply_text("🎮 **لعبة إكس أو (XO) بدأت!**\nدور اللاعب: **❌**", reply_markup=get_xo_keyboard(XO_GAMES[chat_id]["board"]), parse_mode=None)

# ====================================================
# --- موجه الأزرار (Button Router) ---
# ====================================================
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    if data.startswith("owner_group:"):
        await handle_owner_callback(update, context)
        return
    try:
        await query.answer()
    except Exception:
        pass
    uid = update.effective_user.id
    chat_id = getattr(getattr(query, 'message', None), 'chat_id', None)
    bot_obj = await context.bot.get_me()
    back_main = [[InlineKeyboardButton("🔙 عودة للرئيسية", callback_data="main_menu")]]

    if data == "earn_sys":
        fin_keyboard = [
            [InlineKeyboardButton("📊 رصيدي وإحالاتي", callback_data="my_ref_status"), InlineKeyboardButton("🎁 الجائزة اليومية", callback_data="claim_daily")],
            [InlineKeyboardButton("💸 استبدال النقاط", callback_data="start_cashout")],
            [InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="main_menu")]
        ]
        fin_text = (
            "🌸 **نظام الربح الذاتي في سوريا:**\n\n"
            "💡 يمكنك جمع النقاط عبر إحالة أصدقائك واستبدالها برصيد أو تحويل سيريتل كاش حقيقي.\n\n"
            "👇 اختر من القائمة أدناه:"
        )
        try:
            await query.message.edit_text(fin_text, reply_markup=InlineKeyboardMarkup(fin_keyboard), parse_mode=None)
        except Exception:
            pass

    if data == "main_menu":
        text = "🌸 **روبوت لارا (V5.9 Legendary):**\n\n✨ اختر من القائمة أدناه:"
        owner_here = await is_group_owner(update, context)
        await query.message.edit_text(text, reply_markup=get_main_keyboard(bot_obj.username, uid == ADMIN_ID, owner_here), parse_mode=None)

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
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(back_main), parse_mode=None)
    elif data in ["check_sub", "check_subscription"]:
        if await is_user_subscribed(update.effective_user.id, context):
            await query.answer("✅ تم التحقق بنجاح! أهلاً بك.", show_alert=True)
            text = "🌸 **روبوت لارا (V5.9 Legendary):**\n\n✨ اختر من القائمة أدناه:"
            owner_here = await is_group_owner(update, context)
            await query.message.edit_text(text, reply_markup=get_main_keyboard(bot_obj.username, uid == ADMIN_ID, owner_here), parse_mode=None)
        else:
            await query.answer("❌ لم تشترك في القناة بعد! يرجى الاشتراك في القناة أولاً.", show_alert=True)
    elif data == "vip_menu":
        await handle_vip_menu(update, context)
    elif data == "start_video_edit":
        await handle_start_video_edit(update, context)
    elif data == "vip_stats":
        await handle_vip_stats(update, context)
    elif data == "owner_subs":
        await handle_owner_subs_callback(update, context)
    elif data == "cmd_group":
        msg = """👮 **دليل أوامر إدارة المجموعة (litharm Edition):**

🧹 **1. الحذف والتطهير:**
• `مسح 10` : مسح آخر 10 رسائل (من 1 إلى 100).
• `تنظيف الصور` : مسح الصور الأخيرة في المجموعه.
• `مسح` (بالرد) : مسح الرسالة المحددة.

🔒 **2. قفل وفتح الوسائط:**
• `قفل الصور` / `فتح الصور`
• `قفل الفيديو` / `فتح الفيديو`
• `قفل الروابط` / `فتح الروابط`
• `قفل الملصقات` / `فتح الملصقات`
• `قفل الصوتيات` / `فتح الصوتيات`

🔨 **3. العقوبات والتحكم (بالرد):**
• `حظر` / `الغاء الحظر`
• `كتم` / `الغاء الكتم`
• `طرد` | `تحذير` | `تثبيت`"""
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(back_main), parse_mode=None)


    elif data == "bot_guide":
        guide_text = (
            "🌟 **الدليل الشامل والموسّع لروبوت لارا (V5.9 Legendary)** 🌟\n\n"
            "أهلاً بك يا بطل في المرجع الرسمي للبوت! لقد صُمم هذا النظام الذكي ليمنحك تجربة استثنائية، سلسة، وآمنة تماماً. إليك التفاصيل الكاملة لكافة الأقسام والمميزات:\n\n"
            "📌 **أولاً: تفاصيل الأقسام والقوائم الرئيسية**\n"
            "• 📜 **أوامر الأعضاء:** استعراض كافة الأوامر الشخصية المتاحة لك للتفاعل مع البوت في الخاص بكل سهولة.\n"
            "• 👮 **أوامر المجموعة:** أدوات الإدارة المتقدمة، حماية المجموعات، وتنظيم تفاعل الأعضاء بكفاءة عالية.\n"
            "• 🎮 **الألعاب والترفيه:** قسم الترفيه التفاعلي الخارق (حجرة ورقة مقص، النرد 🎲، السهم 🎯، كرة السلة 🏀، وكرة القدم ⚽).\n"
            "• 🛠️ **أدوات وميديا:** حزمة الخدمات السريعة، الأدوات المساعدة، والخصائص التقنية المتنوعة.\n"
            "• 💰 **نظام الربح الذاتي:** محطتك الخاصة لجمع النقاط، تتبع رصيدك، الحصول على الجائزة اليومية، وإدارة نظام الإحالات.\n\n"
            "💎 **ثانياً: نظام الإحالات والربح (كيف تربح؟)**\n"
            "• **رابط الإحالة:** شارك رابط الدعوة الفريد الخاص بك مع أصدقائك وفي المجموعات.\n"
            "• **المكافآت:** يحصل كل صديق ينضم عبرك على ترحيب خاص، وتُسجل إحالتك ونقاطك تلقائياً في قاعدة البيانات.\n"
            "• **الاستبدال:** استبدل نقاطك المتراكمة برصيد أو تحويلات (**سيريتل كاش**) بكل شفافية ويسر.\n\n"
            "⚖️ **ثالثاً: الشروط والأحكام العامة للخدمة**\n"
            "• الالتزام التام بالاستخدام العادل والنزيه لجميع ميزات البوت.\n"
            "• يُمنع منعاً باتاً محاولة التلاعب بالنقاط، استغلال الثغرات، أو استخدام حسابات وهمية للإحالات.\n"
            "• أي محاولة تلاعب متعمدة تعرض الحساب للحظر النهائي التلقائي حفاظاً على استقرار النظام.\n\n"
            "🚀 **رابعاً: كيفية التفعيل والبدء الفوري**\n"
            "1. اضغط على زر \"تفعيل البوت بمجموعة\" لإضافته لمجموعتك المفضلة.\n"
            "2. أرسل الأمر /start في أي وقت للرجوع فوراً للوحة التحكم الرئيسية.\n"
            "3. تصفح الأقسام بسلاسة عبر الأزرار الشفافة أدناه.\n\n"
            "🛠️ **الدعم الفني والتواصل:**\n"
            "واجهتك أي مشكلة، استفسار، أو تريد التبليغ عن خطأ؟ تواصل فوراً مع المطور الأساسي:\n"
            "👤 **المطور:** [litharm](https://t.me/litharm)"
        )
        guide_kb = [
            [InlineKeyboardButton("🛠️ تواصل مع المطور", url="https://t.me/litharm")],
            [InlineKeyboardButton("🔙 عودة للرئيسية", callback_data="main_menu")]
        ]
        await query.message.edit_text(guide_text, reply_markup=InlineKeyboardMarkup(guide_kb), parse_mode="Markdown", disable_web_page_preview=True)

    elif data == "cmd_games":
        keyboard = [
            [InlineKeyboardButton("❌⭕ إكس أو", callback_data="start_xo"), InlineKeyboardButton("🧠 الأسئلة", callback_data="start_trivia")],
            [InlineKeyboardButton("✊✋✌️ حجرة ورقة مقص", callback_data="start_rps")],
            [InlineKeyboardButton("🎲 النرد", callback_data="g_dice"), InlineKeyboardButton("🎯 السهم", callback_data="g_dart")],
            [InlineKeyboardButton("🏀 السلة", callback_data="g_basket"), InlineKeyboardButton("⚽ القدم", callback_data="g_football")],
            [InlineKeyboardButton("🔙 عودة للرئيسية", callback_data="main_menu")]
        ]
        await query.message.edit_text("🎮 **قسم الألعاب والتسلية الخارق:**\n\nاختر لعبتك المفضلة:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

    elif data == "start_rps":
        kb = [
            [InlineKeyboardButton("✊ حجرة", callback_data="rps_rock"), InlineKeyboardButton("✋ ورقة", callback_data="rps_paper"), InlineKeyboardButton("✌️ مقص", callback_data="rps_scissors")]
        ]
        await query.message.edit_text("🎮 **لعبة حجرة ورقة مقص!**\n\nاختر حركتك:", reply_markup=InlineKeyboardMarkup(kb), parse_mode=None)

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
        await query.message.edit_text(final_msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 العب مرة تانية", callback_data="start_rps")], [InlineKeyboardButton("🔙 رجوع", callback_data="cmd_games")]]), parse_mode=None)

    elif data == "start_xo":
        await query.message.delete()
        XO_GAMES[chat_id] = {"board": [""] * 9, "turn": "❌", "p1": uid}
        await context.bot.send_message(chat_id, "🎮 **لعبة إكس أو (XO) بدأت!**\nدور اللاعب: **❌**", reply_markup=get_xo_keyboard(XO_GAMES[chat_id]["board"]), parse_mode=None)

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
            await query.message.edit_text(f"🏆 **انتهت اللعبة وفاز اللاعب {winner}!** 🎉", reply_markup=get_xo_keyboard(b), parse_mode=None)
            del XO_GAMES[chat_id]
            return
        elif "" not in b:
            await query.message.edit_text("🤝 **تعادل الفريقان!**", reply_markup=get_xo_keyboard(b), parse_mode=None)
            del XO_GAMES[chat_id]
            return
        game["turn"] = "⭕" if game["turn"] == "❌" else "❌"
        await query.message.edit_text(f"🎮 **لعبة XO جارية..**\nدور اللاعب: **{game['turn']}**", reply_markup=get_xo_keyboard(b), parse_mode=None)

    elif data == "xo_stop":
        if chat_id in XO_GAMES: del XO_GAMES[chat_id]
        await query.message.edit_text("❌ تم إنهاء لعبة XO الحالية.")

    elif data == "start_trivia":
        await query.message.delete()
        q_data = random.choice(TRIVIA_QUESTIONS)
        TRIVIA_GAMES[chat_id] = {"q": q_data["q"], "a": q_data["a"]}
        await context.bot.send_message(chat_id, f"🧠 **لعبة الأسئلة الثقافية:**\n\n❓ **السؤال:** {q_data['q']}\n\n*(اكتب الإجابة بالدردشة الآن!)*", parse_mode=None)

    elif data == "g_dice": await context.bot.send_dice(chat_id, emoji="🎲")
    elif data == "g_dart": await context.bot.send_dice(chat_id, emoji="🎯")
    elif data == "g_basket": await context.bot.send_dice(chat_id, emoji="🏀")
    elif data == "g_football": await context.bot.send_dice(chat_id, emoji="⚽")

    elif data == "cmd_tools":
        msg = "🛠️ **أدوات إضافية:**\n• `/calc` - حساب معادلات رياضية\n• `نزلي [اسم الأغنية]` - تحميل وسحب الأغاني mp3"
        await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(back_main), parse_mode=None)

    elif data == "btn_donate":
        await query.message.reply_text("💖 شكراً لدعمك المطور litharm! البوت مستمر بفضلكم.")

    elif data == "admin_main" and uid == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("📢 إذاعة للكل", callback_data="adm_broadcast"), InlineKeyboardButton("➕ إضافة رد", callback_data="adm_add_reply")],
            [InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats"), InlineKeyboardButton("🖥️ حالة السيرفر", callback_data="adm_sys_status")],
            [InlineKeyboardButton("🔙 عودة للرئيسية", callback_data="main_menu")]
        ]
        await query.message.edit_text("⚙️ **لوحة المطور الخاصة (litharm):**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

    elif data == "adm_sys_status" and uid == ADMIN_ID:
        await query.edit_message_text(get_system_telemetry(), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data="admin_main")]]), parse_mode=None)

    elif data == "adm_stats" and uid == ADMIN_ID:
        async with async_session() as session:
            u_cnt = (await session.execute(select(func.count(User.id)))).scalar()
            r_cnt = (await session.execute(select(func.count(AutoReply.id)))).scalar()
        await query.edit_message_text(f"📊 **الإحصائيات:**\n👥 المستخدمون: `{u_cnt}`\n💡 الردود المحفوظة: `{r_cnt}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data="admin_main")]]), parse_mode=None)

# ====================================================
# --- محادثات الإدارة والمدخلات ---
# ====================================================
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("↩️ تم الإلغاء والعودة للوضع الطبيعي.", parse_mode=None)
    return ConversationHandler.END

async def add_reply_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    await query.message.reply_text("➕ أرسل كلمة المفتاح:\n*(أو /cancel للإلغاء)*", parse_mode=None)
    return WAIT_TRIGGER

async def add_reply_trig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['trig'] = update.message.text.strip()
    await update.message.reply_text("💬 أرسل نص الرد:", parse_mode=None)
    return WAIT_RESPONSE

async def add_reply_resp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trig, resp = context.user_data['trig'], update.message.text.strip()
    async with async_session() as session:
        session.add(AutoReply(trigger=trig, response=resp))
        await session.commit()
    await update.message.reply_text(f"✅ تم حفظ الرد بنجاح:\n`{trig}` -> `{resp}`", parse_mode=None)
    return ConversationHandler.END

async def suggest_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("💡 أرسل مقترحك للمطور:\n*(أو /cancel للإلغاء)*", parse_mode=None)
    return WAIT_SUGGESTION

async def suggest_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with async_session() as session:
        session.add(Suggestion(user_id=update.effective_user.id, text=update.message.text.strip()))
        await session.commit()
    await update.message.reply_text("✅ تم إرسال مقترحك بنجاح. شكراً لك! 🌸", parse_mode=None)
    return ConversationHandler.END

async def broadcast_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    await query.message.reply_text("📢 أرسل رسالة الإذاعة للجميع:\n*(أو /cancel للإلغاء)*", parse_mode=None)
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
    await update.message.reply_text(f"✅ تمت الإذاعة إلى `{count}` مستخدم بنجاح.", parse_mode=None)
    return ConversationHandler.END

# ====================================================
# --- موجه الرسائل النصية الشامل والآمن ---
# ====================================================

async def is_user_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat.type in ["group", "supergroup"]:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in ["administrator", "creator"]
    return True

async def handle_purge_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.message.text:
        return False
    
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    # Check if command is purge
    if text.startswith("مسح ") or text == "مسح":
        if not await is_user_admin(update, context):
            await update.message.reply_text("⚠️ هذا الأمر مخصص للمشرفين فقط!")
            return True
            
        try:
            parts = text.split()
            count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            count = min(max(count, 1), 100) # Limit between 1 and 100
            
            current_msg_id = update.message.message_id
            deleted_count = 0
            
            for m_id in range(current_msg_id, current_msg_id - count - 1, -1):
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=m_id)
                    deleted_count += 1
                except Exception:
                    pass
            
            status_msg = await context.bot.send_message(chat_id=chat_id, text=f"🧹 تم مسح {deleted_count} رسالة بنجاح.")
            await asyncio.sleep(3)
            await status_msg.delete()
            return True
        except Exception as e:
            return False

    elif text == "تنظيف الصور":
        if not await is_user_admin(update, context):
            await update.message.reply_text("⚠️ هذا الأمر مخصص للمشرفين فقط!")
            return True
            
        current_msg_id = update.message.message_id
        await update.message.delete()
        # Clean recent potential photo messages
        for m_id in range(current_msg_id - 1, current_msg_id - 30, -1):
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=m_id)
            except Exception:
                pass
        return True
        
    return False


async def handle_lock_toggle_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.message.text:
        return False
    
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    lock_map = {
        "قفل الصور": ("lock_photos", True, "🔒 تم قفل الصور بنجاح."),
        "فتح الصور": ("lock_photos", False, "🔓 تم فتح الصور بنجاح."),
        "قفل الفيديو": ("lock_videos", True, "🔒 تم قفل الفيديو بنجاح."),
        "فتح الفيديو": ("lock_videos", False, "🔓 تم فتح الفيديو بنجاح."),
        "قفل الروابط": ("lock_links", True, "🔒 تم قفل الروابط والإعلانات بنجاح."),
        "فتح الروابط": ("lock_links", False, "🔓 تم فتح الروابط للإعضاء."),
        "قفل الملصقات": ("lock_stickers", True, "🔒 تم قفل الملصقات والأنيميشن."),
        "فتح الملصقات": ("lock_stickers", False, "🔓 تم فتح الملصقات."),
        "قفل الصوتيات": ("lock_voice", True, "🔒 تم قفل البصمات والصوتيات."),
        "فتح الصوتيات": ("lock_voice", False, "🔓 تم فتح الصوتيات.")
    }
    
    if text in lock_map:
        if not await is_user_admin(update, context):
            await update.message.reply_text("⚠️ هذا الأمر مخصص للمشرفين فقط!")
            return True
            
        attr, val, msg = lock_map[text]
        async with async_session() as session:
            res = await session.execute(select(GroupSettings).where(GroupSettings.chat_id == chat_id))
            st = res.scalar_one_or_none()
            if not st:
                st = GroupSettings(chat_id=chat_id)
                session.add(st)
            setattr(st, attr, val)
            await session.commit()
        
        await update.message.reply_text(msg)
        return True
    return False

async def check_media_locks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or update.effective_chat.type not in ["group", "supergroup"]:
        return False
    
    if await is_user_admin(update, context):
        return False
        
    chat_id = update.effective_chat.id
    async with async_session() as session:
        res = await session.execute(select(GroupSettings).where(GroupSettings.chat_id == chat_id))
        st = res.scalar_one_or_none()
        if not st:
            return False
            
        msg = update.message
        should_delete = False
        
        if st.lock_photos and msg.photo:
            should_delete = True
        elif st.lock_videos and (msg.video or msg.video_note):
            should_delete = True
        elif st.lock_stickers and (msg.sticker or msg.animation):
            should_delete = True
        elif st.lock_voice and (msg.voice or msg.audio):
            should_delete = True
        elif st.lock_links and msg.text and ("http://" in msg.text or "https://" in msg.text or "t.me/" in msg.text or "@" in msg.text):
            should_delete = True
            
        if should_delete:
            try:
                await msg.delete()
                return True
            except Exception:
                pass
    return False



CHANNEL_USERNAME = "@VIP_ARM0"
CHANNEL_URL = "https://t.me/VIP_ARM0"

async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return await is_user_subscribed(user_id, context)

async def send_sub_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """⚠️ عذراً عزيزي، يجب عليك الاشتراك في قناة البوت أولاً لاستخدامه!

📢 القناة: @VIP_ARM0

اشترك بالقناة ثم اضغط على زر (تحقق من الاشتراك) بالأسفل."""
    keyboard = [
        [InlineKeyboardButton("📢 رابط القناة", url=CHANNEL_URL)],
        [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_sub")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=None)
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode=None)
async def get_user_role_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    
    # Check if Owner
    is_owner = (user_id == ADMIN_ID)
    
    # Check if Group Admin
    is_admin = False
    if chat_type in ["group", "supergroup"]:
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            is_admin = member.status in ["administrator", "creator"]
        except Exception:
            pass

    if is_owner:
        text = (
            "👑 👑 أهلاً بك يا مالك البوت العظيم (litharm)!\n\n"
            "🛠️ 🛠️ لوحة التحكم العليا للخدمات والاشتراكات:\n"
            "• يمكنك متابعة المجموعات وإدارة الاشتراكات.\n"
            "• الوصول إلى كافة أدوات المطور والتحكم الكامل."
        )
        keyboard = [
            [InlineKeyboardButton("📊 إدارة المجموعات والاشتراكات", callback_data="owner_subs")],
            [InlineKeyboardButton("👮 أوامر الإدارة", callback_data="cmd_group"), InlineKeyboardButton("🎮 الألعاب والترفيه", callback_data="cmd_games")],
            [InlineKeyboardButton("🎵 التحميل والخدمات", callback_data="cmd_services"), InlineKeyboardButton("📝 الملاحظات والذكاء", callback_data="cmd_ai")]
        ]
    elif is_admin:
        text = (
            f"👮 👮 أهلاً بك عزيزي المشرف ({update.effective_user.first_name})!**\n\n"
            "إليك أدوات وحزم إدارة المجموعة المتاحة لك:"
        )
        keyboard = [
            [InlineKeyboardButton("👮 أوامر الإدارة والحماية", callback_data="cmd_group")],
            [InlineKeyboardButton("🎮 الألعاب والترفيه", callback_data="cmd_games"), InlineKeyboardButton("🎵 الخدمات العامة", callback_data="cmd_services")]
        ]
    else:
        text = (
            f"👋 👋 أهلاً بك ({update.effective_user.first_name}) في البوت!**\n\n"
            "إليك قائمة الخدمات والترفيه المتاحة لاستخدامك:"
        )
        keyboard = [
            [InlineKeyboardButton("🎮 الألعاب", callback_data="cmd_games"), InlineKeyboardButton("🎵 التحميل والخدمات", callback_data="cmd_services")],
            [InlineKeyboardButton("📝 الملاحظات والذكاء الاصطناعي", callback_data="cmd_ai")]
        ]
        
    return text, InlineKeyboardMarkup(keyboard)

async def handle_owner_subs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if update.effective_user.id != ADMIN_ID:
        await query.answer("⚠️ هذه اللوحة مخصصة لمالك البوت فقط!", show_alert=True)
        return
        
    async with async_session() as session:
        res = await session.execute(select(GroupSettings))
        groups = res.scalars().all()
        
    msg = "📊 **قائمة المجموعات والاشتراكات النشطة:**\n\n"
    if not groups:
        msg += "لا توجد مجموعات مسجلة حالياً في قاعدة البيانات."
    else:
        for g in groups:
            status = "🟢 نشط" if getattr(g, "is_subscribed", True) else "🔴 ملغى"
            msg += f"• مجموعة ID: `{g.chat_id}` | الحالة: {status}\n"
            
    keyboard = [[InlineKeyboardButton("🔙 العودة للرئيسية", callback_data="main_menu")]]
    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def _run_group_custom_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message, chat, actor = update.effective_message, update.effective_chat, update.effective_user
    if not message or not message.text or not chat or chat.type not in ("group", "supergroup") or not actor:
        return False
    group_settings = await group_feature_store.get_settings(chat.id)
    if group_settings and not group_settings.custom_commands_enabled:
        return False
    text = " ".join(message.text.strip().split())
    commands = await group_feature_store.list_commands(chat.id)
    command = next((item for item in sorted(commands, key=lambda c: len(c.name), reverse=True)
                    if text.casefold() == item.normalized_name
                    or text.casefold().startswith(item.normalized_name + " ")), None)
    if command is None:
        return False
    if not command.enabled:
        await message.reply_text("⏸ هذا الأمر متوقف في هذه المجموعة.")
        return True

    if command.required_role != "ADMIN" or command.action not in ACTION_REGISTRY:
        await message.reply_text("❌ إعدادات هذا الأمر غير صالحة؛ لم يتم تنفيذ أي إجراء.")
        return True
    if not await is_group_admin(update, context):
        await message.reply_text("❌ هذا الأمر مخصص لمشرفي المجموعة.")
        return True

    action = command.action
    reply = message.reply_to_message
    tail = text[len(command.name):].strip()
    target_id = reply.from_user.id if reply and reply.from_user else None
    target_name = reply.from_user.first_name if reply and reply.from_user else ""
    requested_username = None
    if target_id is None:
        for entity in message.entities or ():
            if str(entity.type) == "text_mention" and getattr(entity, "user", None):
                target_id = entity.user.id
                target_name = entity.user.first_name or ""
                break
    if target_id is None:
        match = re.search(r"(?<!\w)(\d{5,20})(?!\w)", tail)
        if match:
            target_id = int(match.group(1))
    if target_id is None:
        username_match = re.search(r"(?<!\w)@([A-Za-z0-9_]{5,32})\b", tail)
        if username_match:
            requested_username = username_match.group(1).casefold()
            async with async_session() as session:
                cached_user = await session.scalar(select(User).where(
                    func.lower(User.username) == requested_username))
                if cached_user:
                    target_id = int(cached_user.telegram_id)
                    target_name = cached_user.first_name or ""
    if command.target_type == "MESSAGE" and not reply:
        await message.reply_text("⚠️ استخدم الأمر بالرد على الرسالة المطلوب تنفيذ الإجراء عليها.")
        return True
    if command.target_type in {"USER", "USER_ID"} and target_id is None:
        if "@" in tail:
            await message.reply_text("⚠️ لم أتمكن من مطابقة @username بمستخدم معروف والتحقق من عضويته. استخدم الرد على رسالته أو Telegram user ID.")
        else:
            await message.reply_text("⚠️ استخدم الأمر بالرد على العضو أو أرفق Telegram user ID.")
        return True

    target_member = None
    if target_id is not None and action not in {"UNBAN"}:
        try:
            target_member = await context.bot.get_chat_member(chat.id, target_id)
        except Exception:
            await message.reply_text("❌ لم أتمكن من التحقق من العضو في هذه المجموعة؛ لم يُنفذ الإجراء.")
            return True
        target_status = target_member.status
        if target_status in {"creator", "owner", "administrator"} or target_id in {actor.id, context.bot.id}:
            await message.reply_text("❌ هذا العضو محمي ولا يمكن استهدافه بهذا الأمر.")
            return True
        if requested_username:
            resolved_username = getattr(target_member.user, "username", None)
            if not resolved_username or resolved_username.casefold() != requested_username:
                await message.reply_text("❌ تعذر التحقق من أن @username هو العضو نفسه داخل هذه المجموعة.")
                return True

    try:
        if action == "MUTE":
            duration = int(command.parameters.get("duration_seconds", 0))
            kwargs = {"chat_id": chat.id, "user_id": target_id,
                      "permissions": ChatPermissions(can_send_messages=False)}
            if duration:
                from datetime import datetime, timedelta, timezone
                kwargs["until_date"] = datetime.now(timezone.utc) + timedelta(seconds=duration)
            await context.bot.restrict_chat_member(**kwargs)
            result = f"🔇 تم كتم {target_name or target_id}" + (f" لمدة {duration // 60} دقيقة." if duration else ".")
        elif action == "UNMUTE":
            permissions = ChatPermissions(can_send_messages=True, can_send_audios=True,
                can_send_documents=True, can_send_photos=True, can_send_videos=True,
                can_send_other_messages=True)
            await context.bot.restrict_chat_member(chat.id, target_id, permissions=permissions)
            result = f"🔊 تم فك الكتم عن {target_name or target_id}."
        elif action == "KICK":
            await context.bot.ban_chat_member(chat.id, target_id)
            await context.bot.unban_chat_member(chat.id, target_id, only_if_banned=True)
            result = f"👢 تم طرد {target_name or target_id}."
        elif action == "BAN":
            await context.bot.ban_chat_member(chat.id, target_id)
            result = f"🚫 تم حظر {target_name or target_id}."
        elif action == "UNBAN":
            await context.bot.unban_chat_member(chat.id, target_id, only_if_banned=True)
            result = f"♻️ تم فك الحظر عن {target_id}."
        elif action == "WARN":
            count = await add_moderation_warning(chat.id, target_id, "تحذير بأمر مخصص", reply.message_id if reply else None)
            if count >= MODERATION_WARNING_LIMIT:
                await context.bot.restrict_chat_member(chat.id, target_id, permissions=ChatPermissions(can_send_messages=False))
                await reset_moderation_warnings(chat.id, target_id)
                result = f"⚠️ اكتملت التحذيرات وتم كتم {target_name or target_id} تلقائيًا."
            else:
                result = f"⚠️ تم تسجيل التحذير ({count}/{MODERATION_WARNING_LIMIT}) على {target_name or target_id}."
        elif action == "DELETE":
            await reply.delete()
            result = "🗑 تم حذف الرسالة المردود عليها."
        elif action == "PIN":
            await context.bot.pin_chat_message(chat.id, reply.message_id)
            result = "📌 تم تثبيت الرسالة المردود عليها."
        elif action == "UNPIN":
            await context.bot.unpin_chat_message(chat.id, reply.message_id)
            result = "📍 تمت إزالة تثبيت الرسالة."
        elif action == "SEND_MESSAGE":
            body = render_welcome(command.parameters.get("message", ""), name=actor.first_name or "",
                                  username=actor.username, user_id=actor.id, chat_name=chat.title)
            await context.bot.send_message(chat.id, body or "")
            result = None
        else:
            await message.reply_text("❌ هذا الإجراء غير مدعوم.")
            return True
        if result:
            await message.reply_text(result)
    except Exception as exc:
        logger.warning("Custom group action failed (%s): %s", action, type(exc).__name__)
        detail = re.sub(r"\s+", " ", str(exc)).strip()[:240]
        await message.reply_text(f"❌ تعذر تنفيذ الإجراء ({type(exc).__name__}): {detail or 'خطأ غير موصوف من Telegram.'}")
    return True


async def _is_exact_custom_command(chat_id: int, text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    return any(command.normalized_name == normalized
               for command in await group_feature_store.list_commands(chat_id))

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    if user_id and not await is_subscribed(user_id, context):
        await send_sub_prompt(update, context)
        return

    if update.message and update.message.text in ["الاوامر", "/help", "الأوامر"]:
        text, reply_markup = await get_user_role_menu(update, context)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=None)
        return

    if await handle_purge_commands(update, context):
        return
    if await handle_lock_toggle_commands(update, context):
        return
    if await check_media_locks(update, context):
        return

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
            return await update.message.reply_text(f"🎉 **إجابة صحيحة يا [{update.effective_user.first_name}](tg://user?id={uid})!** بطل الألعاب ✨", parse_mode=None)

    # 4. قسم التسلية والترفيه
    if text in ["لارا اختراق", "اختراق"] and reply_msg:
        target_name = reply_msg.from_user.first_name
        hack_msg = await update.message.reply_text(f"💻 **[{update.effective_user.first_name}]** طلب تهيئة بيئة الاختراق...\n\n[▓░░░░░░░░░] 10%", parse_mode=None)
        await asyncio.sleep(1)
        fake_ip = f"192.168.{random.randint(1,255)}.{random.randint(1,255)}"
        await hack_msg.edit_text(f"🔍 جاري البحث عن IP الهدف ({target_name})...\n\n[▓▓▓▓░░░░░░] 40%", parse_mode=None)
        await asyncio.sleep(1.2)
        await hack_msg.edit_text(f"🎯 تم العثور على الهدف!\n🌐 IP: `{fake_ip}`\n🔓 جاري كسر تشفير الحماية...\n\n[▓▓▓▓▓▓▓░░░] 75%", parse_mode=None)
        await asyncio.sleep(1.5)
        return await hack_msg.edit_text(f"✅ **تم الاختراق بنجاح!** 💀\nتم سحب الصور والملفات من جهاز {target_name}!\n\n*(بمزح بمزح، نظام حماية litharm أقوى من هيك بكتير 😂)*", parse_mode=None)

    if text.startswith("لارا نسبة الحب"):
        names = text.replace("لارا نسبة الحب", "").strip()
        if not names:
            return await update.message.reply_text("❤️ اكتبي الاسمين بعد الأمر، مثال:\n`لارا نسبة الحب أحمد ومريم`", parse_mode=None)
        love_percent = random.randint(0, 100)
        emoji = "🔥" if love_percent > 80 else ("💖" if love_percent > 50 else "💔")
        return await update.message.reply_text(f"❤️ **مقياس الحب الدقيق:**\n\nنسبة الحب بين {names} هي: **{love_percent}%** {emoji}", parse_mode=None)

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
            parse_mode=None
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
        return await update.message.reply_text(f"📊 **تفاعلك:**\n🎖️ الرتبة: {rank}\n💬 الرسائل: {xp}", parse_mode=None)

    if text in ["اكس او", "إكس أو", "إكس او", "xo", "XO"]:
        return await cmd_xo(update, context)

    if text in ["حالة النظام", "السيرفر", "النظام"] and uid == ADMIN_ID:
        return await update.message.reply_text(get_system_telemetry(), parse_mode=None)

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
            return await update.message.reply_text("❌ يرجى كتابة اسم الأغنية بعد الأمر، مثال:\n`نزلي أصالة`", parse_mode=None)

        status_msg = await update.message.reply_text("🔎 **جاري البحث وتحميل الأغنية...**", parse_mode=None)
        res = await asyncio.to_thread(_download_yt_audio, query_song)

        if res['success'] and os.path.exists(res['filepath']):
            try:
                await status_msg.edit_text("⬆️ **جاري رفع الملف الصوتي...**", parse_mode=None)
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

        matches_admin_prefix = any(text == cmd or text.startswith(cmd) for cmd in all_admin_triggers)
        custom_command_owns_exact_name = (
            matches_admin_prefix and await _is_exact_custom_command(chat_id, text)
        )
        if matches_admin_prefix and not custom_command_owns_exact_name:
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
                        await update.message.reply_text(f"🚫 تم طرد العضو **{target.first_name}**.", parse_mode=None)
                    elif text in mute_cmds:
                        await context.bot.restrict_chat_member(chat_id, target.id, permissions=ChatPermissions(can_send_messages=False))
                        await update.message.reply_text(f"🔇 تم كتم العضو **{target.first_name}**.", parse_mode=None)
                    elif text in unmute_cmds:
                        perms = ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_other_messages=True)
                        await context.bot.restrict_chat_member(chat_id, target.id, permissions=perms)
                        await update.message.reply_text(f"🔊 تم فك الكتم عن **{target.first_name}**.", parse_mode=None)
                    elif text in warn_cmds:
                        warning_count = await add_moderation_warning(
                            chat_id=chat_id,
                            user_id=target.id,
                            reason="تحذير إداري",
                            message_id=reply_msg.message_id,
                        )
                        if warning_count >= MODERATION_WARNING_LIMIT:
                            await context.bot.restrict_chat_member(
                                chat_id,
                                target.id,
                                permissions=ChatPermissions(can_send_messages=False),
                            )
                            await reset_moderation_warnings(chat_id, target.id)
                            await update.message.reply_text(
                                f"⚠️ وصل العضو **{target.first_name}** لـ {MODERATION_WARNING_LIMIT} تحذيرات! تم كتمه تلقائياً.",
                                parse_mode=None,
                            )
                        else:
                            await update.message.reply_text(
                                f"⚠️ تحذير للعضو **{target.first_name}** (`{warning_count}/{MODERATION_WARNING_LIMIT}`).",
                                parse_mode=None,
                            )
                    elif text in pin_cmds:
                        await context.bot.pin_chat_message(chat_id, reply_msg.message_id)
                        await update.message.reply_text("📌 تم تثبيت الرسالة بنجاح.")
                except Exception:
                    await update.message.reply_text("⚠️ فشل تنفيذ الأمر: تأكد من رفع البوت كأدمن بالمجموعة وإعطائه الصلاحيات الكاملة.")
                return
            else:
                if text in kick_cmds + mute_cmds + unmute_cmds + warn_cmds + pin_cmds:
                    return await update.message.reply_text("⚠️ يرجى استخدام هذا الأمر بالرد على رسالة العضو المطلوب!")

    # 10. طبقة المحادثة المحلية منخفضة الأولوية بعد مسارات الإدارة والميزات.
    # Preserve active cashout and VIP video workflows from generic Lara replies.
    if (context.user_data.get("awaiting_phone")
            or context.user_data.get("waiting_for_video")
            or uid in ACTIVE_AI_USERS):
        return

    if text in {"إعدادات المجموعة", "اعدادات المجموعة", "لوحة مالك المجموعة"} and is_group:
        if await is_group_owner(update, context):
            await show_owner_menu(update.message, chat_id)
        else:
            await update.message.reply_text("❌ إعدادات المجموعة متاحة لمالك المجموعة فقط.")
        return
    if text in {"تغيير رسالة الترحيب", "تغيير الرسالة الترحيبية"} and is_group:
        if await is_group_owner(update, context):
            context.user_data[GROUP_OWNER_FLOW_KEY] = {"chat_id": chat_id, "step": "welcome"}
            await update.message.reply_text("📝 أرسل رسالة الترحيب الجديدة. المتغيرات: {name} {username} {user_id} {chat_name}")
        else:
            await update.message.reply_text("❌ تغيير رسالة الترحيب متاح لمالك المجموعة فقط.")
        return
    if await handle_owner_flow_message(update, context):
        return
    if await _run_group_custom_command(update, context):
        return

    admin_chat_bypass = [
        "لارا طردي", "لارا اطردي", "لارا كتمي", "لارا اكتمي",
        "لارا فك الكتم", "لارا فكي الكتم", "لارا الغاء كتم", "لارا حذري", "لارا تحذير",
        "لارا ثبتي", "لارا تثبيت", "لارا اقفلي",
        "لارا قفل المحادثة", "لارا إغلاق المحادثة",
        "لارا افتحي", "لارا فتح المحادثة", "لارا فتح الجروب",
        "لارا قفل الجروب",
        "لارا نسبة الحب", "لارا اختراق", "لارا نكتة", "لارا نكت", "لارا قصف",
        "اختراق", "نسبة الحب", "نكتة", "نكت", "قصف", "اقصفي",
        "طرد", "اطردي", "كتم", "اكتمي", "فك الكتم",
        "الغاء كتم", "حذري", "تحذير", "ثبتي", "تثبيت",
        "اقفلي", "قفل المحادثة", "إغلاق المحادثة",
        "افتحي", "فتح المحادثة", "فتح الجروب", "قفل الجروب",
    ]
    is_legacy_admin_text = any(text == cmd or text.startswith(cmd + " ") for cmd in admin_chat_bypass)
    from arsyra.conversation import is_existing_feature_command, strip_invocation
    is_legacy_admin_text = is_legacy_admin_text or is_existing_feature_command(strip_invocation(text))
    if not is_legacy_admin_text:
        from arsyra.conversation import (
            ConversationIntent, InvocationLevel, calculate_local_request, classify_intent,
            conversation_context, detect_invocation,
            is_telegram_command, natural_fallback, strip_invocation,
        )

        replied = update.message.reply_to_message
        replied_user_id = (replied.from_user.id if replied and replied.from_user else None)
        replied_message_id = replied.message_id if replied else None
        reply_to_lara = conversation_context.reply_targets_lara(
            chat_id=chat_id,
            user_id=uid,
            replied_message_id=replied_message_id,
            replied_user_id=replied_user_id,
            bot_user_id=getattr(context.bot, "id", None),
        )
        reply_to_other = bool(replied and not reply_to_lara)

        if not is_telegram_command(text) and not is_existing_feature_command(text):
            decision = conversation_context.decide(
                chat_id=chat_id,
                user_id=uid,
                text=text,
                reply_to_bot=reply_to_lara,
                reply_to_other=reply_to_other,
            )
            if decision.level == InvocationLevel.DIRECT_INVOCATION:
                query_ai = strip_invocation(text) if detect_invocation(text) else text.strip()
                normalized_query = query_ai.lower().replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                response_text = None
                if "من انت" in normalized_query:
                    response_text = "أنا لارا، مساعدتك الذكية والمطورة بواسطة المبدع litharm! 🌸"
                elif "كيفك" in normalized_query or "كيف حالك" in normalized_query:
                    response_text = random.choice([
                        "بأفضل حال والحمد لله! كيف أساعدك اليوم؟ ✨",
                        "منيحة الحمدلله 😄 وإنت كيفك؟",
                        "تمام، مبسوطة إني عم بحكي معك 🌷",
                    ])
                elif "من طورك" in normalized_query:
                    response_text = "تم برمجتي بواسطة المطور الأسطوري litharm 🚀"

                if response_text is None and normalized_query in ("نكتة", "نكت"):
                    response_text = f"😂 {random.choice(JOKES)}"

                context_query = conversation_context.contextual_query(
                    chat_id=chat_id, user_id=uid, text=query_ai,
                    continued=decision.continued,
                )
                details = conversation_context.conversation_details(chat_id, uid)
                intent = classify_intent(
                    query_ai,
                    continued=decision.continued,
                    previous_intent=details.get("previous_intent"),
                    pending_question=details.get("pending_question"),
                )
                if intent == ConversationIntent.CALCULATION:
                    result = calculate_local_request(query_ai)
                    if result is not None:
                        response_text = f"الناتج: {result}"
                if response_text is None:
                    # ArSyra's existing exact replies and dialogue corpus stay first in the chain.
                    from arsyra.engine import ask as arsyra_ask
                    arsyra_reply = arsyra_ask(context_query)
                    if arsyra_reply:
                        response_text = f"🤖 **لارا:** {arsyra_reply}"
                if response_text is None:
                    response_text = natural_fallback(
                        query_ai, intent,
                        topic=details.get("previous_topic", "") if decision.continued else "",
                    )
                    response_text = f"🤖 **لارا:** {response_text}"

                sent = await update.message.reply_text(response_text, parse_mode=None)
                conversation_context.record_reply(
                    chat_id=chat_id,
                    user_id=uid,
                    user_text=text,
                    bot_message_id=getattr(sent, "message_id", None),
                    bot_text=response_text,
                    continued=decision.continued,
                    intent=intent,
                )
                return sent


# ====================================================
# --- التشغيل والنواة الأساسية ---
# ====================================================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in the runtime environment before starting Lara.")
    asyncio.run(init_db())
    application_builder = (Application.builder().token(BOT_TOKEN)
                           .post_init(video_editor_post_init)
                           .post_shutdown(video_editor_post_shutdown))
    telegram_api_base = os.getenv("TELEGRAM_API_BASE_URL")
    telegram_file_base = os.getenv("TELEGRAM_FILE_BASE_URL")
    if telegram_api_base:
        application_builder = application_builder.base_url(telegram_api_base)
    if telegram_file_base:
        application_builder = application_builder.base_file_url(telegram_file_base)
    app = application_builder.build()

    # Start the optional Render keep-alive infrastructure only during runtime,
    # never as a side effect of importing this module for tests or tooling.
    threading.Thread(target=run_dummy_server, daemon=True).start()
    threading.Thread(target=keep_alive_ping, daemon=True).start()

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

    app.add_handler(CallbackQueryHandler(handle_ref_status, pattern="^my_ref_status$"))
    app.add_handler(CallbackQueryHandler(handle_daily_claim, pattern="^claim_daily$"))
    app.add_handler(CallbackQueryHandler(handle_start_cashout, pattern="^start_cashout$"))
    app.add_handler(CallbackQueryHandler(handle_cashout_type, pattern="^cashout_type_"))
    app.add_handler(CallbackQueryHandler(handle_confirm_cashout, pattern="^confirm_cashout_final$"))
    app.add_handler(CallbackQueryHandler(private_start_menu, pattern="^back_private_main$"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), process_phone_input), group=1)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("calc", cmd_calc))
    app.add_handler(CommandHandler("xo", cmd_xo))

    app.add_handler(reply_conv)
    app.add_handler(MessageHandler(EDITOR_MEDIA_FILTER, handle_editor_media), group=-1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_editor_text), group=-1)
        # معالج محادثة تعديل الفيديو الآمن
    video_edit_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(video_edit_init, pattern="^btn_video_edit$")],
        states={
            WAIT_VIDEO: [MessageHandler(filters.VIDEO, video_receive_file)],
            WAIT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, video_process_and_reply)],
        },
        fallbacks=[CommandHandler("cancel", cancel_video_edit), MessageHandler(filters.COMMAND, cancel_video_edit)],
    )
    app.add_handler(video_edit_conv)
    app.add_handler(sug_conv)
    app.add_handler(broadcast_conv)

    app.add_handler(MessageHandler(filters.VIDEO, handle_incoming_video))
    # تم إزالة المعالج العشوائي لتجنب التعارض:
    # app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_video_prompt))
    # تم إزالة المعالج العشوائي لتجنب التعارض:
    # app.add_handler(MessageHandler(AILimitFilter() & ~filters.COMMAND, handle_ai_video_prompt))
    app.add_handler(CallbackQueryHandler(video_editor_callback, pattern=r"^video_editor:"))
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(CallbackQueryHandler(cmd_referral, pattern='^cmd_referral$'))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

    print("[+] Bot Lara V5.9 Legendary (litharm Edition) Started Successfully!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
