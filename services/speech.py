"""Local, bounded Arabic speech synthesis for Lara."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
import urllib.request
import wave
from pathlib import Path
from typing import Any

MAX_SPEECH_CHARS = 800
MODEL_REPOSITORY = "vadimbelsky/arabic-emirati-female-piper"
MODEL_REVISION = "f89f1aec8e6486871ffdf8d878c5a39eaf918d60"
MODEL_FILENAME = "arabic-emirati-female-model.onnx"
MODEL_SHA256 = "1578a9b27d01a0626227225b148179628b770607dd61bdbbc41865bd399106b1"
CONFIG_SHA256 = "fe31710d91b1d3f7022cc2396d34ad8e2d22cd424cd861409f8c916b86f35049"
MODEL_URL = f"https://huggingface.co/{MODEL_REPOSITORY}/resolve/{MODEL_REVISION}/{MODEL_FILENAME}"
CONFIG_URL = f"https://huggingface.co/{MODEL_REPOSITORY}/resolve/{MODEL_REVISION}/{MODEL_FILENAME}.json"
MODEL_MAX_BYTES = 70 * 1024 * 1024
MODEL_EXPECTED_BYTES = 63_516_686
DOWNLOAD_TIMEOUT_SECONDS = 120
SYNTHESIS_TIMEOUT_SECONDS = 30
_TTS_SLOT = threading.BoundedSemaphore(1)
_MODEL_LOCK = threading.Lock()
_VOICE: Any = None
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


def _cache_directory() -> Path:
    configured = os.getenv("LARA_TTS_MODEL_DIR")
    if configured:
        return Path(configured).expanduser()
    cache_root = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_root / "lara" / "piper-ar-emirati-female"


def _download_file(url: str, destination: Path, *, checksum: str | None = None) -> None:
    """Download a bounded, verified model asset atomically (never per request)."""
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT_SECONDS
    temp_path = destination.with_suffix(destination.suffix + f".{os.getpid()}.{threading.get_ident()}.part")
    digest = hashlib.sha256()
    size = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "LaraBot-local-TTS/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response, temp_path.open("wb") as output:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("TTS model download timed out")
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MODEL_MAX_BYTES:
                    raise ValueError("TTS model asset exceeds its size limit")
                output.write(chunk)
                digest.update(chunk)
        if checksum and digest.hexdigest() != checksum:
            raise ValueError("TTS model checksum mismatch")
        if destination.name == MODEL_FILENAME and size != MODEL_EXPECTED_BYTES:
            raise ValueError("TTS model size mismatch")
        if not size:
            raise ValueError("TTS model asset is empty")
        temp_path.replace(destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _ensure_model_files() -> tuple[Path, Path]:
    directory = _cache_directory()
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / MODEL_FILENAME
    config_path = directory / f"{MODEL_FILENAME}.json"
    if not model_path.exists() or _file_sha256(model_path) != MODEL_SHA256:
        _download_file(MODEL_URL, model_path, checksum=MODEL_SHA256)
    if not config_path.exists() or _file_sha256(config_path) != CONFIG_SHA256:
        _download_file(CONFIG_URL, config_path, checksum=CONFIG_SHA256)
    with config_path.open("r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    if config.get("audio", {}).get("sample_rate") != 22050 or config.get("espeak", {}).get("voice") != "ar":
        raise ValueError("Unexpected Arabic Piper voice configuration")
    return model_path, config_path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _get_voice():
    global _VOICE
    if _VOICE is not None:
        return _VOICE
    with _MODEL_LOCK:
        if _VOICE is None:
            from piper import PiperVoice
            from piper.config import PiperConfig
            import onnxruntime

            model_path, config_path = _ensure_model_files()
            with config_path.open("r", encoding="utf-8") as config_file:
                config = PiperConfig.from_dict(json.load(config_file))
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
            session = onnxruntime.InferenceSession(
                str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )
            _VOICE = PiperVoice(session=session, config=config, download_dir=model_path.parent)
            # Avoid adding uncertain vowels to colloquial user text and avoid a second ONNX model.
            _VOICE.use_tashkeel = False
    return _VOICE


def _ffmpeg_binary() -> str:
    configured = os.getenv("FFMPEG_BINARY")
    if configured and Path(configured).is_file():
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    from static_ffmpeg import run

    return run.get_or_fetch_platform_executables_else_raise()[0]


def _segments(text: str) -> list[tuple[str, str]]:
    parts = re.split(r"\s*([،,؛;.!?؟\n]+)\s*", text)
    result: list[tuple[str, str]] = []
    phrase = parts[0].strip() if parts else ""
    for index in range(1, len(parts), 2):
        mark = parts[index]
        if phrase:
            result.append((phrase + mark, mark))
        phrase = parts[index + 1].strip() if index + 1 < len(parts) else ""
    if phrase:
        result.append((phrase, ""))
    return result


def _pause_seconds(mark: str, category: str) -> float:
    if "؟" in mark or "?" in mark:
        return 0.20
    if "!" in mark:
        return 0.18
    if any(char in mark for char in "،,؛;\n"):
        return 0.12
    if "." in mark:
        return 0.20 if category in {"question", "exclamation"} else 0.17
    return 0.0


def _write_wav(voice, text: str, path: Path, *, prosody_text: str | None = None) -> None:
    chunks = _segments(text) or [(text, "")]
    sample_rate = int(voice.config.sample_rate)
    category = classify_prosody(prosody_text if prosody_text is not None else text)
    from piper.config import SynthesisConfig

    config = {
        "warm": SynthesisConfig(length_scale=1.02, noise_w_scale=0.76),
        "playful": SynthesisConfig(length_scale=0.98, noise_w_scale=0.84),
        "question": SynthesisConfig(noise_w_scale=0.82),
        "exclamation": SynthesisConfig(noise_w_scale=0.84),
    }.get(category)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        for index, (phrase, mark) in enumerate(chunks):
            voice.synthesize_wav(phrase, output, syn_config=config, set_wav_format=False)
            pause = _pause_seconds(mark, category)
            if index < len(chunks) - 1 and pause:
                output.writeframes(b"\0\0" * int(sample_rate * pause))


def _convert_to_telegram_voice(wav_path: Path, ogg_path: Path) -> None:
    command = [
        _ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-i", str(wav_path),
        "-af", "silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.08:"
              "stop_periods=1:stop_threshold=-48dB:stop_silence=0.18,loudnorm=I=-18:TP=-2:LRA=9",
        "-ar", "24000", "-ac", "1", "-c:a", "libopus", "-b:a", "32k", "-application", "voip",
        str(ogg_path),
    ]
    subprocess.run(command, check=True, timeout=15, capture_output=True)
    if not ogg_path.is_file() or ogg_path.stat().st_size < 64:
        raise RuntimeError("FFmpeg did not produce a valid voice file")


def generate_speech_file(text: str) -> Path:
    """Generate a local Piper speech file, serializing CPU inference per process."""
    if len(text) > MAX_SPEECH_CHARS:
        raise ValueError("speech text is too long")
    prepared = prepare_speech_text(text)
    if not prepared:
        raise ValueError("empty speech text")
    if len(prepared) > MAX_SPEECH_CHARS:
        raise ValueError("speech text is too long")
    if not _TTS_SLOT.acquire(timeout=2):
        raise TimeoutError("speech service is busy")
    wav_path = ogg_path = None
    try:
        started = time.monotonic()
        voice = _get_voice()
        with tempfile.NamedTemporaryFile(prefix="lara-tts-", suffix=".wav", delete=False) as file:
            wav_path = Path(file.name)
        with tempfile.NamedTemporaryFile(prefix="lara-tts-", suffix=".ogg", delete=False) as file:
            ogg_path = Path(file.name)
        _write_wav(voice, prepared, wav_path, prosody_text=text)
        if time.monotonic() - started > SYNTHESIS_TIMEOUT_SECONDS:
            raise TimeoutError("speech synthesis timed out")
        _convert_to_telegram_voice(wav_path, ogg_path)
        wav_path.unlink(missing_ok=True)
        return ogg_path
    except Exception:
        if wav_path:
            wav_path.unlink(missing_ok=True)
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
