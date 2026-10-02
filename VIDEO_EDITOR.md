# Lara Video Editor

The editor is an additive feature opened from the new **Multimedia Video Editor** button in the existing VIP panel. The legacy `start_video_edit`, `vip_menu`, and `vip_stats` callbacks and the original video handlers remain registered. Editor callbacks use the `video_editor:` namespace.

## User flow

1. Open the editor and start a session.
2. Send up to eight videos, video documents, audio files, voice notes, images, or SRT/VTT documents. The default combined known/downloaded input cap is 80 MB.
3. Press **Finished sending media** and describe the edit in Arabic or colloquial Arabic.
4. Review the generated plan, then execute, edit the request, or cancel.

Sessions have unique UUID job IDs, are bound to the initiating user and chat, and use isolated directories under `storage/video_editor/`. Session state currently lives in process memory; after a bot restart, users must start a new session, and directories from jobs interrupted by a process crash may need manual removal. During normal operation, an application cleanup task reclaims expired inactive sessions every five minutes. Active jobs are not removed during cleanup.

## Current operations

Implemented through argument-list FFmpeg subprocesses (no shell): video/audio trim, audio removal/extraction/replacement/mixing, volume adjustment, speed changes, resize/pad, compression, ordered video concatenation, image overlay, text overlay, subtitle burn-in for attached SRT/VTT, rotate, flip, crop, fade, brightness, contrast, saturation, blur, and sharpen. FFprobe validates input/output streams. Processing has a configurable timeout, cancellation, progress messages, and a bounded queue.

Natural-language parsing has an Arabic/colloquial local rule fallback. An optional OpenAI Responses API parser can handle broader phrasing and returns a structured plan that is checked against operation allowlists and numeric/media constraints before confirmation. The API receives the prompt and media type/order summary only; media files are not uploaded to it. The integration is disabled unless explicitly enabled.

Speech recognition, subtitle translation, noise removal, voice/music separation, and text-to-video generation are not implemented. Subtitle and video-generation provider interfaces are present so a real provider can be added without claiming a mock result.

## Configuration

- `FFMPEG_BINARY` and `FFPROBE_BINARY`: optional explicit executable paths. The engine checks these, then `PATH`, then the installed `static-ffmpeg` package API.
- `LARA_FFMPEG_TIMEOUT`: per-command timeout in seconds (default 1800).
- `LARA_VIDEO_CONCURRENCY`: active FFmpeg jobs (default 1, capped at 4).
- `LARA_VIDEO_MAX_PENDING`: queued plus active jobs (default 20, capped at 100).
- `LARA_VIDEO_STORAGE`: job storage root (default `storage/video_editor`).
- `LARA_TELEGRAM_DOWNLOAD_MAX_BYTES`: incoming download limit (default 20 MiB).
- `LARA_TELEGRAM_UPLOAD_MAX_BYTES`: result upload limit (default 50 MiB).
- `LARA_VIDEO_SESSION_MAX_BYTES`: combined input cap (default 80 MiB).
- `TELEGRAM_API_BASE_URL` and `TELEGRAM_FILE_BASE_URL`: optional PTB Bot API and file API endpoints for a separately configured Local Bot API Server. The default cloud endpoints remain in use when these are unset.
- `LARA_USE_AI_INTENT=true` and `OPENAI_API_KEY`: explicitly opt in to remote natural-language parsing. `LARA_INTENT_MODEL` selects the model (default `gpt-4.1-mini`). No API key is embedded in source. Requests use the existing `requests` dependency and set `store: false`.

The Bot API cloud service currently documents 20 MB for bot downloads and 50 MB for uploads. Raising the editor byte limits alone does not raise Telegram's cloud API limits; configure both custom API endpoints to use a Local Bot API Server before raising the download limit.

## Local checks

From the repository root:

```sh
PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 pytest -q -p no:cacheprovider tests/test_video_editor.py
```

This suite uses a short synthetic FFmpeg fixture and does not contact Telegram, a remote AI provider, or the production database. Importing `main` does not start polling or the optional keep-alive threads.
