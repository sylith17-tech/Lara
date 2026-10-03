"""Telegram UI and orchestration for the isolated natural-language editor."""
from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes, filters

from services.intent import EditPlan, parse_edit_request
from services.media_sessions import MediaSession, SessionState, media_sessions
from services.video_engine import MediaEngine, MediaEngineError, TEMPLATE_IDS, get_template
from services.video_jobs import JobState, video_jobs

CALLBACK_PREFIX = "video_editor:"
MAX_DOWNLOAD_BYTES = int(os.getenv("LARA_TELEGRAM_DOWNLOAD_MAX_BYTES", str(20 * 1024 * 1024)))
MAX_OUTPUT_BYTES = int(os.getenv("LARA_TELEGRAM_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))
MAX_SESSION_BYTES = int(os.getenv("LARA_VIDEO_SESSION_MAX_BYTES", str(80 * 1024 * 1024)))
MAX_SESSION_ITEMS = 8
MAX_SESSION_OPERATIONS = 40
MAX_HISTORY_VERSIONS = 8
MAX_SESSION_PREVIEWS = 6
MAX_PREVIEW_BYTES = 8 * 1024 * 1024

GUIDE = (
    "أرسل فيديو ثم استخدم لوحة التحكم أو اكتب طلبك بالعربية الطبيعية.\n\n"
    "أمثلة: قصلي أول 20 ثانية؛ شيل الصوت؛ حط صوت الفيديو الثاني على الأول؛ "
    "خلي الفيديو عمودي؛ صغّر حجمه؛ ادمج الفيديوهات؛ حط صورة بالنص.\n"
    "طلبات الترجمة وفصل الموسيقى تحتاج مزودًا خارجيًا، لذلك سيخبرك البوت إذا لم يكن متاحًا."
)

CATEGORIES = {
    "basic": ("القص والدمج", "قص جزء بزمن محدد، دمج فيديوهات، أو ضغط الحجم."),
    "audio": ("الصوت", "إزالة الصوت، استخراج الصوت، استبداله، دمجه، أو ضبط مستواه."),
    "video": ("الفيديو", "تغيير الاتجاه والأبعاد والسرعة والتدوير والقص."),
    "subtitles": ("الترجمة", "يمكن حرق ملف SRT/VTT ترسله. تفريغ الكلام والترجمة يحتاجان مزود STT غير مهيأ."),
    "visual": ("الصور والنص", "إضافة صورة أو كتابة وشعار وعلامة مائية."),
    "dimensions": ("الأحجام والمنصات", "تحجيم مع الحفاظ على النسبة والإطار المناسب للمنصة."),
    "effects": ("المؤثرات", "تلاشي وضبط السطوع والتباين والتشبع والتمويه والحدة."),
    "advanced": ("متقدم", "تجميع عدة عمليات بخطة واحدة ومعاينة قبل التنفيذ."),
    "ai": ("المحرر باللغة الطبيعية", "صف التعديلات بالعربية؛ يحلل المحرر الطلب محليًا ويراجع الخطة قبل تشغيل FFmpeg."),
}

TOOL_REQUESTS = {
    "effects": ["زود الإضاءة", "زود التباين", "خلي الألوان أقوى", "اعمل تمويه خفيف",
                "خلي الفيديو أبيض وأسود", "اعمل fade بالبداية", "اعمل fade بالنهاية", "زود حدة الفيديو"],
    "video": ["قص الفيديو", "سرّع الفيديو للضعف", "خليه بطيء", "دوّر الفيديو 90 درجة", "اقلب الفيديو أفقي",
              "اقلب الفيديو عمودي", "حول الفيديو إلى 9:16", "حول الفيديو إلى 16:9",
              "حول الفيديو إلى 1:1", "صغر حجم الفيديو"],
    "audio": ["شيل الصوت", "ارفع الصوت 150%", "اعمل fade للصوت بالبداية",
              "اعمل fade للصوت بالنهاية", "إضافة صوت"],
    "visual": ["أرسل نص لإضافته", "أرسل نص العلامة المائية"],
    "dimensions": ["حول الفيديو إلى 9:16", "حول الفيديو إلى 16:9", "حول الفيديو إلى 1:1",
                   "جهزه للريلز", "جهزه لليوتيوب", "جهزه لتليجرام"],
    "advanced": ["ادمج الفيديوهات", "اعكس الفيديو", "إضافة صورة"],
    "speed": ["خليه 0.25x", "خليه 0.5x", "خليه 0.75x", "خليه 1.25x", "خليه 1.5x", "خليه 2x"],
    "effects_more": ["زيد حرارة الألوان", "برّد الألوان", "اعكس الألوان", "أضف تظليل سينمائي", "أضف حبيبات فيلم"],
    "volume": ["الصوت 25%", "الصوت 50%", "الصوت 75%", "الصوت 100%", "الصوت 150%", "الصوت 200%"],
    "export": ["export high", "export balanced", "export small", "export telegram"],
}

CATEGORY_CODES = {"effects": "ef", "video": "vd", "audio": "au", "visual": "tx",
                  "dimensions": "dm", "advanced": "ad", "speed": "sp",
                  "effects_more": "fx", "volume": "vl", "export": "ex"}
CATEGORY_FROM_CODE = {value: key for key, value in CATEGORY_CODES.items()}


def editor_keyboard() -> InlineKeyboardMarkup:
    keys = [
        [InlineKeyboardButton("✂️ القص والدمج", callback_data=f"{CALLBACK_PREFIX}category:basic"),
         InlineKeyboardButton("🔊 الصوت", callback_data=f"{CALLBACK_PREFIX}category:audio")],
        [InlineKeyboardButton("🎥 الفيديو", callback_data=f"{CALLBACK_PREFIX}category:video"),
         InlineKeyboardButton("📝 الترجمة", callback_data=f"{CALLBACK_PREFIX}category:subtitles")],
        [InlineKeyboardButton("🖼️ الصور والنص", callback_data=f"{CALLBACK_PREFIX}category:visual"),
         InlineKeyboardButton("✨ المؤثرات", callback_data=f"{CALLBACK_PREFIX}category:effects")],
        [InlineKeyboardButton("⚙️ متقدم", callback_data=f"{CALLBACK_PREFIX}category:advanced"),
         InlineKeyboardButton("🤖 AI Editor", callback_data=f"{CALLBACK_PREFIX}category:ai")],
        [InlineKeyboardButton("📖 شرح الاستخدام", callback_data=f"{CALLBACK_PREFIX}guide"),
         InlineKeyboardButton("▶️ ابدأ جلسة", callback_data=f"{CALLBACK_PREFIX}start")],
    ]
    return InlineKeyboardMarkup(keys)


def _control_keyboard(job_id: str, lara_intro: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ اكتب ماذا تريد تعديله", callback_data=f"{CALLBACK_PREFIX}prompt:{job_id}")],
        [InlineKeyboardButton("✂️ القص والتحكم", callback_data=f"{CALLBACK_PREFIX}cat:{job_id}:vd"),
         InlineKeyboardButton("🎨 الألوان", callback_data=f"{CALLBACK_PREFIX}cat:{job_id}:ef")],
        [InlineKeyboardButton("🎚️ سرعات", callback_data=f"{CALLBACK_PREFIX}cat:{job_id}:sp"),
         InlineKeyboardButton("✨ مؤثرات متقدمة", callback_data=f"{CALLBACK_PREFIX}cat:{job_id}:fx")],
        [InlineKeyboardButton("🔊 الصوت", callback_data=f"{CALLBACK_PREFIX}cat:{job_id}:au"),
         InlineKeyboardButton("📝 النص", callback_data=f"{CALLBACK_PREFIX}cat:{job_id}:tx")],
        [InlineKeyboardButton("📐 المقاس", callback_data=f"{CALLBACK_PREFIX}cat:{job_id}:dm"),
         InlineKeyboardButton("🎬 الدمج", callback_data=f"{CALLBACK_PREFIX}cat:{job_id}:ad")],
        [InlineKeyboardButton("🚀 القوالب", callback_data=f"{CALLBACK_PREFIX}templates:{job_id}:0"),
         InlineKeyboardButton("🧠 اقتراح قوالب", callback_data=f"{CALLBACK_PREFIX}suggest:{job_id}")],
        [InlineKeyboardButton("📤 جودة التصدير", callback_data=f"{CALLBACK_PREFIX}cat:{job_id}:ex")],
        [InlineKeyboardButton("↩️ تراجع", callback_data=f"{CALLBACK_PREFIX}undo:{job_id}"),
         InlineKeyboardButton("↪️ إعادة", callback_data=f"{CALLBACK_PREFIX}redo:{job_id}"),
         InlineKeyboardButton("👁️ معاينة", callback_data=f"{CALLBACK_PREFIX}preview:{job_id}")],
        [InlineKeyboardButton("🎵 استخراج الصوت", callback_data=f"{CALLBACK_PREFIX}extract:{job_id}"),
         InlineKeyboardButton("🏷️ Lara Intro: " + ("تشغيل" if lara_intro else "إيقاف"), callback_data=f"{CALLBACK_PREFIX}intro:{job_id}")],
        [InlineKeyboardButton("💾 حفظ وإرسال", callback_data=f"{CALLBACK_PREFIX}save:{job_id}"),
         InlineKeyboardButton("❌ إنهاء بدون حفظ", callback_data=f"{CALLBACK_PREFIX}end:{job_id}")],
    ])


def _template_keyboard(job_id: str, page: int = 0) -> InlineKeyboardMarkup:
    page_size = 6
    pages = (len(TEMPLATE_IDS) + page_size - 1) // page_size
    page = max(0, min(page, pages - 1))
    visible = TEMPLATE_IDS[page * page_size:(page + 1) * page_size]
    rows = [[InlineKeyboardButton(get_template(template_id)["name"],
                                  callback_data=f"{CALLBACK_PREFIX}t:{job_id}:{TEMPLATE_IDS.index(template_id)}")]
            for template_id in visible]
    nav = []
    if page:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"{CALLBACK_PREFIX}templates:{job_id}:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{pages}", callback_data=f"{CALLBACK_PREFIX}templates:{job_id}:{page}"))
    if page + 1 < pages:
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"{CALLBACK_PREFIX}templates:{job_id}:{page+1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton("⬅️ لوحة التحكم", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")])
    return InlineKeyboardMarkup(rows)


