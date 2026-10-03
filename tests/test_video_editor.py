from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from services.intent import parse_edit_request, parse_natural_request, validate_model_plan
from services.media_sessions import MediaSessionManager, SessionState
from services.video_engine import MediaEngine
from services.video_jobs import JobState, VideoJobManager
from handlers.video_editor import _new_session
from handlers.video_editor import (_control_keyboard, _category_keyboard, _template_keyboard,
                                   _template_picker, _text_options_keyboard, TOOL_REQUESTS)
from main_vip import handle_start_video_edit


def _media(kind: str):
    return type("Media", (), {"kind": kind})()


def test_parser_first_minute_and_composed_request():
    plan = parse_edit_request("قصلي أول دقيقة وشيل الصوت وخليه عمودي", [_media("video")])
    assert plan.ready
    assert [op["type"] for op in plan.operations] == ["trim", "remove_audio", "resize"]
    assert plan.operations[0]["end"] == 60


def test_parser_asks_for_missing_trim_range():
    plan = parse_edit_request("قص الفيديو", [_media("video")])
    assert not plan.ready
    assert "أي ثانية" in (plan.clarification or "")


def test_parser_parses_minute_range_and_compress():
    plan = parse_edit_request("قص الجزء من الدقيقة 2 للدقيقة 3 وصغر حجمه", [_media("video")])
    assert plan.ready
    trim = next(op for op in plan.operations if op["type"] == "trim")
    assert trim["start"] == 120
    assert trim["end"] == 180
    assert any(op["type"] == "compress" for op in plan.operations)


def test_parser_requires_assets_and_does_not_fake_subtitles():
    missing_audio = parse_edit_request("حط الأغنية يلي بعتلك ياها")
    assert missing_audio.clarification
    subtitles = parse_edit_request("طلعلي الترجمة")
    assert subtitles.unsupported
    assert not subtitles.operations


def test_parser_media_references_for_audio_and_image():
    plan = parse_edit_request("حط الصوت يلي بعتلك بدل القديم وحط الصورة بالنص", [
        _media("video"), _media("audio"), _media("image")
    ])
    assert plan.ready
    assert [op["type"] for op in plan.operations] == ["replace_audio", "overlay_image"]


def test_parser_speed_second_video_audio_and_image_duration():
    media = [_media("video"), _media("video"), _media("image")]
    replace = parse_edit_request("بدل الصوت وحط صوت الفيديو الثاني", media)
    assert replace.ready
    assert replace.operations[0] == {"type": "replace_audio", "source_video_index": 2}
    speed = parse_edit_request("سرع الفيديو للضعف")
    assert speed.operations == [{"type": "change_speed", "factor": 2.0}]
    slow = parse_edit_request("خليه أبطأ")
    assert slow.operations == [{"type": "change_speed", "factor": 0.5}]
    image = parse_edit_request("حط الصورة أول 5 ثواني بالنص", media)
    assert image.ready and image.operations[0]["duration"] == 5


def test_local_parser_handles_arabic_editor_tool_examples():
    cases = {
        "سرّعو للضعف": "change_speed",
        "شيل الصوت": "remove_audio",
        "زود الإضاءة": "brightness",
        "خلي الألوان أقوى": "saturation",
        "حول الفيديو إلى 9:16": "resize",
        'حط كتابة "أهلا وسهلا" على الفيديو': "text_overlay",
        "خلي الفيديو أبيض وأسود": "grayscale",
        "اعمل fade بالبداية": "fade",
        "دوّر الفيديو 90 درجة": "rotate",
    }
    for request, operation in cases.items():
        plan = parse_edit_request(request, [_media("video")])
        assert plan.ready, (request, plan.clarification)
        assert operation in [item["type"] for item in plan.operations]


def test_editor_panels_have_only_wired_local_tools():
    assert sum(map(len, TOOL_REQUESTS.values())) >= 20
    keyboards = [_control_keyboard("a" * 32), _template_keyboard("a" * 32),
                 _template_picker("a" * 32, "cinematic_trailer"), _text_options_keyboard("a" * 32)]
    for category in TOOL_REQUESTS:
        markup = _category_keyboard(category, "a" * 32)
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        assert callbacks and all(callback.startswith("video_editor:") for callback in callbacks)
        keyboards.append(markup)
    all_callbacks = [button.callback_data for markup in keyboards for row in markup.inline_keyboard
                     for button in row if button.callback_data]
    assert all(len(callback.encode("utf-8")) <= 64 for callback in all_callbacks)


