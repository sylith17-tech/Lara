from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message):
    welcome_text = (
        f"<b>مرحباً بك في نظام Lara! 🚀</b>\n\n"
        f"أنا بوت الإدارة والتحكم الذكي.\n"
        f"معرفك: <code>{message.from_user.id}</code>\n\n"
        f"استخدم /help لعرض الأوامر المتاحة."
    )
    await message.answer(welcome_text)

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "<b>قائمة الأوامر المتاحة:</b>\n\n"
        "/start - بدء التشغيل وعرض الرسالة الترحيبية\n"
        "/help - عرض قائمة المساعدة\n"
        "/status - فحص حالة النظام"
    )
    await message.answer(help_text)

@router.message(Command("status"))
async def cmd_status(message: Message):
    await message.answer("<b>[✓] النظام يعمل بكفاءة عالية!</b>")