def _category_keyboard(category: str, job_id: str) -> InlineKeyboardMarkup:
    labels = {
        "effects": ["☀️ إضاءة +", "🌗 تباين +", "🎨 ألوان أقوى", "🌫️ تمويه", "⚫ أبيض وأسود", "🎚️ Fade In", "🎚️ Fade Out", "✨ زيادة الحدة"],
        "video": ["✂️ قص حسب الوقت", "⚡ السرعة ×2", "🐢 بطيء ×0.5", "🔄 دوران 90°", "↔️ قلب أفقي", "↕️ قلب عمودي", "📱 9:16", "▶️ 16:9", "🟦 1:1", "📦 ضغط"],
        "audio": ["🔇 كتم الصوت", "🔊 صوت 150%", "🎚️ Fade In", "🎚️ Fade Out", "🎵 إضافة ملف صوت"],
        "visual": ["📝 إضافة نص", "💧 علامة مائية", "📱 9:16", "▶️ 16:9", "🟦 1:1"],
        "dimensions": ["📱 TikTok / Reels / Shorts 9:16", "▶️ YouTube 16:9", "⬛ Instagram 1:1", "📲 Story 9:16", "🖥️ YouTube Pro", "✈️ Telegram Ready"],
        "advanced": ["🎬 دمج الفيديوهات", "🔁 عكس الفيديو", "🖼️ أرسل صورة Overlay"],
        "speed": ["🐌 0.25x", "🐢 0.5x", "🎞️ 0.75x", "🚶 1.25x", "🏃 1.5x", "⚡ 2x"],
        "effects_more": ["🌡️ أدفأ", "❄️ أبرد", "➖ نيجاتيف", "🌘 Vignette", "🎞️ Film Grain"],
        "volume": ["🔉 25%", "🔉 50%", "🔊 75%", "🔊 100%", "🔊 150%", "🔊 200%"],
        "export": ["🏆 جودة عالية", "⚖️ متوازن", "📦 حجم صغير", "✈️ مناسب لتليجرام"],
    }
    rows = [[InlineKeyboardButton(label, callback_data=f"{CALLBACK_PREFIX}op:{job_id}:{CATEGORY_CODES[category]}:{i}")]
            for i, label in enumerate(labels.get(category, []))]
    if category == "audio":
        rows.extend([
            [InlineKeyboardButton("➕ مزج ملف صوت", callback_data=f"{CALLBACK_PREFIX}am:{job_id}:m"),
             InlineKeyboardButton("🔄 تكرار الصوت ومزجه", callback_data=f"{CALLBACK_PREFIX}am:{job_id}:ml")],
            [InlineKeyboardButton("🔁 استبدال الصوت", callback_data=f"{CALLBACK_PREFIX}am:{job_id}:r"),
             InlineKeyboardButton("🔁 تكرار الصوت واستبداله", callback_data=f"{CALLBACK_PREFIX}am:{job_id}:rl")],
            [InlineKeyboardButton("📹 استخراج صوت من فيديو", callback_data=f"{CALLBACK_PREFIX}audio_video_source:{job_id}")],
            [InlineKeyboardButton("🎚️ مستويات الصوت", callback_data=f"{CALLBACK_PREFIX}category:volume:{job_id}")],
        ])
    if category == "advanced":
        rows.insert(0, [InlineKeyboardButton("🎬 أرسل فيديو لدمجه", callback_data=f"{CALLBACK_PREFIX}merge_video:{job_id}")])
    rows.append([InlineKeyboardButton("⬅️ لوحة التحكم", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")])
    return InlineKeyboardMarkup(rows)


def _cancel_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ انتهيت من إرسال الوسائط", callback_data=f"{CALLBACK_PREFIX}finish:{job_id}"),
                                  InlineKeyboardButton("❌ إلغاء", callback_data=f"{CALLBACK_PREFIX}cancel:{job_id}")]])


async def open_editor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or update.effective_chat.type != "private":
        target = update.effective_message
        if target:
            await target.reply_text("🎬 محرر الفيديو متاح في المحادثة الخاصة مع Lara فقط.")
        return
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.reply_text("🎬 محرر الفيديو\n\nاختر قسمًا أو ابدأ جلسة تحرير:", reply_markup=editor_keyboard())
    elif update.message:
        await update.message.reply_text("🎬 محرر الفيديو\n\nاختر قسمًا أو ابدأ جلسة تحرير:", reply_markup=editor_keyboard())


async def _new_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> MediaSession:
    user, chat = update.effective_user, update.effective_chat
    if not user or not chat or chat.type != "private":
        raise RuntimeError("A private user/chat is required")
    existing_id = context.user_data.get("video_editor_job")
    if existing_id:
        existing = await media_sessions.get(existing_id, user.id, chat.id)
        if existing and existing.state not in (SessionState.COMPLETED, SessionState.FAILED, SessionState.CANCELLED):
            return existing
    await media_sessions.cleanup_expired()
    session = await media_sessions.create(user.id, chat.id)
    context.user_data["video_editor_job"] = session.job_id
    return session


async def _describe_plan(plan: EditPlan) -> str:
    labels = {
        "trim": lambda o: f"قص الفيديو من {o['start']:.2f} إلى {o['end']:.2f} ثانية",
        "trim_head": lambda o: f"حذف أول {o['duration']:g} ثانية",
        "trim_tail": lambda o: f"حذف آخر {o['duration']:g} ثانية",
        "trim_audio": lambda o: f"قص الصوت من {o['start']:.2f} إلى {o['end']:.2f} ثانية",
        "extract_audio": lambda o: "استخراج نسخة صوتية من الفيديو",
        "audio_fade": lambda o: f"تلاشي الصوت {('دخول' if o.get('direction') == 'in' else 'خروج')} خلال {o['duration']:g} ثانية",
        "audio_offset": lambda o: f"مزامنة الصوت بتقديم/تأخير {o['seconds']:g} ثانية",
        "remove_audio": lambda o: "حذف الصوت الأصلي",
        "replace_audio": lambda o: "استبدال الصوت بملف الصوت المرسل",
        "mix_audio": lambda o: "دمج صوت إضافي مع صوت الفيديو",
        "change_speed": lambda o: f"تغيير السرعة إلى {o['factor']:g}x",
        "resize": lambda o: f"تغيير المقاس إلى {o['width']}×{o['height']}",
        "compress": lambda o: "ضغط الفيديو لتقليل الحجم",
        "concat_videos": lambda o: "دمج الفيديوهات المرسلة بترتيبها",
        "overlay_image": lambda o: "إضافة الصورة في وسط الفيديو" + (f" لأول {o['duration']:g} ثوانٍ" if o.get("duration") else ""),
        "text_overlay": lambda o: f"إضافة النص: {o['text'][:40]}",
        "normalize_audio": lambda o: "موازنة مستوى الصوت",
        "grayscale": lambda o: "تحويل إلى أبيض وأسود",
        "hue": lambda o: f"تغيير Hue بمقدار {o['value']}°",
        "temperature": lambda o: "ضبط حرارة الألوان",
        "negative": lambda o: "عكس الألوان",
        "vignette": lambda o: "تظليل حواف الفيديو",
        "film_grain": lambda o: "إضافة حبيبات فيلم",
    }
    lines = [f"{i}. {labels.get(op['type'], lambda _: op['type'])(op)}" for i, op in enumerate(plan.operations, 1)]
    return "🎬 خطة التعديل:\n\n" + "\n".join(lines)