def test_ai_plan_validator_rejects_unsafe_values_and_checks_media():
    valid = validate_model_plan({"operations": [{"type": "trim", "start": 3, "end": 9}]}, [_media("video")])
    assert valid.ready and valid.operations[0]["type"] == "trim"
    invalid = validate_model_plan({"operations": [{"type": "trim", "start": 9, "end": 3}]}, [_media("video")])
    assert invalid.clarification
    missing = validate_model_plan({"operations": [{"type": "overlay_image", "media_index": 1}]}, [_media("video")])
    assert missing.clarification
    forbidden = validate_model_plan({"operations": [{"type": "run_shell", "command": "rm -rf /"}]}, [_media("video")])
    assert forbidden.unsupported and not forbidden.operations


def test_remote_ai_is_opt_in_and_local_parser_remains_available(monkeypatch):
    async def scenario():
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("LARA_USE_AI_INTENT", raising=False)
        plan = await parse_natural_request("قصلي أول 20 ثانية", [_media("video")])
        assert plan.ready and plan.operations[0]["end"] == 20
    asyncio.run(scenario())


def test_job_manager_bounds_concurrency_and_tracks_states():
    async def scenario():
        jobs = VideoJobManager(concurrency=1)
        gate = asyncio.Event()
        active = 0
        peak = 0
        async def processor():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await gate.wait()
            active -= 1
        first = await jobs.submit("a", processor)
        second = await jobs.submit("b", processor)
        await asyncio.sleep(0.02)
        assert first.state == JobState.PROCESSING
        assert second.state == JobState.QUEUED
        assert peak == 1
        gate.set()
        await asyncio.gather(first.task, second.task)
        assert first.state == second.state == JobState.COMPLETED
    asyncio.run(scenario())


def test_engine_validates_operation_parameters_without_running_ffmpeg():
    assert MediaEngine._number("1.5", 0.25, 4, "speed") == 1.5
    try:
        MediaEngine._number("999", 0.25, 4, "speed")
    except Exception as exc:
        assert "between" in str(exc)
    else:
        raise AssertionError("out-of-range values must be rejected")


def test_video_editor_refuses_group_session_creation():
    async def scenario():
        update = SimpleNamespace(effective_user=SimpleNamespace(id=7),
                                 effective_chat=SimpleNamespace(id=-100, type="supergroup"))
        context = SimpleNamespace(user_data={})
        try:
            await _new_session(update, context)
        except RuntimeError as exc:
            assert "private" in str(exc).lower()
        else:
            raise AssertionError("group chat must not create a video session")
    asyncio.run(scenario())


def test_vip_video_workflow_refuses_group_callback():
    async def scenario():
        query = SimpleNamespace(answer=AsyncMock())
        update = SimpleNamespace(callback_query=query,
                                 effective_chat=SimpleNamespace(id=-100, type="group"))
        context = SimpleNamespace(user_data={})
        await handle_start_video_edit(update, context)
        query.answer.assert_awaited_once_with("محرر الفيديو متاح في الخاص فقط.", show_alert=True)
        assert not context.user_data
    asyncio.run(scenario())


