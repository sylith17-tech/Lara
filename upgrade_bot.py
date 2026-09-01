import re
import os

token = ""
admin_id = 123456789

if os.path.exists("main.py"):
    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()
        t_match = re.search(r'BOT_TOKEN\s*=\s*["\']([^"\']+)["\']', content)
        a_match = re.search(r'ADMIN_ID\s*=\s*(\d+)', content)
        if t_match and t_match.group(1) != "ضع_التوكن_هنا":
            token = t_match.group(1)
        if a_match:
            admin_id = int(a_match.group(1))

if not token or token == "ضع_التوكن_هنا":
    token = input("أدخل BOT_TOKEN الخاص بك: ").strip()

# ----------------- database.py -----------------
db_code = '''import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, BigInteger, Text, Boolean, Integer, DateTime, func

DATABASE_URL = "sqlite+aiosqlite:///lara.db"
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    stars_donated: Mapped[int] = mapped_column(Integer, default=0)

class AutoReply(Base):
    __tablename__ = 'auto_replies'
    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    response: Mapped[str] = mapped_column(Text)

class Suggestion(Base):
    __tablename__ = 'suggestions'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text)

class Note(Base):
    __tablename__ = 'user_notes'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
'''

with open("database.py", "w", encoding="utf-8") as f:
    f.write(db_code)