async def _download_assets(update: Update, session: MediaSession, context: ContextTypes.DEFAULT_TYPE) -> list[Path]:
    paths = []
    downloaded_bytes = 0
    for item in session.media:
        if item.file_size and item.file_size > MAX_DOWNLOAD_BYTES:
            raise MediaEngineError(f"الملف {item.index} حجمه يتجاوز حد التنزيل المضبوط ({MAX_DOWNLOAD_BYTES // (1024*1024)} MB).")
        tg_file = await context.bot.get_file(item.file_id)
        reported = getattr(tg_file, "file_size", None)
        if reported and reported > MAX_DOWNLOAD_BYTES:
            raise MediaEngineError(f"الملف {item.index} يتجاوز حد تنزيل Telegram المضبوط.")
        suffix = Path(item.filename).suffix[:12] or {"video": ".mp4", "video_document": ".mp4", "audio": ".audio", "audio_document": ".audio", "voice": ".ogg", "image": ".img"}.get(item.kind, ".bin")
        target = session.job_dir / "input" / f"asset_{item.index:03d}{suffix}"
        if not target.is_file():
            tg_file = await context.bot.get_file(item.file_id)
            reported = getattr(tg_file, "file_size", None)
            if reported and reported > MAX_DOWNLOAD_BYTES:
                raise MediaEngineError(f"الملف {item.index} يتجاوز حد تنزيل Telegram المضبوط.")
            await tg_file.download_to_drive(custom_path=str(target))
        if not target.is_file() or not target.stat().st_size:
            raise MediaEngineError(f"تعذر تنزيل الملف {item.index} أو أنه فارغ.")
        downloaded_bytes += target.stat().st_size
        if downloaded_bytes > MAX_SESSION_BYTES:
            target.unlink(missing_ok=True)
            raise MediaEngineError(f"تجاوزت الوسائط حد الجلسة ({MAX_SESSION_BYTES // (1024*1024)} MB).")
        item.local_path = str(target)
        paths.append(target)
    return paths


async def _prepare_primary_video(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                session: MediaSession, item, message) -> None:
    try:
        await _download_assets(update, session, context)
        original = Path(item.local_path)
        working_copy = session.job_dir / "output" / "working_copy.mp4"
        import shutil
        shutil.copy2(original, working_copy)
        session.result_path = str(working_copy)
        session.history = [str(working_copy)]
        session.history_cursor = 0
        await media_sessions.set_state(session.job_id, session.user_id, SessionState.READY)
        await message.reply_text("📥 تم استلام الفيديو بنجاح.\n\n🎬 تم تجهيز نسخة العمل.\n\n"
                                 "يمكنك الآن تعديل الفيديو كما تريد، ويمكنك تنفيذ عدة تعديلات متتالية قبل الحفظ.\n\n"
                                 "✍️ اكتب ماذا تريد تعديله، أو اختر أداة من لوحة التحكم.",
                                 reply_markup=_control_keyboard(session.job_id, session.lara_intro))
    except Exception as exc:
        await media_sessions.set_state(session.job_id, session.user_id, SessionState.READY)
        await message.reply_text(f"⚠️ تعذر تجهيز نسخة العمل: {str(exc)[:250]} أعد إرسال الفيديو.")


