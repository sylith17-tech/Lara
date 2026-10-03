"""Per-user media editing sessions and isolated, TTL-bound job storage."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SessionState(str, Enum):
    RECEIVING_MEDIA = "RECEIVING_MEDIA"
    WAITING_FOR_INSTRUCTIONS = "WAITING_FOR_INSTRUCTIONS"
    WAITING_TEXT = "WAITING_TEXT"
    WAITING_AUDIO = "WAITING_AUDIO"
    WAITING_AUDIO_VIDEO = "WAITING_AUDIO_VIDEO"
    WAITING_MERGE_VIDEO = "WAITING_MERGE_VIDEO"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    READY = "READY"


@dataclass
class MediaItem:
    index: int
    file_id: str
    kind: str
    filename: str
    file_size: int | None = None
    mime_type: str | None = None
    role: str | None = None
    local_path: str | None = None


@dataclass
class MediaSession:
    job_id: str
    user_id: int
    chat_id: int
    job_dir: Path
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    state: SessionState = SessionState.RECEIVING_MEDIA
    media: list[MediaItem] = field(default_factory=list)
    prompt: str | None = None
    plan: list[dict[str, Any]] = field(default_factory=list)
    clarification: str | None = None
    result_path: str | None = None
    task: asyncio.Task | None = None
    history: list[str] = field(default_factory=list)
    history_cursor: int = 0
    lara_intro: bool = False
    operation_count: int = 0
    preview_count: int = 0
    selected_template: str | None = None
    export_profile: str = "balanced"


class MediaSessionManager:
    """In-process session registry with owner checks and safe TTL cleanup."""

    def __init__(self, root: str | Path | None = None, ttl_seconds: int = 6 * 3600):
        self.root = Path(root or os.getenv("LARA_VIDEO_STORAGE", "storage/video_editor")).resolve()
        self.ttl_seconds = max(300, int(ttl_seconds))
        self._sessions: dict[str, MediaSession] = {}
        self._lock = asyncio.Lock()

    async def create(self, user_id: int, chat_id: int) -> MediaSession:
        async with self._lock:
            job_id = uuid.uuid4().hex
            job_dir = (self.root / job_id).resolve()
            job_dir.mkdir(parents=True, exist_ok=False)
            (job_dir / "input").mkdir()
            (job_dir / "temp").mkdir()
            (job_dir / "output").mkdir()
            session = MediaSession(job_id, int(user_id), int(chat_id), job_dir)
            self._sessions[job_id] = session
            return session

    async def get(self, job_id: str, user_id: int, chat_id: int | None = None) -> MediaSession | None:
        expired_session = None
        async with self._lock:
            session = self._sessions.get(job_id)
            if not session or session.user_id != int(user_id):
                return None
            if chat_id is not None and session.chat_id != int(chat_id):
                return None
            if (time.time() - session.updated_at > self.ttl_seconds
                    and session.state != SessionState.PROCESSING
                    and (not session.task or session.task.done())):
                expired_session = self._sessions.pop(job_id)
                session = None
            if session:
                session.updated_at = time.time()
        if expired_session:
            self._safe_remove_dir(expired_session.job_dir)
            return None
        if session:
            return session
        return None

    async def add_media(self, job_id: str, user_id: int, chat_id: int, *, file_id: str,
                        kind: str, filename: str, file_size: int | None = None,
                        mime_type: str | None = None) -> MediaItem | None:
        async with self._lock:
            session = self._sessions.get(job_id)
            if not session or session.user_id != int(user_id) or session.chat_id != int(chat_id):
                return None
            if session.state not in (SessionState.RECEIVING_MEDIA, SessionState.WAITING_FOR_INSTRUCTIONS,
                                     SessionState.WAITING_TEXT, SessionState.WAITING_AUDIO,
                                     SessionState.WAITING_AUDIO_VIDEO, SessionState.WAITING_MERGE_VIDEO):
                return None
            if len(session.media) >= 8:
                return None
            known_bytes = sum(m.file_size or 0 for m in session.media) + (file_size or 0)
            if known_bytes > 80 * 1024 * 1024:
                return None
            same_kind_count = sum(m.kind == kind for m in session.media) + 1
            if kind in ("video", "video_document"):
                role = "primary_video" if same_kind_count == 1 else f"video_source_{same_kind_count}"
            elif kind in ("audio", "audio_document", "voice"):
                role = f"audio_source_{same_kind_count}"
            elif kind == "image":
                role = f"overlay_image_{same_kind_count}"
            elif kind == "subtitle":
                role = f"subtitle_track_{same_kind_count}"
            else:
                role = f"media_{same_kind_count}"
            item = MediaItem(len(session.media) + 1, file_id, kind, Path(filename).name,
                             file_size, mime_type, role)
            session.media.append(item)
            session.state = SessionState.RECEIVING_MEDIA
            session.updated_at = time.time()
            return item

    async def set_state(self, job_id: str, user_id: int, state: SessionState) -> bool:
        async with self._lock:
            session = self._sessions.get(job_id)
            if not session or session.user_id != int(user_id):
                return False
            session.state = state
            session.updated_at = time.time()
            return True

    async def remove(self, job_id: str, user_id: int, *, force: bool = False) -> bool:
        async with self._lock:
            session = self._sessions.get(job_id)
            if not session or session.user_id != int(user_id):
                return False
            if session.state == SessionState.PROCESSING:
                return False
            if session.task and not session.task.done():
                return False
            self._sessions.pop(job_id, None)
        self._safe_remove_dir(session.job_dir)
        return True

    def _safe_remove_dir(self, path: Path) -> None:
        root = self.root.resolve()
        resolved = path.resolve()
        if resolved.parent == root and resolved.name and resolved.exists():
            shutil.rmtree(resolved)

    async def cleanup_expired(self) -> int:
        now = time.time()
        removed_dirs: set[Path] = set()
        async with self._lock:
            expired = [s for s in self._sessions.values()
                       if now - s.updated_at > self.ttl_seconds
                       and s.state != SessionState.PROCESSING
                       and (not s.task or s.task.done())]
            for session in expired:
                self._sessions.pop(session.job_id, None)
        for session in expired:
            self._safe_remove_dir(session.job_dir)
            removed_dirs.add(session.job_dir.resolve())
        if self.root.is_dir():
            active_dirs = {session.job_dir.resolve() for session in self._sessions.values()}
            for child in self.root.iterdir():
                if (child.is_dir() and re.fullmatch(r"[a-f0-9]{32}", child.name)
                        and child.resolve() not in active_dirs and child.resolve() not in removed_dirs):
                    try:
                        if now - child.stat().st_mtime > self.ttl_seconds:
                            self._safe_remove_dir(child)
                            removed_dirs.add(child.resolve())
                    except FileNotFoundError:
                        continue
        return len(removed_dirs)


media_sessions = MediaSessionManager()
