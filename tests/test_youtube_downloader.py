from __future__ import annotations

import os
import sys
import types
import asyncio
from unittest.mock import AsyncMock

import main


def test_download_command_parser_selects_mode_and_keeps_query():
    assert main._parse_youtube_download_request("نزلي سماعيل تمر") == ("سماعيل تمر", "audio")
    assert main._parse_youtube_download_request("نزلي سماعيل تمر صوت") == ("سماعيل تمر", "audio")
    assert main._parse_youtube_download_request("نزلي سماعيل تمر صوتي") == ("سماعيل تمر", "audio")
    assert main._parse_youtube_download_request("نزلي سماعيل تمر فيديو") == ("سماعيل تمر", "video")
    assert main._parse_youtube_download_request("نزلي سماعيل تمر فيديو كليب") == ("سماعيل تمر", "video")
    assert main._parse_youtube_download_request("نزلي Ismail Tamer video") == ("Ismail Tamer", "video")
    assert main._parse_youtube_download_request("نزلي اسم الأغنية") == ("اسم الأغنية", "audio")


def test_youtube_result_ranking_prefers_matching_official_song():
    results = [
        {"id": "wrong", "title": "Funny reaction gameplay compilation", "duration": 420},
        {"id": "right", "title": "إسماعيل تمر - أغنية جديدة Official Audio", "channel": "Ismail Tamer", "duration": 210},
    ]
    ranked = main._rank_youtube_results("سماعيل تمر", results, "audio")
    assert [item["id"] for item in ranked] == ["right", "wrong"]
    assert main._youtube_result_score("Ismael Tamer", results[1], "audio") > main._youtube_result_score("Ismael Tamer", results[0], "audio")


class _FakeYoutubeDL:
    search_entries = []
    download_calls = []
    failure = None
    fail_first_only = False

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def extract_info(self, target, download=False):
        if target.startswith("ytsearch"):
            return {"entries": list(self.search_entries)}
        self.download_calls.append((target, self.options))
        if self.failure and (not self.fail_first_only or len(self.download_calls) == 1):
            raise RuntimeError(self.failure)
        extension = "mp3" if self.options.get("postprocessors") else "mp4"
        output_path = self.options["outtmpl"].replace("%(id)s", "fixture123").replace("%(ext)s", extension)
        with open(output_path, "wb") as output:
            output.write(b"fixture-media")
        return {"title": "Ismail Tamer - Official", "uploader": "Ismail Tamer"}


def _install_fake_ytdlp(monkeypatch, entries):
    _FakeYoutubeDL.search_entries = entries
    _FakeYoutubeDL.download_calls = []
    _FakeYoutubeDL.failure = None
    _FakeYoutubeDL.fail_first_only = False
    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=_FakeYoutubeDL))


def _use_temp_root(monkeypatch, tmp_path):
    counter = iter(range(100))
    def make_temp_dir(prefix):
        path = tmp_path / f"{prefix}{next(counter)}"
        path.mkdir()
        return str(path)
    monkeypatch.setattr(main.tempfile, "mkdtemp", make_temp_dir)


def test_audio_mode_extracts_mp3_and_cleans_its_temp_directory(monkeypatch, tmp_path):
    _install_fake_ytdlp(monkeypatch, [{"id": "fixture123", "title": "Ismail Tamer Official Audio", "duration": 210}])
    _use_temp_root(monkeypatch, tmp_path)

    result = main._download_yt_audio("Ismail Tamer", "audio")
    assert result["success"] and result["mode"] == "audio"
    assert result["filepath"].endswith(".mp3")
    options = _FakeYoutubeDL.download_calls[0][1]
    assert options["postprocessors"][0]["preferredcodec"] == "mp3"
    assert "extractor_args" not in options  # use current yt-dlp defaults first
    assert not any("cookie" in key for key in options)
    temp_dir = result["temp_dir"]
    main._cleanup_youtube_download(result)
    assert not os.path.exists(temp_dir)


def test_video_mode_keeps_mp4_without_audio_postprocessor(monkeypatch, tmp_path):
    _install_fake_ytdlp(monkeypatch, [{"id": "fixture123", "title": "Ismail Tamer Official Video", "duration": 210}])
    _use_temp_root(monkeypatch, tmp_path)

    result = main._download_yt_audio("Ismail Tamer", "video")
    assert result["success"] and result["mode"] == "video"
    assert result["filepath"].endswith(".mp4")
    options = _FakeYoutubeDL.download_calls[0][1]
    assert "postprocessors" not in options
    assert options["merge_output_format"] == "mp4"
    main._cleanup_youtube_download(result)


def test_bot_challenge_gets_one_safe_fallback_then_generic_failure(monkeypatch, tmp_path):
    _install_fake_ytdlp(monkeypatch, [{"id": "fixture123", "title": "Ismail Tamer Official Audio", "duration": 210}])
    _FakeYoutubeDL.failure = "Sign in to confirm you’re not a bot"
    _use_temp_root(monkeypatch, tmp_path)

    result = main._download_yt_audio("Ismail Tamer", "audio")
    assert not result["success"]
    assert result["error"] == "youtube_download_failed"
    assert len(_FakeYoutubeDL.download_calls) == 2
    assert _FakeYoutubeDL.download_calls[1][1]["extractor_args"] == {"youtube": {"player_client": ["default"]}}
    assert not list(tmp_path.iterdir())
    assert "Sign in" not in main.YOUTUBE_FAILURE_MESSAGE
    assert "traceback" not in main.YOUTUBE_FAILURE_MESSAGE.casefold()


def test_bot_challenge_fallback_can_succeed(monkeypatch, tmp_path):
    _install_fake_ytdlp(monkeypatch, [{"id": "fixture123", "title": "Ismail Tamer Official Audio", "duration": 210}])
    _FakeYoutubeDL.failure = "Sign in to confirm you’re not a bot"
    _FakeYoutubeDL.fail_first_only = True
    _use_temp_root(monkeypatch, tmp_path)

    result = main._download_yt_audio("Ismail Tamer", "audio")
    assert result["success"] and len(_FakeYoutubeDL.download_calls) == 2
    main._cleanup_youtube_download(result)


def test_audio_and_video_results_use_the_matching_telegram_send_method(tmp_path):
    async def scenario():
        media_file = tmp_path / "fixture.bin"
        media_file.write_bytes(b"fixture")
        bot = types.SimpleNamespace(send_audio=AsyncMock(), send_video=AsyncMock())
        common = {"filepath": str(media_file), "title": "Fixture", "uploader": "Artist"}
        await main._send_youtube_result(bot, 12, 34, {**common, "mode": "audio"})
        await main._send_youtube_result(bot, 12, 34, {**common, "mode": "video"})
        bot.send_audio.assert_awaited_once()
        bot.send_video.assert_awaited_once()
    asyncio.run(scenario())