async def _execute(update: Update, context: ContextTypes.DEFAULT_TYPE, session: MediaSession, status_message_id: int) -> None:
    await media_sessions.set_state(session.job_id, session.user_id, SessionState.PROCESSING)
    engine = MediaEngine(timeout_seconds=int(os.getenv("LARA_FFMPEG_TIMEOUT", "1800")))
    generated_paths: list[Path] = []
    try:
        if session.operation_count + len(session.plan) > MAX_SESSION_OPERATIONS:
            raise MediaEngineError(f"بلغت الجلسة حد العمليات ({MAX_SESSION_OPERATIONS}). احفظ الناتج وابدأ جلسة جديدة.")
        await _download_assets(update, session, context)
        videos = [Path(session.media[i].local_path) for i in range(len(session.media))
                  if session.media[i].kind in ("video", "video_document")]
        audios = [Path(m.local_path) for m in session.media
                  if m.local_path and m.kind in ("audio", "audio_document", "voice")]
        if not videos and not audios:
            raise MediaEngineError("أرسل فيديو أو ملفًا صوتيًا واحدًا على الأقل.")
        audio_only = not videos
        original = videos[0] if videos else audios[0]
        if videos:
            source_meta = await engine.probe_media(original)
            if float(source_meta.get("format", {}).get("duration", 0)) > 7200:
                raise MediaEngineError("المدة القصوى المدعومة ساعتان.")
        if videos and not session.result_path:
            import shutil
            working_copy = session.job_dir / "output" / "working_copy.mp4"
            shutil.copy2(original, working_copy)
            session.result_path = str(working_copy)
        current = Path(session.result_path) if session.result_path else original
        if not session.history and videos:
            session.history = [str(original)]
            session.history_cursor = 0
        extracted_audio: list[Path] = []
        step = 0
        last_progress_edit = 0.0
        loop = asyncio.get_running_loop()

        def report_progress(value: str) -> None:
            nonlocal last_progress_edit
            now = time.monotonic()
            if now - last_progress_edit < 12:
                return
            last_progress_edit = now
            try:
                seconds = max(0, int(value) // 1_000_000)
                loop.create_task(context.bot.edit_message_text(
                    f"⚙️ جارٍ تنفيذ التعديل… وصل ترميز الوسائط إلى نحو {seconds} ثانية.",
                    chat_id=session.chat_id, message_id=status_message_id))
            except Exception:
                pass
        for op in session.plan:
            step += 1
            if op["type"] == "extract_audio":
                audio_output = session.job_dir / "output" / f"extracted_audio_{step:03d}.m4a"
                await engine.apply(current, audio_output, op, progress=report_progress)
                extracted_audio.append(audio_output)
                continue
            audio_op = op["type"] in ("trim_audio", "audio_fade", "audio_offset") or (audio_only and op["type"] in ("mix_audio", "volume", "change_speed"))
            target = session.job_dir / "output" / f"edit_{uuid.uuid4().hex}_{step:03d}{'.m4a' if audio_op else '.mp4'}"
            generated_paths.append(target)
            if op["type"] == "concat_videos":
                current = await engine.concat_videos([current, *videos[1:]], target, progress=report_progress)
                continue
            auxiliary = None
            if op["type"] in ("replace_audio", "mix_audio"):
                if op.get("source_video_index"):
                    chosen = [Path(m.local_path) for m in session.media
                              if m.local_path and m.kind in ("video", "video_document")]
                    source_index = int(op["source_video_index"]) - 1
                    auxiliary = chosen[source_index] if source_index < len(chosen) else None
                else:
                    audio_sources = [Path(m.local_path) for m in session.media
                                     if m.local_path and m.kind in ("audio", "audio_document", "voice")]
                    aux_index = int(op.get("media_index", 1)) - 1
                    auxiliary = audio_sources[aux_index] if 0 <= aux_index < len(audio_sources) else None
            elif op["type"] == "overlay_image":
                image_sources = [Path(m.local_path) for m in session.media if m.local_path and m.kind == "image"]
                image_index = int(op.get("media_index", 1)) - 1
                auxiliary = image_sources[image_index] if 0 <= image_index < len(image_sources) else None
            elif op["type"] == "burn_subtitles":
                subtitle_sources = [Path(m.local_path) for m in session.media if m.local_path and m.kind == "subtitle"]
                subtitle_index = int(op.get("media_index", 1)) - 1
                auxiliary = subtitle_sources[subtitle_index] if 0 <= subtitle_index < len(subtitle_sources) else None
            current = await engine.apply(current, target, op, auxiliary=auxiliary, progress=report_progress)
        video_result = bool(videos and current != original
                            and any(op["type"] != "extract_audio" for op in session.plan))
        if ((video_result and current.stat().st_size > MAX_OUTPUT_BYTES) or any(p.stat().st_size > MAX_OUTPUT_BYTES for p in extracted_audio)):
            raise MediaEngineError(f"الناتج أكبر من حد الإرسال المضبوط ({MAX_OUTPUT_BYTES // (1024*1024)} MB). أعد الطلب مع ضغط الفيديو.")
        if video_result:
            discarded = session.history[session.history_cursor + 1:]
            session.history = session.history[:session.history_cursor + 1]
            session.history.append(str(current))
            session.history_cursor += 1
            if len(session.history) > MAX_HISTORY_VERSIONS:
                discarded.extend(session.history[:-MAX_HISTORY_VERSIONS])
                session.history = session.history[-MAX_HISTORY_VERSIONS:]
                session.history_cursor = len(session.history) - 1
            retained = set(session.history)
            for obsolete in discarded:
                if obsolete not in retained:
                    Path(obsolete).unlink(missing_ok=True)
            session.result_path = str(current)
            session.operation_count += sum(op["type"] != "extract_audio" for op in session.plan)
        for audio_path in extracted_audio:
            with audio_path.open("rb") as output:
                await context.bot.send_audio(chat_id=session.chat_id, audio=output, title="Extracted audio")
            audio_path.unlink(missing_ok=True)
        for generated in generated_paths:
            if generated != current:
                generated.unlink(missing_ok=True)
        await media_sessions.set_state(session.job_id, session.user_id, SessionState.READY)
        await context.bot.edit_message_text("✅ تم تطبيق التعديل على نسخة العمل. يمكنك مواصلة التحرير أو التراجع.",
                                            chat_id=session.chat_id, message_id=status_message_id,
                                            reply_markup=_control_keyboard(session.job_id, session.lara_intro))
        session.task = None
    except Exception as exc:
        for generated in generated_paths:
            generated.unlink(missing_ok=True)
        await media_sessions.set_state(session.job_id, session.user_id, SessionState.READY)
        try:
            await context.bot.edit_message_text(f"❌ تعذر تنفيذ التعديل، ونسختك السابقة محفوظة: {str(exc)[:500]}", chat_id=session.chat_id, message_id=status_message_id,
                                                reply_markup=_control_keyboard(session.job_id, session.lara_intro))
        except Exception:
            pass
        raise


async def _queue_preview(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         session: MediaSession, operations: list[dict] | None = None) -> None:
    if session.state == SessionState.PROCESSING:
        await update.effective_message.reply_text("⏳ توجد عملية أخرى قيد التنفيذ لهذه الجلسة.")
        return
    if session.preview_count >= MAX_SESSION_PREVIEWS:
        await update.effective_message.reply_text("بلغت حد المعاينات لهذه الجلسة. احفظ الفيديو أو تابع التعديل.")
        return
    status = await update.effective_message.reply_text("👁️ جارٍ إعداد معاينة قصيرة ومنخفضة الجودة…")
    resume_state = session.state if session.state != SessionState.PROCESSING else SessionState.READY
    await media_sessions.set_state(session.job_id, session.user_id, SessionState.PROCESSING)
    session.preview_count += 1
    preview_job_id = f"{session.job_id}_preview_{uuid.uuid4().hex[:8]}"

    async def processor() -> None:
        paths: list[Path] = []
        try:
            await _download_assets(update, session, context)
            primary = next((Path(item.local_path) for item in session.media
                            if item.local_path and item.kind in ("video", "video_document")), None)
            source = Path(session.result_path) if session.result_path else primary
            if not source:
                raise MediaEngineError("أرسل فيديو أولًا لإنشاء معاينة.")
            engine = MediaEngine(timeout_seconds=int(os.getenv("LARA_FFMPEG_TIMEOUT", "1800")))
            preview_input = session.job_dir / "temp" / f"preview_input_{uuid.uuid4().hex}.mp4"
            paths.append(preview_input)
            current = await engine.create_preview(source, preview_input, duration=5)
            for index, operation in enumerate(operations or [], 1):
                target = session.job_dir / "temp" / f"preview_step_{uuid.uuid4().hex}_{index}.mp4"
                current = await engine.apply(current, target, operation)
                paths.append(target)
            final_preview = session.job_dir / "temp" / f"preview_final_{uuid.uuid4().hex}.mp4"
            paths.append(final_preview)
            await engine.create_preview(current, final_preview, duration=5)
            if final_preview.stat().st_size > MAX_PREVIEW_BYTES:
                raise MediaEngineError("حجم المعاينة تجاوز الحد الآمن. جرّب مقطعًا أقصر.")
            with final_preview.open("rb") as output:
                await context.bot.send_video(chat_id=session.chat_id, video=output,
                                             caption="👁️ معاينة منخفضة الجودة لأول 5 ثوانٍ؛ النسخة الأصلية لم تتغير.")
            await context.bot.edit_message_text("✅ انتهت المعاينة. يمكنك تطبيق التعديل أو متابعة التحرير.",
                                                chat_id=session.chat_id, message_id=status.message_id,
                                                reply_markup=_control_keyboard(session.job_id, session.lara_intro))
        except Exception as exc:
            await context.bot.edit_message_text(f"⚠️ تعذرت المعاينة. نسخة العمل محفوظة: {str(exc)[:300]}",
                                                chat_id=session.chat_id, message_id=status.message_id,
                                                reply_markup=_control_keyboard(session.job_id, session.lara_intro))
        finally:
            for path in paths:
                path.unlink(missing_ok=True)
            await media_sessions.set_state(session.job_id, session.user_id,
                                            resume_state if resume_state == SessionState.WAITING_FOR_CONFIRMATION else SessionState.READY)
            session.task = None

    try:
        record = await video_jobs.submit(preview_job_id, processor)
        session.task = record.task
    except Exception:
        await media_sessions.set_state(session.job_id, session.user_id, SessionState.READY)
        raise


def _template_picker(job_id: str, template_id: str) -> InlineKeyboardMarkup:
    template_index = TEMPLATE_IDS.index(template_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👁️ معاينة 5 ثوانٍ", callback_data=f"{CALLBACK_PREFIX}tp:{job_id}:{template_index}")],
        [InlineKeyboardButton("✅ تطبيق القالب", callback_data=f"{CALLBACK_PREFIX}confirm:{job_id}")],
        [InlineKeyboardButton("↩️ رجوع للقوالب", callback_data=f"{CALLBACK_PREFIX}templates:{job_id}:0")],
    ])


def _text_options_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📍 أعلى", callback_data=f"{CALLBACK_PREFIX}tx:{job_id}:t:36:0"),
         InlineKeyboardButton("📍 وسط", callback_data=f"{CALLBACK_PREFIX}tx:{job_id}:c:36:0"),
         InlineKeyboardButton("📍 أسفل", callback_data=f"{CALLBACK_PREFIX}tx:{job_id}:b:36:0")],
        [InlineKeyboardButton("🔠 كبير", callback_data=f"{CALLBACK_PREFIX}tx:{job_id}:c:52:0"),
         InlineKeyboardButton("🔲 خلفية", callback_data=f"{CALLBACK_PREFIX}tx:{job_id}:c:36:1")],
        [InlineKeyboardButton("⬅️ لوحة التحكم", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")],
    ])


