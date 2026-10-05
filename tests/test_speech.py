from __future__ import annotations

import asyncio
import hashlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services import speech


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("أنا بحبك", "أنا بحبك"),
        ("  مرحباً   يا لارا  ", "مرحباً يا لارا"),
        ("كيفك؟؟؟", "كيفك؟"),
        ("حلووووو", "حلوو"),
        ("هههههههه", "هه"),
        ("السعر ٢٥٪", "السعر 25 بالمئة"),
        ("السعر 25%", "السعر 25 بالمئة"),
        ("كلفته 10$ و 4€ و 7£", "كلفته 10 دولار و 4 يورو و 7 جنيه"),
        ("hello Lara 😊", "hello Lara"),
        ("أول سطر\nثاني سطر", "أول سطر، ثاني سطر"),
        ("عربي & English @home", "عربي و English آت home"),
        ("", ""),
    ],
)
def test_prepare_speech_text(source, expected):
    assert speech.prepare_speech_text(source) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("كيفك؟", "question"),
        ("رائع!", "exclamation"),
        ("عنجد؟! شو عم تعمل 😂", "question"),
        ("أنا بحبك", "warm"),
        ("هذا نص طويل عادي", "short"),
        ("هذا، نص، فيه، فواصل، كثيرة", "long"),
    ],
)
def test_classify_prosody(text, expected):
    assert speech.classify_prosody(text) == expected


def test_generation_rejects_empty_and_long_text():
    engine = Mock()
    assert not speech.prepare_speech_text("😊")
    with pytest.raises(ValueError, match="empty"):
        speech.generate_speech_file("😊")
    with pytest.raises(ValueError, match="too long"):
        speech.generate_speech_file("ك" * (speech.MAX_SPEECH_CHARS + 1))


def test_generator_rejects_a_concurrent_request(monkeypatch):
    monkeypatch.setattr(speech._TTS_SLOT, "acquire", lambda timeout: False)
    with pytest.raises(TimeoutError, match="busy"):
        speech.generate_speech_file("مرحبا")


@pytest.mark.parametrize("fail_send", [False, True])
def test_send_always_cleans_audio_and_uses_telegram_voice(monkeypatch, tmp_path, fail_send):
    path = tmp_path / "generated.ogg"
    path.write_bytes(b"OggS audio")
    monkeypatch.setattr(speech, "generate_speech_file", lambda text: path)
    bot = SimpleNamespace(send_voice=AsyncMock(side_effect=RuntimeError("send failed") if fail_send else None))
    call = speech.generate_and_send_voice(bot, chat_id=123, reply_to_message_id=456, text="أنا بحبك")
    if fail_send:
        with pytest.raises(RuntimeError, match="send failed"):
            asyncio.run(call)
    else:
        asyncio.run(call)
        bot.send_voice.assert_awaited_once()
        args = bot.send_voice.await_args.kwargs
        assert args["chat_id"] == 123 and args["reply_to_message_id"] == 456
    assert not path.exists()


def test_local_failure_uses_existing_text_fallback(monkeypatch):
    monkeypatch.setattr(speech, "generate_and_send_voice", AsyncMock(side_effect=TimeoutError("internal")))
    message = SimpleNamespace(message_id=88, reply_text=AsyncMock())
    result = asyncio.run(speech.send_speech_or_text_fallback(
        SimpleNamespace(), message, chat_id=123, text="أنا بحبك"
    ))
    assert result is False
    message.reply_text.assert_awaited_once_with("🗣️ **لارا تقول:** أنا بحبك")


