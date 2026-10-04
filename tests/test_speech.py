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


def test_pause_duration_tracks_punctuation():
    assert speech._pause_seconds("؟", "question") > speech._pause_seconds("،", "question")
    assert speech._pause_seconds("", "neutral") == 0


def test_segments_preserve_words_and_punctuation():
    assert speech._segments("أهلًا، كيف حالك؟") == [("أهلًا،", "،"), ("كيف حالك؟", "؟")]


def test_generation_rejects_empty_and_long_text():
    engine = Mock()
    assert not speech.prepare_speech_text("😊")
    with pytest.raises(ValueError, match="empty"):
        speech.generate_speech_file("😊")
    with pytest.raises(ValueError, match="too long"):
        speech.generate_speech_file("ك" * (speech.MAX_SPEECH_CHARS + 1))


def test_generation_produces_voice_file_and_uses_single_cached_voice(monkeypatch, tmp_path):
    fake_voice = object()
    voice_loader = Mock(return_value=fake_voice)
    wav_writer = Mock()

    def fake_ffmpeg(source, destination):
        Path(destination).write_bytes(b"OggS" + b"0" * 128)

    monkeypatch.setattr(speech, "_get_voice", voice_loader)
    monkeypatch.setattr(speech, "_write_wav", wav_writer)
    monkeypatch.setattr(speech, "_convert_to_telegram_voice", fake_ffmpeg)
    monkeypatch.setattr(speech.tempfile, "tempdir", str(tmp_path))
    path = speech.generate_speech_file("أنا بحبك")
    assert path.suffix == ".ogg"
    assert path.read_bytes().startswith(b"OggS")
    wav_writer.assert_called_once_with(fake_voice, "أنا بحبك", wav_writer.call_args.args[2], prosody_text="أنا بحبك")
    path.unlink()


def test_generation_cleans_files_when_synthesis_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(speech, "_get_voice", lambda: object())
    monkeypatch.setattr(speech, "_write_wav", Mock(side_effect=RuntimeError("test failure")))
    monkeypatch.setattr(speech.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(RuntimeError, match="test failure"):
        speech.generate_speech_file("مرحبا")
    assert list(tmp_path.iterdir()) == []


def test_generator_rejects_a_concurrent_request(monkeypatch):
    monkeypatch.setattr(speech._TTS_SLOT, "acquire", lambda timeout: False)
    with pytest.raises(TimeoutError, match="busy"):
        speech.generate_speech_file("مرحبا")


def test_piper_voice_is_loaded_once_with_cpu_thread_limits(monkeypatch, tmp_path):
    calls = {"session": 0, "voice": 0}

    class FakeVoice:
        def __init__(self, **kwargs):
            calls["voice"] += 1
            self.kwargs = kwargs
            self.use_tashkeel = True

    class FakeConfig:
        @staticmethod
        def from_dict(data):
            return data

    class FakeSessionOptions:
        pass

    class FakeOrt:
        SessionOptions = FakeSessionOptions
        ExecutionMode = SimpleNamespace(ORT_SEQUENTIAL="sequential")

        @staticmethod
        def InferenceSession(*args, **kwargs):
            calls["session"] += 1
            options = kwargs["sess_options"]
            assert options.intra_op_num_threads == options.inter_op_num_threads == 1
            return object()

    monkeypatch.setattr(speech, "_VOICE", None)
    monkeypatch.setattr(speech, "_ensure_model_files", lambda: (tmp_path / "voice.onnx", tmp_path / "voice.json"))
    (tmp_path / "voice.json").write_text("{}", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "piper", SimpleNamespace(PiperVoice=FakeVoice))
    monkeypatch.setitem(sys.modules, "piper.config", SimpleNamespace(PiperConfig=FakeConfig))
    monkeypatch.setitem(sys.modules, "onnxruntime", FakeOrt)
    first, second = speech._get_voice(), speech._get_voice()
    assert first is second
    assert first.use_tashkeel is False
    assert calls == {"session": 1, "voice": 1}


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


def test_download_verifies_checksum_and_replaces_atomically(monkeypatch, tmp_path):
    payload = b"local model fixture"

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    monkeypatch.setattr(speech.urllib.request, "urlopen", lambda *a, **kw: FakeResponse(payload))
    target = tmp_path / "model.onnx"
    speech._download_file("https://example.invalid/model", target, checksum=hashlib.sha256(payload).hexdigest())
    assert target.read_bytes() == payload
    with pytest.raises(ValueError, match="checksum"):
        speech._download_file("https://example.invalid/model", target, checksum="0" * 64)
    assert not list(tmp_path.glob("model.onnx.*.part"))