async def handle_editor_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user, chat = update.effective_user, update.effective_chat
    if not chat or chat.type != "private":
        return
    job_id = context.user_data.get("video_editor_job")
    if not message or not user or not chat or not job_id:
        return
    session = await media_sessions.get(job_id, user.id, chat.id)
    if not session:
        return
    document_mime = (message.document.mime_type or "") if message and message.document else ""
    incoming_video = bool(message and (message.video or (message.document and document_mime.startswith("video/"))))
    awaiting_secondary_video = session.state in (SessionState.WAITING_MERGE_VIDEO, SessionState.WAITING_AUDIO_VIDEO)
    has_primary_video = any(item.kind in ("video", "video_document") for item in session.media)
    if incoming_video and has_primary_video and not awaiting_secondary_video and session.state != SessionState.PROCESSING:
        media_obj = message.video or message.document
        context.user_data["video_editor_pending_replacement"] = {
            "job_id": session.job_id,
            "file_id": media_obj.file_id,
            "filename": getattr(media_obj, "file_name", None) or f"replacement_{media_obj.file_unique_id}.mp4",
            "file_size": getattr(media_obj, "file_size", None),
            "mime_type": document_mime,
        }
        await message.reply_text("لديك جلسة تحرير مفتوحة. هل تريد استبدال الفيديو الأساسي؟",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 استبدال الفيديو", callback_data=f"{CALLBACK_PREFIX}replace_video:{job_id}")],
                                               [InlineKeyboardButton("❌ الاحتفاظ بالفيديو الحالي", callback_data=f"{CALLBACK_PREFIX}keep_video:{job_id}")]]))
        raise ApplicationHandlerStop
    if session.state not in (SessionState.RECEIVING_MEDIA, SessionState.WAITING_FOR_INSTRUCTIONS,
                             SessionState.WAITING_TEXT, SessionState.WAITING_AUDIO,
                             SessionState.WAITING_AUDIO_VIDEO, SessionState.WAITING_MERGE_VIDEO):
        await message.reply_text("الجلسة لا تستقبل وسائط الآن. استخدم الأزرار لمتابعة الخطة أو إلغائها.")
        raise ApplicationHandlerStop
    media_obj, kind, filename, mime = None, None, None, None
    if message.video:
        media_obj, kind, filename = message.video, "video", f"video_{message.video.file_unique_id}.mp4"
    elif message.audio:
        media_obj, kind, filename = message.audio, "audio", message.audio.file_name or f"audio_{message.audio.file_unique_id}.audio"
    elif message.voice:
        media_obj, kind, filename = message.voice, "voice", f"voice_{message.voice.file_unique_id}.ogg"
    elif message.photo:
        media_obj, kind, filename = message.photo[-1], "image", f"image_{message.photo[-1].file_unique_id}.jpg"
    elif message.document:
        doc = message.document
        mime = doc.mime_type or ""
        if mime.startswith("video/"):
            kind = "video_document"
        elif mime.startswith("audio/"):
            kind = "audio_document"
        elif mime.startswith("image/"):
            kind = "image"
        elif (doc.file_name or "").lower().endswith((".srt", ".vtt")) or mime in ("application/x-subrip", "text/vtt"):
            kind = "subtitle"
        if kind:
            media_obj, filename = doc, doc.file_name or f"document_{doc.file_unique_id}.bin"
    if not media_obj:
        return
    if session.state == SessionState.WAITING_MERGE_VIDEO and kind not in ("video", "video_document"):
        await message.reply_text("أرسل فيديو لإتمام الدمج.")
        return
    if session.state == SessionState.WAITING_AUDIO_VIDEO and kind not in ("video", "video_document"):
        await message.reply_text("أرسل فيديو يحتوي على مسار صوتي.")
        return
    if session.state == SessionState.WAITING_AUDIO and kind not in ("audio", "audio_document", "voice"):
        await message.reply_text("أرسل ملفًا صوتيًا مدعومًا مثل MP3 أو M4A أو WAV.")
        return
    if len(session.media) >= MAX_SESSION_ITEMS:
        await message.reply_text(f"الحد الأقصى {MAX_SESSION_ITEMS} وسائط لكل جلسة.")
        return
    current_size = sum(m.file_size or 0 for m in session.media)
    incoming_size = getattr(media_obj, "file_size", 0) or 0
    if current_size + incoming_size > MAX_SESSION_BYTES:
        await message.reply_text(f"تجاوزت الوسائط حد الجلسة ({MAX_SESSION_BYTES // (1024*1024)} MB).")
        return
    item = await media_sessions.add_media(job_id, user.id, chat.id, file_id=media_obj.file_id,
                                          kind=kind, filename=filename,
                                          file_size=getattr(media_obj, "file_size", None), mime_type=mime)
    if item:
        was_waiting_audio_video = session.state == SessionState.RECEIVING_MEDIA and context.user_data.pop("video_editor_audio_video_pending", False)
        was_waiting_merge_video = session.state == SessionState.RECEIVING_MEDIA and context.user_data.pop("video_editor_merge_pending", False)
        audio_mode = context.user_data.pop("video_editor_audio_mode", None)
        if was_waiting_audio_video and kind in ("video", "video_document"):
            videos = [m for m in session.media if m.kind in ("video", "video_document")]
            if len(videos) >= 2:
                await media_sessions.set_state(job_id, user.id, SessionState.READY)
                await message.reply_text("🎵 تم استلام الفيديو واستخراج مساره الصوتي عند التطبيق. اختر طريقة الاستخدام:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 استبدال الصوت", callback_data=f"{CALLBACK_PREFIX}av:{job_id}:r")],
                                                       [InlineKeyboardButton("🔁 تكرار المصدر واستبداله", callback_data=f"{CALLBACK_PREFIX}av:{job_id}:rl")],
                                                       [InlineKeyboardButton("🎚️ مزج مع الصوت الأصلي", callback_data=f"{CALLBACK_PREFIX}av:{job_id}:m")],
                                                       [InlineKeyboardButton("🔁 تكرار المصدر ومزجه", callback_data=f"{CALLBACK_PREFIX}av:{job_id}:ml")],
                                                       [InlineKeyboardButton("↩️ رجوع", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")]]))
                raise ApplicationHandlerStop
        if was_waiting_merge_video and kind in ("video", "video_document"):
            videos = [m for m in session.media if m.kind in ("video", "video_document")]
            session.plan = [{"type": "concat_videos"}]
            await media_sessions.set_state(job_id, user.id, SessionState.WAITING_FOR_CONFIRMATION)
            await message.reply_text(f"🎬 جاهز لدمج {len(videos)} فيديوهات بالتسلسل.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ دمج الفيديوهات", callback_data=f"{CALLBACK_PREFIX}confirm:{job_id}")], [InlineKeyboardButton("⬅️ لوحة التحكم", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")]]))
            raise ApplicationHandlerStop
        if audio_mode and kind in ("audio", "audio_document", "voice"):
            mode = audio_mode.removesuffix("_loop")
            session.plan = [{"type": "mix_audio", "media_index": 1, "volume": 0.35, "repeat": audio_mode.endswith("_loop")} if mode == "mix"
                            else {"type": "replace_audio", "media_index": 1, "repeat": audio_mode.endswith("_loop")}]
            await media_sessions.set_state(job_id, user.id, SessionState.WAITING_FOR_CONFIRMATION)
            label = "مزج الملف مع الصوت الأصلي بنسبة مناسبة" if audio_mode == "mix" else "استبدال المسار الصوتي الأصلي"
            await message.reply_text(f"🎵 جاهز: {label}.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ تطبيق", callback_data=f"{CALLBACK_PREFIX}confirm:{job_id}")], [InlineKeyboardButton("⬅️ لوحة التحكم", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")]]))
            raise ApplicationHandlerStop
        if kind in ("video", "video_document") and not session.result_path:
            try:
                await _download_assets(update, session, context)
                primary = Path(item.local_path)
                working_copy = session.job_dir / "output" / "working_copy.mp4"
                import shutil
                shutil.copy2(primary, working_copy)
                session.result_path = str(working_copy)
                session.history = [str(working_copy)]
                session.history_cursor = 0
            except Exception as exc:
                await message.reply_text(f"⚠️ تعذر تجهيز نسخة العمل: {str(exc)[:250]} أعد إرسال الفيديو.")
                raise ApplicationHandlerStop
            await media_sessions.set_state(job_id, user.id, SessionState.READY)
            await message.reply_text("📥 تم استلام الفيديو بنجاح.\n\n🎬 تم تجهيز نسخة العمل.\n\n"
                                     "يمكنك الآن تعديل الفيديو كما تريد، ويمكنك تنفيذ عدة تعديلات متتالية قبل الحفظ.\n\n"
                                     "✍️ اكتب ماذا تريد تعديله، أو اختر أداة من لوحة التحكم.",
                                     reply_markup=_control_keyboard(job_id, session.lara_intro))
        else:
            await media_sessions.set_state(job_id, user.id, SessionState.WAITING_FOR_INSTRUCTIONS)
            await message.reply_text(f"✅ أُضيف الوسيط رقم {item.index} ({kind}). ارجع للوحة التحكم وأرسل طلبك.",
                                     reply_markup=_control_keyboard(job_id, session.lara_intro))
        raise ApplicationHandlerStop


async def handle_editor_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message, user, chat = update.effective_message, update.effective_user, update.effective_chat
    if not chat or chat.type != "private":
        return
    job_id = context.user_data.get("video_editor_job")
    if not message or not message.text or not user or not chat or not job_id:
        return
    session = await media_sessions.get(job_id, user.id, chat.id)
    if not session:
        return
    if session.state == SessionState.WAITING_FOR_CONFIRMATION:
        await message.reply_text("الخطة جاهزة. استخدم أزرار التنفيذ أو تعديل الطلب أولًا.")
        raise ApplicationHandlerStop
    if session.state == SessionState.PROCESSING:
        await message.reply_text("المهمة قيد المعالجة. أرسل طلبًا جديدًا بعد اكتمالها.")
        raise ApplicationHandlerStop
    if session.state == SessionState.WAITING_TEXT:
        clean_text = message.text.strip()
        if not clean_text or len(clean_text) > 300:
            await message.reply_text("أرسل نصًا بين حرف واحد و300 حرف.")
            raise ApplicationHandlerStop
        context.user_data["video_editor_text_value"] = clean_text
        await message.reply_text("اختر موضع النص وحجمه:", reply_markup=_text_options_keyboard(job_id))
        raise ApplicationHandlerStop
    if session.state not in (SessionState.WAITING_FOR_INSTRUCTIONS, SessionState.READY):
        return
    pending_text = context.user_data.pop("video_editor_pending_text", None)
    if pending_text:
        session.prompt = f'حط كتابة "{message.text.strip()}" على الفيديو'
    else:
        session.prompt = (session.prompt + " " + message.text).strip() if session.clarification else message.text.strip()
    plan = parse_edit_request(session.prompt, session.media)
    session.plan = plan.operations
    session.clarification = plan.clarification
    if plan.clarification:
        await message.reply_text("❓ " + plan.clarification)
        raise ApplicationHandlerStop
    if plan.unsupported:
        await message.reply_text("⚠️ لا أستطيع تنفيذ هذا الجزء حاليًا:\n" + "\n".join(plan.unsupported))
        raise ApplicationHandlerStop
    if not plan.ready:
        await message.reply_text("لم أتمكن من إعداد خطة آمنة لهذا الطلب. استخدم شرح المحرر أو أعد صياغته.")
        raise ApplicationHandlerStop
    await media_sessions.set_state(job_id, user.id, SessionState.WAITING_FOR_CONFIRMATION)
    session.plan = plan.operations
    text = await _describe_plan(plan)
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("▶️ تنفيذ", callback_data=f"{CALLBACK_PREFIX}confirm:{job_id}"),
                                     InlineKeyboardButton("✏️ تعديل الطلب", callback_data=f"{CALLBACK_PREFIX}edit:{job_id}")],
                                    [InlineKeyboardButton("⬅️ لوحة التحكم", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")]])
    await message.reply_text(text, reply_markup=buttons)
    raise ApplicationHandlerStop


async def video_editor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user or not update.effective_chat:
        return
    data = query.data or ""
    await query.answer()
    if update.effective_chat.type != "private":
        await query.message.reply_text("🎬 محرر الفيديو متاح في المحادثة الخاصة فقط. افتح البوت واضغط Start.")
        return
    if data == f"{CALLBACK_PREFIX}open":
        await query.message.reply_text("🎬 محرر الفيديو\n\nاختر قسمًا أو ابدأ جلسة تحرير:", reply_markup=editor_keyboard())
        return
    if data == f"{CALLBACK_PREFIX}guide":
        await query.message.reply_text(GUIDE, reply_markup=editor_keyboard())
        return
    if data.startswith(f"{CALLBACK_PREFIX}category:"):
        parts = data.split(":")
        category = parts[2]
        if len(parts) == 4:
            job_id = parts[3]
            session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
            if not session:
                await query.message.reply_text("انتهت الجلسة أو لا تملك صلاحية الوصول إليها.")
                return
            await query.message.reply_text(CATEGORIES.get(category, CATEGORIES["advanced"])[0], reply_markup=_category_keyboard(category, job_id))
            return
        title, description = CATEGORIES.get(category, CATEGORIES["advanced"])
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📖 شرح", callback_data=f"{CALLBACK_PREFIX}guide")],
                                   [InlineKeyboardButton("▶️ تنفيذ / AI Editor", callback_data=f"{CALLBACK_PREFIX}start")],
                                   [InlineKeyboardButton("↩️ رجوع", callback_data=f"{CALLBACK_PREFIX}open")]])
        await query.message.reply_text(f"{title}\n\n{description}\n\nأرسل الوسائط ثم اكتب طلبك بالعربية الطبيعية.", reply_markup=kb)
        return
    compact_category = re.fullmatch(r"video_editor:cat:([a-f0-9]{32}):([a-z]+)", data)
    if compact_category:
        job_id, category_code = compact_category.groups()
        category = CATEGORY_FROM_CODE.get(category_code)
        session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
        if not session or not category:
            await query.message.reply_text("انتهت الجلسة أو لا تملك صلاحية الوصول إليها.")
            return
        await query.message.reply_text(CATEGORIES.get(category, (category, ""))[0],
                                      reply_markup=_category_keyboard(category, job_id))
        return
    templates_page = re.fullmatch(r"video_editor:templates:([a-f0-9]{32}):(\d+)", data)
    if templates_page:
        job_id, page_text = templates_page.groups()
        session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
        if not session:
            await query.message.reply_text("انتهت الجلسة أو لا تملك صلاحية الوصول إليها.")
            return
        await query.message.reply_text("🚀 Lara Video Studio — قوالب مبنية من عمليات FFmpeg حقيقية:",
                                      reply_markup=_template_keyboard(job_id, int(page_text)))
        return
    selected_template = re.fullmatch(r"video_editor:t:([a-f0-9]{32}):(\d+)", data)
    if selected_template:
        job_id, template_index = selected_template.groups()
        if int(template_index) >= len(TEMPLATE_IDS):
            await query.message.reply_text("القالب غير متاح.")
            return
        template_id = TEMPLATE_IDS[int(template_index)]
        session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
        if not session:
            await query.message.reply_text("انتهت الجلسة أو لا تملك صلاحية الوصول إليها.")
            return
        try:
            template = get_template(template_id)
        except ValueError:
            await query.message.reply_text("القالب غير متاح.")
            return
        session.selected_template = template_id
        session.plan = template["operations"]
        session.prompt = f"template:{template_id}"
        await media_sessions.set_state(job_id, session.user_id, SessionState.WAITING_FOR_CONFIRMATION)
        await query.message.reply_text(f"🚀 {template['name']}\n\n" + await _describe_plan(EditPlan(operations=session.plan)),
                                      reply_markup=_template_picker(job_id, template_id))
        return
    template_preview = re.fullmatch(r"video_editor:tp:([a-f0-9]{32}):(\d+)", data)
    if template_preview:
        job_id, template_index = template_preview.groups()
        if int(template_index) >= len(TEMPLATE_IDS):
            await query.message.reply_text("القالب غير متاح.")
            return
        template_id = TEMPLATE_IDS[int(template_index)]
        session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
        if not session:
            await query.message.reply_text("انتهت الجلسة أو لا تملك صلاحية الوصول إليها.")
            return
        try:
            template = get_template(template_id)
            await _queue_preview(update, context, session, template["operations"])
        except (ValueError, MediaEngineError) as exc:
            await query.message.reply_text(f"⚠️ تعذرت المعاينة: {str(exc)[:250]}")
        return
    audio_video_apply = re.fullmatch(r"video_editor:av:([a-f0-9]{32}):(m|r|ml|rl)", data)
    if audio_video_apply:
        job_id, mode_code = audio_video_apply.groups()
        mode = {"m": "mix", "r": "replace", "ml": "mix_loop", "rl": "replace_loop"}[mode_code]
        session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
        if not session:
            await query.message.reply_text("انتهت الجلسة أو لا تملك صلاحية الوصول إليها.")
            return
        videos = [m for m in session.media if m.kind in ("video", "video_document")]
        if len(videos) < 2:
            await query.message.reply_text("أرسل فيديو مصدرًا للصوت أولًا.")
            return
        normalized_mode = mode.removesuffix("_loop")
        session.plan = [{"type": "mix_audio" if normalized_mode == "mix" else "replace_audio",
                         "source_video_index": 2, "volume": 0.35, "repeat": mode.endswith("_loop")}]
        session.prompt = "source-video-audio"
        await media_sessions.set_state(job_id, session.user_id, SessionState.WAITING_FOR_CONFIRMATION)
        label = "مزج الصوت المستخرج" if mode == "mix" else "استبدال الصوت الأصلي"
        await query.message.reply_text(f"🎵 تأكيد {label} باستخدام الصوت من الفيديو الثاني.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ تطبيق", callback_data=f"{CALLBACK_PREFIX}confirm:{job_id}")], [InlineKeyboardButton("⬅️ لوحة التحكم", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")]]))
        return
    text_style = re.fullmatch(r"video_editor:tx:([a-f0-9]{32}):(t|c|b):(\d+):(0|1)", data)
    if text_style:
        job_id, position_code, size, background = text_style.groups()
        position = {"t": "top", "c": "center", "b": "bottom"}[position_code]
        session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
        text_value = context.user_data.pop("video_editor_text_value", "")
        if not session or not text_value:
            await query.message.reply_text("انتهت خطوة النص؛ أعد اختيار إضافة نص.")
            return
        session.plan = [{"type": "text_overlay", "text": text_value, "position": position,
                         "fontsize": int(size), "box": background == "1"}]
        await media_sessions.set_state(job_id, session.user_id, SessionState.WAITING_FOR_CONFIRMATION)
        await query.message.reply_text("📝 إعداد النص جاهز للتطبيق.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ تطبيق النص", callback_data=f"{CALLBACK_PREFIX}confirm:{job_id}")], [InlineKeyboardButton("⬅️ لوحة التحكم", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")]]))
        return
    suggestions = re.fullmatch(r"video_editor:suggest:([a-f0-9]{32})", data)
    if suggestions:
        job_id = suggestions.group(1)
        session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
        if not session:
            await query.message.reply_text("انتهت الجلسة أو لا تملك صلاحية الوصول إليها.")
            return
        try:
            await _download_assets(update, session, context)
            source = next(Path(item.local_path) for item in session.media if item.local_path and item.kind in ("video", "video_document"))
            meta = await MediaEngine().probe_media(source)
            stream = next(item for item in meta["streams"] if item.get("codec_type") == "video")
            width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
            duration = float(meta.get("format", {}).get("duration", 0))
            vertical = height > width
            choices = ["viral_short", "fast_hook"] if vertical or duration < 60 else ["cinematic_trailer", "film_story"]
            if any(item.get("codec_type") == "audio" for item in meta["streams"]):
                choices.append("music_montage")
            reason = f"اقتراح محلي مبني على مدة {duration:.0f} ثانية ونسبة {width}:{height}"
            rows = [[InlineKeyboardButton(get_template(template_id)["name"], callback_data=f"{CALLBACK_PREFIX}t:{job_id}:{TEMPLATE_IDS.index(template_id)}")] for template_id in choices]
            rows.append([InlineKeyboardButton("⬅️ لوحة التحكم", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")])
            await query.message.reply_text("🧠 قوالب مقترحة\n" + reason + ". لا يجري تحليل محتوى المشاهد.", reply_markup=InlineKeyboardMarkup(rows))
        except Exception as exc:
            await query.message.reply_text(f"تعذر فحص خصائص الفيديو محليًا: {str(exc)[:200]}")
        return
    if data == f"{CALLBACK_PREFIX}start":
        session = await _new_session(update, context)
        await query.message.reply_text(f"📥 أرسل فيديو أو صوتًا أو صورة. رقم الجلسة: {session.job_id[:8]}\nيمكنك إرسال عدة ملفات، ثم اضغط «انتهيت».", reply_markup=_cancel_keyboard(session.job_id))
        return
    replace_video = re.fullmatch(r"video_editor:replace_video:([a-f0-9]{32})", data)
    if replace_video:
        old_job_id = replace_video.group(1)
        old_session = await media_sessions.get(old_job_id, update.effective_user.id, update.effective_chat.id)
        pending = context.user_data.pop("video_editor_pending_replacement", None)
        if not old_session or not pending or pending.get("job_id") != old_job_id:
            await query.message.reply_text("انتهت خطوة الاستبدال؛ أعد إرسال الفيديو من داخل الجلسة.")
            return
        await media_sessions.set_state(old_job_id, old_session.user_id, SessionState.CANCELLED)
        await media_sessions.remove(old_job_id, old_session.user_id)
        context.user_data.pop("video_editor_job", None)
        session = await _new_session(update, context)
        item = await media_sessions.add_media(session.job_id, session.user_id, session.chat_id,
                                              file_id=pending["file_id"], kind="video_document" if pending.get("mime_type", "").startswith("video/") and not pending.get("filename", "").endswith(".mp4") else "video",
                                              filename=pending["filename"], file_size=pending.get("file_size"),
                                              mime_type=pending.get("mime_type"))
        if not item:
            await query.message.reply_text("تعذر إنشاء جلسة الفيديو البديل؛ أرسل الفيديو مرة أخرى.")
            return
        await _prepare_primary_video(update, context, session, item, query.message)
        return
    keep_video = re.fullmatch(r"video_editor:keep_video:([a-f0-9]{32})", data)
    if keep_video:
        job_id = keep_video.group(1)
        session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
        pending = context.user_data.get("video_editor_pending_replacement")
        if pending and pending.get("job_id") == job_id:
            context.user_data.pop("video_editor_pending_replacement", None)
        if session:
            await query.message.reply_text("✅ بقي الفيديو الحالي كما هو.", reply_markup=_control_keyboard(job_id, session.lara_intro))
        return
    simple = re.fullmatch(r"video_editor:(panel|prompt|extract|addvideo|merge_video|audio_video_source|preview|intro|save|end|undo|redo):([a-f0-9]{32})", data)
    if simple:
        action, job_id = simple.groups()
        session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
        if not session:
            await query.message.reply_text("انتهت الجلسة أو لا تملك صلاحية الوصول إليها.")
            return
        if session.state == SessionState.PROCESSING:
            await query.answer("⏳ يتم الآن معالجة الفيديو...", show_alert=True)
            return
        if action == "panel":
            await query.message.reply_text("🎬 Lara Video Studio", reply_markup=_control_keyboard(job_id, session.lara_intro))
        elif action == "prompt":
            await media_sessions.set_state(job_id, session.user_id, SessionState.WAITING_FOR_INSTRUCTIONS)
            await query.message.reply_text("✍️ اكتب ماذا تريد تعديله. أمثلة: قص أول 5 ثواني، زود الإضاءة، أو حوله إلى 9:16.")
        elif action == "addvideo":
            await media_sessions.set_state(job_id, session.user_id, SessionState.RECEIVING_MEDIA)
            await query.message.reply_text("🎬 أرسل الفيديو الإضافي لدمجه أو لاستخدام صوته.")
        elif action == "merge_video":
            context.user_data["video_editor_merge_pending"] = True
            await media_sessions.set_state(job_id, session.user_id, SessionState.WAITING_MERGE_VIDEO)
            await query.message.reply_text("🎬 أرسل الفيديو الثاني لدمجه بالتسلسل مع الفيديو الحالي.")
        elif action == "audio_video_source":
            context.user_data["video_editor_audio_video_pending"] = True
            await media_sessions.set_state(job_id, session.user_id, SessionState.WAITING_AUDIO_VIDEO)
            await query.message.reply_text("📹 أرسل فيديو لاستخراج مساره الصوتي؛ سيبقى الفيديو الأساسي كما هو.")
        elif action == "preview":
            await _queue_preview(update, context, session)
        elif action == "intro":
            session.lara_intro = not session.lara_intro
            await query.message.reply_text("🏷️ مقدمة Lara " + ("مفعّلة وستضاف قبل الفيديو عند الحفظ." if session.lara_intro else "متوقفة ولن تغيّر الفيديو عند الحفظ."), reply_markup=_control_keyboard(job_id, session.lara_intro))
        elif action in ("undo", "redo"):
            cursor = session.history_cursor + (-1 if action == "undo" else 1)
            if not session.history or not 0 <= cursor < len(session.history):
                await query.message.reply_text("لا توجد نسخة سابقة/تالية في سجل الجلسة.", reply_markup=_control_keyboard(job_id, session.lara_intro))
            else:
                session.history_cursor = cursor
                session.result_path = session.history[cursor]
                await media_sessions.set_state(job_id, session.user_id, SessionState.READY)
                await query.message.reply_text("✅ تم تحديث نسخة العمل من سجل التعديلات.", reply_markup=_control_keyboard(job_id, session.lara_intro))
        elif action == "extract":
            session.plan = [{"type": "extract_audio"}]
            await media_sessions.set_state(job_id, session.user_id, SessionState.WAITING_FOR_CONFIRMATION)
            await query.message.reply_text("🎵 استخراج الصوت من الفيديو الحالي.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ استخراج الآن", callback_data=f"{CALLBACK_PREFIX}confirm:{job_id}")]]))
        elif action == "save":
            status = await query.message.reply_text("⏳ أُضيف التصدير النهائي إلى طابور المعالجة…")
            await media_sessions.set_state(job_id, session.user_id, SessionState.PROCESSING)
            save_job_id = f"{job_id}_save_{uuid.uuid4().hex[:8]}"
            async def save_processor() -> None:
                temporary: list[Path] = []
                try:
                    await _download_assets(update, session, context)
                    source = Path(session.result_path) if session.result_path else next(
                        Path(m.local_path) for m in session.media if m.local_path and m.kind in ("video", "video_document"))
                    engine = MediaEngine(timeout_seconds=int(os.getenv("LARA_FFMPEG_TIMEOUT", "1800")))
                    export_source = source
                    if session.lara_intro:
                        branded = session.job_dir / "output" / f"lara_branded_{uuid.uuid4().hex}.mp4"
                        temporary.append(branded)
                        await engine.create_lara_intro(export_source, branded)
                        export_source = branded
                    final = session.job_dir / "output" / f"export_{uuid.uuid4().hex}.mp4"
                    temporary.append(final)
                    await engine.apply(export_source, final, {"type": "export", "profile": session.export_profile})
                    if final.stat().st_size > MAX_OUTPUT_BYTES:
                        raise MediaEngineError("الناتج تجاوز حد الإرسال؛ اختر ملفًا أصغر أو خفّض الجودة.")
                    with final.open("rb") as output:
                        await context.bot.send_video(chat_id=session.chat_id, video=output,
                                                     caption="💾 الفيديو النهائي — Lara Video Studio")
                    await media_sessions.set_state(job_id, session.user_id, SessionState.COMPLETED)
                    session.task = None
                    await media_sessions.remove(job_id, session.user_id)
                    context.user_data.pop("video_editor_job", None)
                    await context.bot.edit_message_text("✅ تم الحفظ والإرسال وتنظيف ملفات الجلسة.",
                                                        chat_id=session.chat_id, message_id=status.message_id)
                except Exception as exc:
                    await media_sessions.set_state(job_id, session.user_id, SessionState.READY)
                    await context.bot.edit_message_text(f"⚠️ تعذر التصدير أو الإرسال. نسخة العمل محفوظة: {str(exc)[:250]}",
                                                        chat_id=session.chat_id, message_id=status.message_id,
                                                        reply_markup=_control_keyboard(job_id, session.lara_intro))
                    for path in temporary:
                        path.unlink(missing_ok=True)
                finally:
                    session.task = None
            try:
                record = await video_jobs.submit(save_job_id, save_processor)
                session.task = record.task
            except Exception as exc:
                await media_sessions.set_state(job_id, session.user_id, SessionState.READY)
                await query.message.reply_text(f"تعذر إدراج التصدير في الطابور: {str(exc)[:180]}", reply_markup=_control_keyboard(job_id, session.lara_intro))
        elif action == "end":
            if session.operation_count:
                rows = [[InlineKeyboardButton("💾 حفظ وإرسال", callback_data=f"{CALLBACK_PREFIX}save:{job_id}")],
                        [InlineKeyboardButton("🗑️ إنهاء وحذف", callback_data=f"{CALLBACK_PREFIX}cancel:{job_id}")],
                        [InlineKeyboardButton("↩️ متابعة التحرير", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")]]
                prompt = "⚠️ لديك تعديلات غير محفوظة. ماذا تريد أن تفعل؟"
            else:
                rows = [[InlineKeyboardButton("✅ نعم، أنهِ الجلسة", callback_data=f"{CALLBACK_PREFIX}cancel:{job_id}")],
                        [InlineKeyboardButton("↩️ متابعة التحرير", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")]]
                prompt = "هل تريد إنهاء الجلسة وحذف ملفات العمل؟"
            await query.message.reply_text(prompt, reply_markup=InlineKeyboardMarkup(rows))
        return
    audio_mode = re.fullmatch(r"video_editor:am:([a-f0-9]{32}):(m|r|ml|rl)", data)
    if audio_mode:
        job_id, mode_code = audio_mode.groups()
        mode = {"m": "mix", "r": "replace", "ml": "mix_loop", "rl": "replace_loop"}[mode_code]
        session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
        if not session:
            await query.message.reply_text("انتهت الجلسة أو لا تملك صلاحية الوصول إليها.")
            return
        context.user_data["video_editor_audio_mode"] = mode
        await media_sessions.set_state(job_id, session.user_id, SessionState.WAITING_AUDIO)
        await query.message.reply_text("🎵 أرسل ملف الصوت. سيُ" + ("مزج مع الصوت الأصلي" if mode == "mix" else "ستبدل به المسار الصوتي الأصلي") + ".")
        return
    tool = re.fullmatch(r"video_editor:op:([a-f0-9]{32}):([a-z]+):(\d+)", data)
    if tool:
        job_id, category_code, index_text = tool.groups()
        category = CATEGORY_FROM_CODE.get(category_code)
        if not category:
            return
        session = await media_sessions.get(job_id, update.effective_user.id, update.effective_chat.id)
        if not session:
            await query.message.reply_text("انتهت الجلسة أو لا تملك صلاحية الوصول إليها.")
            return
        index = int(index_text)
        if index >= len(TOOL_REQUESTS[category]):
            return
        if category == "export":
            profiles = ("high", "balanced", "small", "telegram")
            session.export_profile = profiles[index]
            await query.message.reply_text(f"📤 تم ضبط ملف التصدير على {profiles[index]}.", reply_markup=_control_keyboard(job_id, session.lara_intro))
            return
        if category == "dimensions" and index == 5:
            session.export_profile = "telegram"
            await query.message.reply_text("✈️ تم اختيار تصدير Telegram H.264/AAC محسّن؛ ستحافظ أبعاد الفيديو على نسبتها عند الحفظ.", reply_markup=_control_keyboard(job_id, session.lara_intro))
            return
        request = TOOL_REQUESTS[category][index]
        if request.startswith("أرسل نص"):
            context.user_data["video_editor_pending_text"] = "watermark" if "العلامة" in request else "text"
            await media_sessions.set_state(job_id, session.user_id, SessionState.WAITING_TEXT)
            await query.message.reply_text("📝 أرسل النص الذي تريد وضعه على الفيديو.")
            return
        session.prompt = request
        plan = parse_edit_request(request, session.media)
        session.plan = plan.operations
        session.clarification = plan.clarification
        if not plan.ready:
            if (category == "advanced" and index in (0, 2)) or (category == "audio" and index == 4):
                await media_sessions.set_state(job_id, session.user_id, SessionState.RECEIVING_MEDIA)
            await query.message.reply_text("❓ " + (plan.clarification or "أرسل الوسيط المطلوب ثم أعد المحاولة."), reply_markup=_control_keyboard(job_id, session.lara_intro))
            return
        await media_sessions.set_state(job_id, session.user_id, SessionState.WAITING_FOR_CONFIRMATION)
        await query.message.reply_text(await _describe_plan(plan), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ تطبيق", callback_data=f"{CALLBACK_PREFIX}confirm:{job_id}")], [InlineKeyboardButton("⬅️ لوحة التحكم", callback_data=f"{CALLBACK_PREFIX}panel:{job_id}")]]))
        return
    match = re.fullmatch(r"video_editor:(finish|confirm|edit|cancel):([a-f0-9]{32})", data)
    if not match:
        return
    action, job_id = match.groups()
    user_id, chat_id = update.effective_user.id, update.effective_chat.id
    session = await media_sessions.get(job_id, user_id, chat_id)
    if not session:
        await query.message.reply_text("انتهت الجلسة أو لا تملك صلاحية الوصول إليها. ابدأ جلسة جديدة.")
        return
    if action == "finish":
        if not session.media:
            await query.message.reply_text("أرسل وسيطًا واحدًا على الأقل أولًا.")
            return
        await media_sessions.set_state(job_id, user_id, SessionState.WAITING_FOR_INSTRUCTIONS)
        await query.message.reply_text("اكتب الآن ما تريد تعديله بلغة طبيعية.\nمثال: قصلي أول دقيقة، شيل الصوت، وخليه عمودي.")
    elif action == "edit":
        await media_sessions.set_state(job_id, user_id, SessionState.WAITING_FOR_INSTRUCTIONS)
        session.clarification = None
        await query.message.reply_text("اكتب الطلب المعدّل. أرسل طلبًا كاملًا جديدًا.")
    elif action == "cancel":
        record = await video_jobs.get(job_id)
        if record and record.state in (JobState.QUEUED, JobState.PROCESSING):
            await video_jobs.cancel(job_id)
        await media_sessions.set_state(job_id, user_id, SessionState.CANCELLED)
        await media_sessions.remove(job_id, user_id)
        context.user_data.pop("video_editor_job", None)
        await query.message.reply_text("❌ أُلغيت الجلسة ونُظفت ملفاتها المؤقتة.")
    elif action == "confirm":
        if session.state != SessionState.WAITING_FOR_CONFIRMATION:
            await query.message.reply_text("هذه الخطة لم تعد جاهزة للتنفيذ. أرسل الطلب من جديد.")
            return
        status = await query.message.reply_text("⏳ أُضيفت المهمة إلى طابور المعالجة…")
        await media_sessions.set_state(job_id, user_id, SessionState.PROCESSING)
        async def processor():
            await _execute(update, context, session, status.message_id)
        try:
            record = await video_jobs.submit(job_id, processor)
        except Exception as exc:
            await media_sessions.set_state(job_id, user_id, SessionState.WAITING_FOR_CONFIRMATION)
            await query.message.reply_text(f"تعذر إضافة المهمة للطابور: {exc}")
            return
        session.task = record.task
        await query.message.reply_text(f"حالة المهمة: {record.state.value}. الحد الأقصى للمعالجة المتوازية: {video_jobs.limit}.")


EDITOR_MEDIA_FILTER = (filters.VIDEO | filters.PHOTO | filters.AUDIO | filters.VOICE |
                       filters.Document.ALL)


async def _session_cleanup_loop() -> None:
    while True:
        await media_sessions.cleanup_expired()
        await asyncio.sleep(300)


async def video_editor_post_init(application) -> None:
    application.bot_data["video_editor_cleanup_task"] = asyncio.create_task(
        _session_cleanup_loop(), name="video-editor-session-cleanup"
    )


async def video_editor_post_shutdown(application) -> None:
    task = application.bot_data.pop("video_editor_cleanup_task", None)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
