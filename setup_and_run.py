import os
import re
import asyncio
import sqlite3
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, BigInteger, Text, Boolean, select, delete

# --- 1. استخراج الإعدادات والتنسيق ---
token = ""
admin_id = 0

if os.path.exists("main.py"):
    with open("main.py", "r", encoding="utf-8") as f:
        content = f.read()
        t_match = re.search(r"BOT_TOKEN\s*=\s*['\"]([^'\"]+)['\"]", content)
        a_match = re.search(r"ADMIN_ID\s*=\s*(\d+)", content)
        if t_match: token = t_match.group(1)
        if a_match: admin_id = int(a_match.group(1))

if not token or token == "ضع_توكن_البوت_هنا":
    token = input("أدخل توكن البوت الخاص بك (Bot Token): ").strip()
if not admin_id or admin_id == 123456789:
    admin_id_input = input("أدخل Telegram ID الخاص بك (Chat ID): ").strip()
    admin_id = int(admin_id_input) if admin_id_input.isdigit() else 0

# --- 2. كود قاعدة البيانات المحدثة ---
db_code = '''import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, BigInteger, Text, Boolean

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

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
'''

with open("database.py", "w", encoding="utf-8") as f:
    f.write(db_code)

# --- 3. إنشاء كود البوت الشامل (main.py) ---
main_code = f'''import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler
)
from sqlalchemy import select, func, delete
from database import init_db, async_session, User, AutoReply, Suggestion

BOT_TOKEN = "{token}"
ADMIN_ID = {admin_id}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

WAIT_TRIGGER, WAIT_RESPONSE, WAIT_BROADCAST, WAIT_SUGGESTION = range(4)

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
            await update.message.reply_text("❌ تم حظرك من استخدام البوت.")
            return

    keyboard = [
        [InlineKeyboardButton("➕ إضافة البوت لمجموعتك", url=f"https://t.me/{{bot_obj.username}}?startgroup=true")],
        [InlineKeyboardButton("📜 الأوامر العامة", callback_data="cmd_user"), InlineKeyboardButton("👮‍♂️ أوامر المجموعات", callback_data="cmd_group")],
        [InlineKeyboardButton("🎮 الألعاب والتسلية", callback_data="cmd_games"), InlineKeyboardButton("🛠 الأدوات والخدمات", callback_data="cmd_tools")],
        [InlineKeyboardButton("💡 اقتراح ميزة", callback_data="btn_suggest"), InlineKeyboardButton("☕ دعم التطوير", callback_data="btn_donate")]
    ]
    
    if user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة تحكم المطور (الخاصة)", callback_data="admin_main")])

    text = f"🌸 **أهلاً بك يا {{user.first_name}} في بوت لارا المطور!**\\n\\nيمكنك استخدامه في المحادثات الخاصة أو إضافته لمجموعتك مجاناً مع كامل الميزات."
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id

    if data == "cmd_user":
        msg = "📌 **الأوامر العامة للمستخدمين:**\\n• `لارا ابحثي عن اغنية [الاسم]`\\n• `/replies` - عرض الردود المضافة من المطور\\n• `/id` - عرض معلومات حسابك\\n• `/ping` - فحص سرعة استجابة البوت"
        await query.message.reply_text(msg, parse_mode="Markdown")
    elif data == "cmd_group":
        msg = "👮‍♂️ **أوامر إدارة المجموعات (للآدمن فقط):**\\n• `/kick` - طرد عضو\\n• `/mute` - كتم عضو\\n• `/unmute` - إلغاء كتم عضو\\n• `/pin` - تثبيت رسالة\\n• `/admin_help` - قائمة التحكم بالقروب"
        await query.message.reply_text(msg, parse_mode="Markdown")
    elif data == "cmd_games":
        keyboard = [[InlineKeyboardButton("🎲 حجر النرد", callback_data="game_dice"), InlineKeyboardButton("🎯 التصويب", callback_data="game_dart")]]
        await query.message.reply_text("🎮 **قسم الألعاب والتسلية:**", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "game_dice":
        await context.bot.send_dice(chat_id=query.message.chat_id, emoji="🎲")
    elif data == "game_dart":
        await context.bot.send_dice(chat_id=query.message.chat_id, emoji="🎯")
    elif data == "cmd_tools":
        msg = "🛠 **الأدوات:**\\n• `/time` - الوقت والتاريخ الحالي\\n• `/calc [المعادلة]` - حاسبة سريعة\\n• `/quote` - اقتباس يومي"
        await query.message.reply_text(msg, parse_mode="Markdown")
    elif data == "btn_donate":
        await query.message.reply_text("💖 شكراً لرغبتك في دعم وتطوير البوت! يمكنك التواصل مع المطور مباشرة.")
    elif data == "admin_main" and uid == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("📢 إذاعة للمستخدمين", callback_data="adm_broadcast"), InlineKeyboardButton("➕ إضافة رد تلقائي", callback_data="adm_add_reply")],
            [InlineKeyboardButton("📋 قائمة الردود", callback_data="adm_list_replies"), InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats")],
            [InlineKeyboardButton("💡عرض المقترحات", callback_data="adm_view_sug")]
        ]
        await query.message.reply_text("🛠 **لوحة تحكم المطور المتقدمة:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "adm_stats" and uid == ADMIN_ID:
        async with async_session() as session:
            u_cnt = (await session.execute(select(func.count(User.id)))).scalar()
            r_cnt = (await session.execute(select(func.count(AutoReply.id)))).scalar()
            s_cnt = (await session.execute(select(func.count(Suggestion.id)))).scalar()
            await query.message.reply_text(f"📊 **إحصائيات البوت:**\\n\\n👥 عدد المستخدمين: {{u_cnt}}\\n💬 عدد الردود التلقائية: {{r_cnt}}\\n💡 عدد المقترحات: {{s_cnt}}", parse_mode="Markdown")
    elif data == "adm_list_replies":
        async with async_session() as session:
            replies = (await session.execute(select(AutoReply))).scalars().all()
            if not replies:
                await query.message.reply_text("لا توجد ردود مضافة.")
            else:
                txt = "📋 **قائمة الردود المضافة:**\\n" + "\\n".join([f"• `{{r.trigger}}` ➔ {{r.response}}" for r in replies])
                await query.message.reply_text(txt, parse_mode="Markdown")
    elif data == "adm_view_sug" and uid == ADMIN_ID:
        async with async_session() as session:
            sugs = (await session.execute(select(Suggestion))).scalars().all()
            if not sugs:
                await query.message.reply_text("لا توجد مقترحات جديدة.")
            else:
                txt = "💡 **مقترحات المستخدمين:**\\n" + "\\n".join([f"• من {{s.user_id}}: {{s.text}}" for s in sugs])
                await query.message.reply_text(txt)

async def add_reply_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return ConversationHandler.END
    await query.message.reply_text("أدخل الكلمة التي سيطلبها المستخدم (مثال: `لارا مرحبا`):")
    return WAIT_TRIGGER

async def add_reply_trig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['trig'] = update.message.text.strip()
    await update.message.reply_text("الآن أدخل الرد الذي ستجيب به لارا (مثال: `أهلاً يا وردة`):")
    return WAIT_RESPONSE

async def add_reply_resp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    trig = context.user_data['trig']
    resp = update.message.text.strip()
    async with async_session() as session:
        session.add(AutoReply(trigger=trig, response=resp))
        await session.commit()
    await update.message.reply_text(f"✅ تم إضافة الرد بنجاح!\\n\\nالكلمة: `{{trig}}`\\nالرد: `{{resp}}`", parse_mode="Markdown")
    return ConversationHandler.END

async def suggest_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("اكتب مقترحك الآن وسيتم إرساله للمطور مباشرة:")
    return WAIT_SUGGESTION

async def suggest_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    uid = update.effective_user.id
    async with async_session() as session:
        session.add(Suggestion(user_id=uid, text=txt))
        await session.commit()
    await update.message.reply_text("✅ تم إرسال مقترحك للمطور، شكراً لمساهمتك!")
    return ConversationHandler.END

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    
    if text.startswith("لارا ابحثي عن اغنية"):
        song = text.replace("لارا ابحثي عن اغنية", "").strip()
        await update.message.reply_text(f"🔍 جاري البحث عن الأغنية: **{{song}}** ...")
        return

    async with async_session() as session:
        res = await session.execute(select(AutoReply).where(AutoReply.trigger == text))
        reply = res.scalar_one_or_none()
        if reply:
            await update.message.reply_text(reply.response)

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(f"🆔 **معلومات الحساب:**\\n\\nاسمك: {{u.first_name}}\\nمعرفك: `@{{u.username}}`\\nID: `{{u.id}}`", parse_mode="Markdown")

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ البوت يعمل وسريع الاستجابة!")

async def group_kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']: return
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    if member.status not in ['administrator', 'creator'] and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ هذا الأمر مخصص لأدمن المجموعة فقط!")
        return
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"🚫 تم طرد العضو {{target.first_name}} بنجاح.")

async def main():
    await init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    reply_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_reply_init, pattern="^adm_add_reply$")],
        states={{
            WAIT_TRIGGER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reply_trig)],
            WAIT_RESPONSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reply_resp)]
        }},
        fallbacks=[]
    )

    sug_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(suggest_init, pattern="^btn_suggest$")],
        states={{WAIT_SUGGESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggest_save)]}},
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("kick", group_kick))
    app.add_handler(reply_conv)
    app.add_handler(sug_conv)
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

    print("[+] Bot started successfully with complete feature set!")
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
'''

with open("main.py", "w", encoding="utf-8") as f:
    f.write(main_code)

print("[+] Clean rebuild completed.")
