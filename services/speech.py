"""Local, bounded Arabic speech synthesis for Lara."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

MAX_SPEECH_CHARS = 800
SYNTHESIS_TIMEOUT_SECONDS = 30
_TTS_SLOT = threading.BoundedSemaphore(1)
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def prepare_speech_text(text: str) -> str:
    """Normalize the private spoken copy; keep the user's message untouched."""
    text = unicodedata.normalize("NFKC", text).translate(_ARABIC_DIGITS).replace("٪", "%")
    # Keep common laughter markers long enough to sound intentional.
    playful = bool(re.search(r"(?:😂|🤣|هههه|هاها|مزح|نكتة)", text, re.I))
    text = "".join(ch for ch in text if unicodedata.category(ch) not in {"So", "Sk"})
    text = re.sub(r"[\uFE0E\uFE0F\u200D]", "", text)
    text = re.sub(r"([!?؟،,.؛:])\1+", r"\1", text)
    text = re.sub(r"([\u0600-\u06FF])\1{2,}", r"\1\1", text)
    text = re.sub(r"([A-Za-z])\1{3,}", r"\1\1", text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r" *\n+ *", "، ", text)
    text = re.sub(r"\s+([،؛,.!?؟:])", r"\1", text)
    text = re.sub(r"([،؛,.!?؟:])(?=\S)", r"\1 ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*%", r"\1 بالمئة", text)
    text = re.sub(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*\$", r"\1 دولار", text)
    text = re.sub(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*€", r"\1 يورو", text)
    text = re.sub(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*£", r"\1 جنيه", text)
    text = text.replace("&", " و ").replace("@", " آت ")
    if playful:
        # The emoji itself is omitted, while common written laughter remains speakable.
        text = re.sub(r"ه{3,}", "هه", text)
    return re.sub(r"\s+", " ", text).strip()


def classify_prosody(text: str) -> str:
    """Deterministic punctuation and keyword classification for pause timing."""
    if re.search(r"[؟?]", text):
        return "question"
    if re.search(r"[!！]", text):
        return "exclamation"
    if re.search(r"(?:😂|🤣|هههه|هاها|نكتة|مزح)", text, re.I):
        return "playful"
    if re.search(r"(?:بحبك|أحبك|بحبّك|اشتقتلك|يا قلبي|حبيبي|حبيبتي)", text):
        return "warm"
    if len(text) > 180 or text.count("،") + text.count(",") >= 3:
        return "long"
    if len(text) <= 18:
        return "short"
    return "neutral"


EDGE_VOICE = "ar-EG-SalmaNeural"
SYNTHESIS_TIMEOUT_SECONDS = 30
_TTS_SLOT = threading.BoundedSemaphore(1)


def _ffmpeg_binary() -> str:
    configured = os.getenv("FFMPEG_BINARY")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    from static_ffmpeg import run
    return run.get_or_fetch_platform_executables_else_raise()[0]


def _edge_rate(category: str) -> str:
    return {
        "short": "-2%",
        "warm": "-4%",
        "playful": "+3%",
        "question": "+0%",
        "exclamation": "+2%",
        "long": "-3%",
        "neutral": "-2%",
    }.get(category, "-2%")


def _edge_pitch(category: str) -> str:
    return {
        "warm": "+1Hz",
        "playful": "+2Hz",
    }.get(category, "+0Hz")


def _synthesize_edge_tts(text: str, mp3_path: Path, category: str) -> None:
    import asyncio
    import edge_tts

    async def _save() -> None:
        communicate = edge_tts.Communicate(
            text,
            EDGE_VOICE,
            rate=_edge_rate(category),
            pitch=_edge_pitch(category),
        )
        await communicate.save(str(mp3_path))

    asyncio.run(_save())


def _convert_to_telegram_voice(mp3_path: Path, ogg_path: Path) -> None:
    command = [
        _ffmpeg_binary(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(mp3_path),
        "-af",
        "silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.08:"
        "stop_periods=1:stop_threshold=-48dB:stop_silence=0.18,"
        "loudnorm=I=-18:TP=-2:LRA=9",
        "-ar",
        "24000",
        "-ac",
        "1",
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        "-application",
        "voip",
        str(ogg_path),
    ]
    subprocess.run(command, check=True, timeout=15, capture_output=True)
    if not ogg_path.is_file() or ogg_path.stat().st_size < 64:
        raise RuntimeError("FFmpeg did not produce a valid voice file")


def generate_speech_file(text: str) -> Path:
    """Generate an Edge TTS Arabic voice file for Telegram."""
    if len(text) > MAX_SPEECH_CHARS:
        raise ValueError("speech text is too long")

    prepared = prepare_speech_text(text)
    if not prepared:
        raise ValueError("empty speech text")
    if len(prepared) > MAX_SPEECH_CHARS:
        raise ValueError("speech text is too long")

    if not _TTS_SLOT.acquire(timeout=2):
        raise TimeoutError("speech service is busy")

    mp3_path = ogg_path = None
    try:
        started = time.monotonic()
        category = classify_prosody(text)

        with tempfile.NamedTemporaryFile(
            prefix="lara-tts-", suffix=".mp3", delete=False
        ) as file:
            mp3_path = Path(file.name)

        with tempfile.NamedTemporaryFile(
            prefix="lara-tts-", suffix=".ogg", delete=False
        ) as file:
            ogg_path = Path(file.name)

        _synthesize_edge_tts(prepared, mp3_path, category)

        if not mp3_path.is_file() or mp3_path.stat().st_size < 64:
            raise RuntimeError("Edge TTS did not produce a valid audio file")

        if time.monotonic() - started > SYNTHESIS_TIMEOUT_SECONDS:
            raise TimeoutError("speech synthesis timed out")

        _convert_to_telegram_voice(mp3_path, ogg_path)
        mp3_path.unlink(missing_ok=True)
        return ogg_path

    except Exception:
        if mp3_path:
            mp3_path.unlink(missing_ok=True)
        if ogg_path:
            ogg_path.unlink(missing_ok=True)
        raise
    finally:
        _TTS_SLOT.release()


async def generate_and_send_voice(bot, *, chat_id: int, reply_to_message_id: int, text: str) -> None:
    """Generate off-loop, send using Telegram's current voice path, always clean up."""
    worker = asyncio.create_task(asyncio.to_thread(generate_speech_file, text))
    path: Path | None = None
    try:
        try:
            path = await asyncio.shield(worker)
        except asyncio.CancelledError:
            try:
                path = await worker
            except Exception:
                pass
            raise
        with path.open("rb") as voice_file:
            await bot.send_voice(chat_id=chat_id, voice=voice_file, reply_to_message_id=reply_to_message_id)
    finally:
        if path:
            path.unlink(missing_ok=True)


async def send_speech_or_text_fallback(bot, message, *, chat_id: int, text: str) -> bool:
    """Keep the command useful and private when local speech generation/send fails."""
    try:
        await generate_and_send_voice(
            bot, chat_id=chat_id, reply_to_message_id=message.message_id, text=text
        )
        return True
    except Exception:
        await message.reply_text(f"🗣️ **لارا تقول:** {text}")
        return False
