"""Telegram UI and orchestration for the isolated natural-language editor."""
from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes, filters

from services.intent import EditPlan, parse_natural_request
from services.media_sessions import MediaSession, SessionState, media_sessions
from services.video_engine import MediaEngine, MediaEngineError
from services.video_jobs import JobState, video_jobs

CALLBACK_PREFIX = "video_editor:"
MAX_DOWNLOAD_BYTES = int(os.getenv("LARA_TELEGRAM_DOWNLOAD_MAX_BYTES", str(20 * 1024 * 1024)))
MAX_OUTPUT_BYTES = int(os.getenv("LARA_TELEGRAM_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))
MAX_SESSION_BYTES = int(os.getenv("LARA_VIDEO_SESSION_MAX_BYTES", str(80 * 1024 * 1024)))
MAX_SESSION_ITEMS = 8

GUIDE = (
    "أرسل فيديو أو عدة وسائط على مراحل، ثم اكتب طلبك بالعربية الطبيعية.\n\n"
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
    "effects": ("المؤثرات", "تلاشي وضبط السطوع والتباين والتشبع والتمويه والحدة."),
    "advanced": ("متقدم", "تجميع عدة عمليات بخطة واحدة ومعاينة قبل التنفيذ."),
    "ai": ("AI Editor", "صف التعديلات بلغتك الطبيعية؛ يراجع المحرر الخطة قبل تشغيل FFmpeg."),
}


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


async def _execute(update: Update, context: ContextTypes.DEFAULT_TYPE, session: MediaSession, status_message_id: int) -> None:
    await media_sessions.set_state(session.job_id, session.user_id, SessionState.PROCESSING)
    engine = MediaEngine(timeout_seconds=int(os.getenv("LARA_FFMPEG_TIMEOUT", "1800")))
    try:
        await _download_assets(update, session, context)
        videos = [Path(session.media[i].local_path) for i in range(len(session.media))
                  if session.media[i].kind in ("video", "video_document")]
        audios = [Path(m.local_path) for m in session.media
                  if m.local_path and m.kind in ("audio", "audio_document", "voice")]
        if not videos and not audios:
            raise MediaEngineError("أرسل فيديو أو ملفًا صوتيًا واحدًا على الأقل.")
        audio_only = not videos
        current = videos[0] if videos else audios[0]
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
            target = session.job_dir / "temp" / f"step_{step:03d}_{op['type']}{'.m4a' if audio_op else '.mp4'}"
            if op["type"] == "concat_videos":
                current = await engine.concat_videos(videos, target, progress=report_progress)
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
        # Move/copy final output within this job only.
        video_result = bool(videos and any(op["type"] != "extract_audio" for op in session.plan))
        final_path = session.job_dir / "output" / ("final.m4a" if audio_only else "final.mp4")
        if video_result or audio_only:
            if current != final_path:
                import shutil
                shutil.copy2(current, final_path)
        if ((video_result or audio_only) and final_path.stat().st_size > MAX_OUTPUT_BYTES) or any(p.stat().st_size > MAX_OUTPUT_BYTES for p in extracted_audio):
            raise MediaEngineError(f"الناتج أكبر من حد الإرسال المضبوط ({MAX_OUTPUT_BYTES // (1024*1024)} MB). أعد الطلب مع ضغط الفيديو.")
        await context.bot.edit_message_text("✅ اكتملت المعالجة، جارٍ إرسال النتيجة…", chat_id=session.chat_id, message_id=status_message_id)
        if video_result or audio_only:
            with final_path.open("rb") as output:
                if audio_only:
                    await context.bot.send_audio(chat_id=session.chat_id, audio=output,
                                                 title="Lara edited audio", caption=f"✅ اكتمل التعديل ({session.job_id[:8]}).")
                else:
                    await context.bot.send_video(chat_id=session.chat_id, video=output,
                                                 caption=f"✅ اكتمل التعديل (المهمة {session.job_id[:8]}).")
        for audio_path in extracted_audio:
            with audio_path.open("rb") as output:
                await context.bot.send_audio(chat_id=session.chat_id, audio=output, title="Extracted audio")
        session.result_path = str(final_path)
        await media_sessions.set_state(session.job_id, session.user_id, SessionState.COMPLETED)
        # Outputs and inputs belong only to this job, so they can be removed after delivery.
        session.task = None
        await media_sessions.remove(session.job_id, session.user_id)
        context.user_data.pop("video_editor_job", None)
    except Exception as exc:
        await media_sessions.set_state(session.job_id, session.user_id, SessionState.FAILED)
        try:
            await context.bot.edit_message_text(f"❌ تعذر تنفيذ الخطة: {str(exc)[:700]}", chat_id=session.chat_id, message_id=status_message_id)
        except Exception:
            pass
        raise


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
    if session.state not in (SessionState.RECEIVING_MEDIA, SessionState.WAITING_FOR_INSTRUCTIONS):
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
        await message.reply_text(f"📥 أُضيف الوسيط رقم {item.index} ({kind}). أرسل وسائط أخرى أو اضغط «انتهيت» ثم اكتب طلبك.",
                                 reply_markup=_cancel_keyboard(job_id))
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
        await message.reply_text("الخطة جاهزة. اضغط «تنفيذ» أو «تعديل الطلب» قبل إرسال وصف آخر.")
        raise ApplicationHandlerStop
    if session.state == SessionState.PROCESSING:
        await message.reply_text("المهمة قيد المعالجة. أرسل طلبًا جديدًا بعد اكتمالها.")
        raise ApplicationHandlerStop
    if session.state != SessionState.WAITING_FOR_INSTRUCTIONS:
        return
    session.prompt = (session.prompt + " " + message.text).strip() if session.clarification else message.text.strip()
    plan = await parse_natural_request(session.prompt, session.media)
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
                                    [InlineKeyboardButton("❌ إلغاء", callback_data=f"{CALLBACK_PREFIX}cancel:{job_id}")]])
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
        category = data.split(":", 2)[-1]
        title, description = CATEGORIES.get(category, CATEGORIES["advanced"])
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📖 شرح", callback_data=f"{CALLBACK_PREFIX}guide")],
                                   [InlineKeyboardButton("▶️ تنفيذ / AI Editor", callback_data=f"{CALLBACK_PREFIX}start")],
                                   [InlineKeyboardButton("↩️ رجوع", callback_data=f"{CALLBACK_PREFIX}open")]])
        await query.message.reply_text(f"{title}\n\n{description}\n\nأرسل الوسائط ثم اكتب طلبك بالعربية الطبيعية.", reply_markup=kb)
        return
    if data == f"{CALLBACK_PREFIX}start":
        session = await _new_session(update, context)
        await query.message.reply_text(f"📥 أرسل فيديو أو صوتًا أو صورة. رقم الجلسة: {session.job_id[:8]}\nيمكنك إرسال عدة ملفات، ثم اضغط «انتهيت».", reply_markup=_cancel_keyboard(session.job_id))
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
        async def processor():
            await _execute(update, context, session, status.message_id)
        try:
            record = await video_jobs.submit(job_id, processor)
        except Exception as exc:
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