# ----------------- main.py -----------------
main_code = f'''import logging
import asyncio
import datetime
import os
import glob
import urllib.parse
import httpx
import yt_dlp
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions,
    LabeledPrice, PreCheckoutQuery
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, ContextTypes, filters, ConversationHandler
)
from database import init_db, async_session, User, AutoReply, Suggestion, Note
from sqlalchemy import select, func, delete, update

BOT_TOKEN = "{token}"
ADMIN_ID = {admin_id}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

WAIT_TRIGGER, WAIT_RESPONSE, WAIT_SUGGESTION, WAIT_BROADCAST, WAIT_NOTE_TITLE, WAIT_NOTE_CONTENT, WAIT_BAN_ID = range(7)

def download_audio_yt(query_str):
    ydl_opts = {{
        'format': 'bestaudio/best',
        'outtmpl': 'song_%(id)s.%(ext)s',
        'postprocessors': [{{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }}],
        'default_search': 'ytsearch1:',
        'quiet': True,
        'noplaylist': True
    }}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query_str, download=True)
        if 'entries' in info and info['entries']:
            info = info['entries'][0]
        filename = f"song_{{info['id']}}.mp3"
        return filename, info.get('title', 'صوتية جديدة')

async def query_ai(prompt_text: str) -> str:
    try:
        encoded_prompt = urllib.parse.quote(prompt_text)
        url = f"https://text.pollinations.ai/{{encoded_prompt}}"
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.text.strip():
                return resp.text.strip()
    except Exception:
        pass
    return "💡 أهلاً بك! أنا لارا، كيف يمكنني مساعدتك اليوم؟"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_obj = await context.bot.get_me()
    
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user.id))
        u = res.scalar_one_or_none()
        if not u:
            session.add(User(telegram_id=user.id, username=user.username, first_name=user.first_name, is_admin=(user.id == ADMIN_ID)))
            await session.commit()
        elif u.is_banned:
            await update.message.reply_text("❌ تم حظرك من استخدام خدمات البوت.")
            return

    keyboard = [
        [InlineKeyboardButton("➕ إضافة البوت لمجموعتك", url=f"https://t.me/{{bot_obj.username}}?startgroup=true")],
        [InlineKeyboardButton("📜 الأوامر العامة والذكاء", callback_data="cmd_user"), InlineKeyboardButton("👮‍♂️ إدارة المجموعات", callback_data="cmd_group")],
        [InlineKeyboardButton("🎮 الألعاب والتسلية", callback_data="cmd_games"), InlineKeyboardButton("🛠 الأدوات والملاحظات", callback_data="cmd_tools")],
        [InlineKeyboardButton("💡 اقتراح ميزة", callback_data="btn_suggest"), InlineKeyboardButton("⭐ دعم البوت بالنجوم", callback_data="btn_donate")]
    ]
    
    if user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم المطور الذكية", callback_data="admin_main")])

    await update.message.reply_text(
        f"🤖 **أهلاً بك يا {{user.first_name}} في نظام لارا الذكي v7.0!**\\n\\n💡 البوت مجهز بالذكاء الاصطناعي، الحماية، تحميل الصوتيات، والدعم بالنجوم.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id

    if data == "cmd_user":
        msg = ("📌 **الأوامر العامة المتاحة:**\\n"
               "• `/ai [سؤالك]` - سؤال الذكاء الاصطناعي مياشرة\\n"
               "• `لارا ابحثي عن اغنية [الاسم]` - تحميل الصوتيات\\n"
               "• `/id` - عرض المعرفات والحساب\\n"
               "• `/ping` - قياس الاستجابة الحية\\n"
               "• `/mynotes` - عرض ملاحظاتك")
        await query.message.reply_text(msg, parse_mode="Markdown")
    elif data == "cmd_group":
        msg = ("👮‍♂️ **أوامر الإدارة والحماية في المجموعات:**\\n"
               "• `/kick` - طرد عضو (بالرد)\\n"
               "• `/ban` - حظر عضو من المجموعة (بالرد)\\n"
               "• `/unban` - فك حظر عضو (بالرد)\\n"
               "• `/mute` - كتم العضو (بالرد)\\n"
               "• `/unmute` - فك كتم العضو (بالرد)\\n"
               "• `/pin` - تثبيت الرسالة (بالرد)\\n"
               "• `/unpin` - إلغاء تثبيت الرسالة (بالرد)\\n"
               "• `/info` - عرض تفاصيل ومعلومات المجموعة")
        await query.message.reply_text(msg, parse_mode="Markdown")
    elif data == "cmd_games":
        keyboard = [
            [InlineKeyboardButton("🎲 حجر النرد", callback_data="game_dice"), InlineKeyboardButton("🎯 التصويب", callback_data="game_dart")],
            [InlineKeyboardButton("🎰 ماكينة الحظ", callback_data="game_slots"), InlineKeyboardButton("⚽ كرة القدم", callback_data="game_ball")]
        ]
        await query.message.reply_text("🎮 **الألعاب التفاعلية المباشرة:**", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data in ["game_dice", "game_dart", "game_slots", "game_ball"]:
        emoji_map = {{"game_dice": "🎲", "game_dart": "🎯", "game_slots": "🎰", "game_ball": "⚽"}}
        await context.bot.send_dice(chat_id=query.message.chat_id, emoji=emoji_map[data])
    elif data == "cmd_tools":
        keyboard = [[InlineKeyboardButton("📝 إضافة ملاحظة جديدة", callback_data="btn_add_note")]]
        msg = "🛠 **الملاحظات والحافظة الشخصية:**\\nسجل بياناتك وملاحظاتك بأمان واسترجعها بأي وقت."
        await query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "btn_donate":
        keyboard = [
            [InlineKeyboardButton("⭐ 10 نجوم", callback_data="buy_stars_10"), InlineKeyboardButton("⭐ 50 نجمة", callback_data="buy_stars_50")],
            [InlineKeyboardButton("⭐ 100 نجمة", callback_data="buy_stars_100"), InlineKeyboardButton("⭐ 500 نجمة", callback_data="buy_stars_500")]
        ]
        await query.message.reply_text("💖 **دعم البوت بواسطة نجوم تليجرام (Telegram Stars):**\\nاختر الفئة التي تود المساهمة بها لدعم وتطوير الخوادم:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data.startswith("buy_stars_"):
        amount = int(data.split("_")[-1])
        title = f"دعم البوت بـ {{amount}} نجمة"
        description = f"مساهمة لتطوير خوادم لارا ودعم استمرار الخدمات."
        payload = f"stars_donate_{{uid}}_{{amount}}"
        prices = [LabeledPrice(label=f"{{amount}} ⭐", amount=amount)]
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=prices
        )
    elif data == "admin_main" and uid == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("📢 إذاعة عامة", callback_data="adm_broadcast"), InlineKeyboardButton("➕ إضافة رد", callback_data="adm_add_reply")],
            [InlineKeyboardButton("📋 الردود", callback_data="adm_list_replies"), InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats")],
            [InlineKeyboardButton("🚫 حظر/فك حظر مستخدم", callback_data="adm_ban_user"), InlineKeyboardButton("💡 المقترحات", callback_data="adm_view_sug")]
        ]
        await query.message.reply_text("⚙️ **لوحة التحكم المتقدمة:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "adm_stats" and uid == ADMIN_ID:
        async with async_session() as session:
            u_cnt = (await session.execute(select(func.count(User.id)))).scalar()
            r_cnt = (await session.execute(select(func.count(AutoReply.id)))).scalar()
            s_cnt = (await session.execute(select(func.count(Suggestion.id)))).scalar()
            n_cnt = (await session.execute(select(func.count(Note.id)))).scalar()
            s_sum = (await session.execute(select(func.sum(User.stars_donated)))).scalar() or 0
            msg = f"📊 **تقارير النظام:**\\n\\n👥 المستعملين: {{u_cnt}}\\n💬 الردود الآلية: {{r_cnt}}\\n💡 الاقتراحات: {{s_cnt}}\\n📝 الملاحظات: {{n_cnt}}\\n⭐ إجمالي النجوم المتبرع بها: {{s_sum}}"
            await query.message.reply_text(msg, parse_mode="Markdown")
    elif data == "adm_list_replies" and uid == ADMIN_ID:
        async with async_session() as session:
            replies = (await session.execute(select(AutoReply))).scalars().all()
            if not replies:
                await query.message.reply_text("لا توجد ردود حالياً.")
            else:
                lines = [f"• `{{rep.trigger}}` ➔ {{rep.response}}" for rep in replies]
                txt = "📋 **سجل الردود التلقائية:**\\n" + "\\n".join(lines)
                await query.message.reply_text(txt, parse_mode="Markdown")
    elif data == "adm_view_sug" and uid == ADMIN_ID:
        async with async_session() as session:
            sugs = (await session.execute(select(Suggestion))).scalars().all()
            if not sugs:
                await query.message.reply_text("لا توجد مقترحات.")
            else:
                lines = [f"• User ID: `{{s.user_id}}` | {{s.text}}" for s in sugs]
                txt = "💡 **المقترحات:**\\n" + "\\n".join(lines)
                await query.message.reply_text(txt, parse_mode="Markdown")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    user = update.effective_user
    stars = sp.total_amount
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == user.id))
        u = res.scalar_one_or_none()
        if u:
            u.stars_donated += stars
            await session.commit()
    await update.message.reply_text(f"🌟 **شكراً جزيلاً لك يا {{user.first_name}}!**\\nتم استلام دعمك بقيمة **{{stars}} نجمة** بنجاح. مساهمتك تساعدنا على التطوير المباشر! ❤️", parse_mode="Markdown")

async def broadcast_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END
    await query.message.reply_text("📢 أدخل الرسالة المراد إذاعتها:")
    return WAIT_BROADCAST

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = update.message.text
    async with async_session() as session:
        users = (await session.execute(select(User.telegram_id))).scalars().all()
    count = 0
    for u_id in users:
        try:
            await context.bot.send_message(chat_id=u_id, text=f"📢 **إشعار من المطور:**\\n\\n{{msg_text}}", parse_mode="Markdown")
            count += 1
            await asyncio.sleep(0.04)
        except Exception:
            continue
    await update.message.reply_text(f"✅ تم الإرسال لـ {{count}} مستخدم بنجاح.")
    return ConversationHandler.END

async def ban_user_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END
    await query.message.reply_text("أدخل ID المستخدم للتبديل بين (حظر / فك حظر):")
    return WAIT_BAN_ID

async def ban_user_exec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target_id = int(update.message.text.strip())
        async with async_session() as session:
            res = await session.execute(select(User).where(User.telegram_id == target_id))
            u = res.scalar_one_or_none()
            if u:
                u.is_banned = not u.is_banned
                await session.commit()
                status = "حظره 🚫" if u.is_banned else "فك حظره ✅"
                await update.message.reply_text(f"تم {{status}} بنجاح للمستخدم `{{target_id}}`", parse_mode="Markdown")
            else:
                await update.message.reply_text("المستخدم غير موجود بقاعدة البيانات.")
    except Exception as e:
        await update.message.reply_text(f"خطأ: {{e}}")
    return ConversationHandler.END

async def add_reply_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END
    await query.message.reply_text("أدخل الكلمة المفتاحية:")
    return WAIT_TRIGGER

async def add_reply_trig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['trig'] = update.message.text.strip()
    await update.message.reply_text("أدخل نص الرد:")
    return WAIT_RESPONSE

async def add_reply_resp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trig = context.user_data['trig']
    resp = update.message.text.strip()
    async with async_session() as session:
        session.add(AutoReply(trigger=trig, response=resp))
        await session.commit()
    await update.message.reply_text("✅ تم إضافة الرد التلقائي بنجاح!")
    return ConversationHandler.END

async def suggest_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("اكتب الاقتراح بالتفصيل:")
    return WAIT_SUGGESTION

async def suggest_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    uid = update.effective_user.id
    async with async_session() as session:
        session.add(Suggestion(user_id=uid, text=txt))
        await session.commit()
    await update.message.reply_text("✅ تم استلام مقترحك، شكراً لك!")
    return ConversationHandler.END

async def add_note_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("أدخل عنوان الملاحظة:")
    return WAIT_NOTE_TITLE

async def add_note_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['note_title'] = update.message.text.strip()
    await update.message.reply_text("أدخل تفاصيل الملاحظة:")
    return WAIT_NOTE_CONTENT

async def add_note_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = context.user_data['note_title']
    content = update.message.text.strip()
    uid = update.effective_user.id
    async with async_session() as session:
        session.add(Note(user_id=uid, title=title, content=content))
        await session.commit()
    await update.message.reply_text(f"✅ تم حفظ الملاحظة `{{title}}`", parse_mode="Markdown")
    return ConversationHandler.END

async def get_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    async with async_session() as session:
        notes = (await session.execute(select(Note).where(Note.user_id == uid))).scalars().all()
        if not notes:
            await update.message.reply_text("ليس لديك ملاحظات محفوظة.")
        else:
            lines = [f"📌 **{{n.title}}**: {{n.content}}" for n in notes]
            txt = "📝 **ملاحظاتك:**\\n" + "\\n".join(lines)
            await update.message.reply_text(txt, parse_mode="Markdown")

async def cmd_kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("يرجى الرد على رسالة العضو المراد طرده.")
        return
    user_to_kick = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user_to_kick.id)
        await context.bot.unban_chat_member(update.effective_chat.id, user_to_kick.id)
        await update.message.reply_text(f"🚫 تم طرد العضو {{user_to_kick.first_name}} بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"فشل إجراء الطرد: {{e}}")

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("يرجى الرد على رسالة العضو المراد حظره.")
        return
    user_to_ban = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user_to_ban.id)
        await update.message.reply_text(f"🛑 تم حظر العضو {{user_to_ban.first_name}} نهائياً من المجموعة.")
    except Exception as e:
        await update.message.reply_text(f"فشل الحظر: {{e}}")

async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("يرجى الرد على رسالة العضو المراد فك حظره.")
        return
    user_to_unban = update.message.reply_to_message.from_user
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, user_to_unban.id, only_if_banned=True)
        await update.message.reply_text(f"✅ تم فك الحظر عن العضو {{user_to_unban.first_name}}.")
    except Exception as e:
        await update.message.reply_text(f"فشل فك الحظر: {{e}}")

async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("يرجى الرد على رسالة العضو المراد كتمه.")
        return
    user_to_mute = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, 
            user_to_mute.id, 
            permissions=ChatPermissions(can_send_messages=False)
        )
        await update.message.reply_text(f"🤐 تم كتم العضو {{user_to_mute.first_name}}.")
    except Exception as e:
        await update.message.reply_text(f"فشل الكتم: {{e}}")

async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("يرجى الرد على رسالة العضو المراد إلغاء كتمه.")
        return
    user_to_unmute = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, 
            user_to_unmute.id, 
            permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
        )
        await update.message.reply_text(f"🔊 تم إلغاء الكتم عن {{user_to_unmute.first_name}}.")
    except Exception as e:
        await update.message.reply_text(f"فشل إلغاء الكتم: {{e}}")

async def cmd_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("يرجى الرد على الرسالة المراد تثبيتها.")
        return
    try:
        await context.bot.pin_chat_message(update.effective_chat.id, update.message.reply_to_message.message_id)
        await update.message.reply_text("📌 تم تثبيت الرسالة بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"فشل التثبيت: {{e}}")

async def cmd_unpin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.unpin_chat_message(update.effective_chat.id)
        await update.message.reply_text("📌 تم إلغاء تثبيت الرسالة الأخيرة.")
    except Exception as e:
        await update.message.reply_text(f"فشل إلغاء التثبيت: {{e}}")

async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    members_count = await chat.get_member_count()
    info_text = (
        f"ℹ️ **معلومات المحادثة/المجموعة:**\\n\\n"
        f"• **العنوان:** {{chat.title or chat.first_name}}\\n"
        f"• **المعرف (ID):** `{{chat.id}}`\\n"
        f"• **النوع:** {{chat.type}}\\n"
        f"• **عدد الأعضاء:** {{members_count}}"
    )
    await update.message.reply_text(info_text, parse_mode="Markdown")

async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("يرجى كتابة السؤال بعد الأمر، مثال:\\n`/ai ما هي مجرة درب التبانة؟`", parse_mode="Markdown")
        return
    status = await update.message.reply_text("🧠 **جاري تفكير الذكاء الاصطناعي...**", parse_mode="Markdown")
    reply = await query_ai(prompt)
    await status.edit_text(f"🤖 **إجابة لارا:**\\n\\n{{reply}}", parse_mode="Markdown")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    uid = update.effective_user.id
    
    async with async_session() as session:
        res = await session.execute(select(User).where(User.telegram_id == uid))
        u = res.scalar_one_or_none()
        if u and u.is_banned: return

    if text.startswith("لارا ابحثي عن اغنية"):
        song_name = text.replace("لارا ابحثي عن اغنية", "").strip()
        status_msg = await update.message.reply_text(f"⏳ **جاري البحث والتحميل للصوتية:** `{song_name}`...", parse_mode="Markdown")
        try:
            loop = asyncio.get_running_loop()
            file_path, title = await loop.run_in_executor(None, download_audio_yt, song_name)
            await status_msg.edit_text("⚡ **جاري رفعه لك كملف صوتي...**")
            with open(file_path, 'rb') as audio:
                await update.message.reply_audio(audio=audio, title=title, caption=f"🎵 {{title}}\\n🤖 تم التحميل بواسطة لارا")
            await status_msg.delete()
            if os.path.exists(file_path): os.remove(file_path)
            return
        except Exception as e:
            await status_msg.edit_text(f"❌ تعذر تحميل الأغنية: {{e}}")
            return

    async with async_session() as session:
        res = await session.execute(select(AutoReply).where(AutoReply.trigger == text))
        reply = res.scalar_one_or_none()
        if reply:
            await update.message.reply_text(reply.response)
            return

    if update.effective_chat.type == "private" and not text.startswith("/"):
        status = await update.message.reply_text("🧠 **جاري التفكير...**")
        ai_res = await query_ai(text)
        await status.edit_text(ai_res)

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    c = update.effective_chat
    await update.message.reply_text(f"🆔 **معلومات الحساب:**\\n\\nالاسم: {{u.first_name}}\\nالمعرف: `@{{u.username}}`\\nID الحساب: `{{u.id}}`\\nID Chat: `{{c.id}}`", parse_mode="Markdown")

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = datetime.datetime.now()
    msg = await update.message.reply_text("⚡ جاري القياس...")
    ms = (datetime.datetime.now() - start_time).total_seconds() * 1000
    await msg.edit_text(f"⚡ **استجابة البوت والسيرفر:** `{{ms:.2f}}ms`", parse_mode="Markdown")

def main():
    asyncio.run(init_db())
    app = Application.builder().token(BOT_TOKEN).build()

    bcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_init, pattern="^adm_broadcast$")],
        states={{WAIT_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)]}},
        fallbacks=[], per_message=True
    )

    ban_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ban_user_init, pattern="^adm_ban_user$")],
        states={{WAIT_BAN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ban_user_exec)]}},
        fallbacks=[], per_message=True
    )

    reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_reply_init, pattern="^adm_add_reply$")],
        states={{
            WAIT_TRIGGER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reply_trig)],
            WAIT_RESPONSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reply_resp)]
        }},
        fallbacks=[], per_message=True
    )

    sug_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(suggest_init, pattern="^btn_suggest$")],
        states={{WAIT_SUGGESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggest_save)]}},
        fallbacks=[], per_message=True
    )

    note_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_note_init, pattern="^btn_add_note$")],
        states={{
            WAIT_NOTE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_note_title)],
            WAIT_NOTE_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_note_save)]
        }},
        fallbacks=[], per_message=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("ai", cmd_ai))
    app.add_handler(CommandHandler("mynotes", get_notes))
    
    app.add_handler(CommandHandler("kick", cmd_kick))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("unban", cmd_unban))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("unmute", cmd_unmute))
    app.add_handler(CommandHandler("pin", cmd_pin))
    app.add_handler(CommandHandler("unpin", cmd_unpin))
    app.add_handler(CommandHandler("info", cmd_info))

    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    app.add_handler(bcast_conv)
    app.add_handler(ban_conv)
    app.add_handler(reply_conv)
    app.add_handler(sug_conv)
    app.add_handler(note_conv)
    
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

    print("[+] Intelligent Bot Engine Started successfully!")
    app.run_polling()

if __name__ == "__main__":
    main()
'''

with open("main.py", "w", encoding="utf-8") as f:
    f.write(main_code)

print("[+] Code base fixed and updated successfully.")