def test_ffmpeg_trim_and_remove_audio_on_tiny_fixture(tmp_path: Path):
    async def scenario():
        engine = MediaEngine(timeout_seconds=60)
        source = tmp_path / "tiny.mp4"
        make = [engine.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc=size=160x120:rate=12",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)]
        subprocess.run(make, check=True, capture_output=True, timeout=60)
        trimmed = await engine.apply(source, tmp_path / "trimmed.mp4", {"type": "trim", "start": 0.25, "end": 1.25})
        meta = await engine.probe_media(trimmed)
        assert 0.8 <= float(meta["format"]["duration"]) <= 1.3
        muted = await engine.apply(trimmed, tmp_path / "muted.mp4", {"type": "remove_audio"})
        muted_meta = await engine.probe_media(muted)
        assert all(stream["codec_type"] != "audio" for stream in muted_meta["streams"])
        gray = await engine.apply(trimmed, tmp_path / "gray.mp4", {"type": "grayscale"})
        assert any(stream["codec_type"] == "video" for stream in (await engine.probe_media(gray))["streams"])
        reversed_video = await engine.apply(trimmed, tmp_path / "reversed.mp4", {"type": "reverse"})
        assert any(stream["codec_type"] == "video" for stream in (await engine.probe_media(reversed_video))["streams"])
    asyncio.run(scenario())


def test_ffmpeg_audio_only_trim_and_mix(tmp_path: Path):
    async def scenario():
        engine = MediaEngine(timeout_seconds=60)
        sources = []
        for i, frequency in enumerate((440, 660)):
            path = tmp_path / f"tone_{i}.m4a"
            subprocess.run([engine.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                            "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=44100",
                            "-t", "2", "-c:a", "aac", str(path)], check=True, capture_output=True, timeout=60)
            sources.append(path)
        trimmed = await engine.apply(sources[0], tmp_path / "audio_trim.m4a",
                                     {"type": "trim_audio", "start": 0.25, "end": 1.25})
        assert any(s["codec_type"] == "audio" for s in (await engine.probe_media(trimmed))["streams"])
        mixed = await engine.apply(sources[0], tmp_path / "audio_mix.m4a",
                                   {"type": "mix_audio", "volume": 0.3}, auxiliary=sources[1])
        mixed_streams = (await engine.probe_media(mixed))["streams"]
        assert any(s["codec_type"] == "audio" for s in mixed_streams)
        assert all(s["codec_type"] != "video" for s in mixed_streams)
    asyncio.run(scenario())


def test_sessions_are_isolated_and_active_files_are_not_removed(tmp_path: Path):
    async def scenario():
        manager = MediaSessionManager(tmp_path, ttl_seconds=300)
        session = await manager.create(10, 20)
        assert await manager.get(session.job_id, 11, 20) is None
        item = await manager.add_media(session.job_id, 10, 20, file_id="tg-file",
                                       kind="video", filename="../../unsafe.mp4", file_size=10)
        assert item and item.filename == "unsafe.mp4"
        await manager.set_state(session.job_id, 10, SessionState.PROCESSING)
        assert not await manager.remove(session.job_id, 10)
        assert session.job_dir.exists()
        await manager.set_state(session.job_id, 10, SessionState.CANCELLED)
        assert await manager.remove(session.job_id, 10)
        assert not session.job_dir.exists()
    asyncio.run(scenario())


def test_session_cleanup_removes_stale_orphan_job_directories(tmp_path: Path):
    async def scenario():
        import os
        import time
        manager = MediaSessionManager(tmp_path, ttl_seconds=300)
        orphan = tmp_path / ("b" * 32)
        orphan.mkdir()
        os.utime(orphan, (time.time() - 600, time.time() - 600))
        assert await manager.cleanup_expired() == 1
        assert not orphan.exists()
    asyncio.run(scenario())


def test_legacy_vip_callbacks_and_main_commands_remain_registered():
    root = Path(__file__).resolve().parents[1]
    main = (root / "main.py").read_text(encoding="utf-8")
    vip = (root / "main_vip.py").read_text(encoding="utf-8")
    for callback in ('callback_data="vip_menu"', 'callback_data="start_video_edit"',
                     'callback_data="vip_stats"'):
        assert callback in vip or callback in main
    for command in ('CommandHandler("start", start)', 'CommandHandler("id", cmd_id)',
                    'CommandHandler("ping", cmd_ping)', 'CommandHandler("calc", cmd_calc)',
                    'CommandHandler("xo", cmd_xo)'):
        assert command in main
    assert 'CallbackQueryHandler(button_router)' in main
    assert 'CallbackQueryHandler(video_editor_callback, pattern=r"^video_editor:")' in main


def test_main_import_is_side_effect_free():
    import main  # noqa: F401
