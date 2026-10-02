"""Bounded async job manager; each submitted processor is isolated by job ID."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Any


class JobState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobQueueFull(RuntimeError):
    pass


@dataclass
class JobRecord:
    job_id: str
    state: JobState = JobState.QUEUED
    error: str | None = None
    task: asyncio.Task | None = None
    created_at: float = field(default_factory=time.time)


class VideoJobManager:
    def __init__(self, concurrency: int | None = None):
        self.limit = max(1, min(4, int(concurrency or os.getenv("LARA_VIDEO_CONCURRENCY", "1"))))
        self.max_pending = max(self.limit, min(100, int(os.getenv("LARA_VIDEO_MAX_PENDING", "20"))))
        self._semaphore = asyncio.Semaphore(self.limit)
        self._records: dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()

    async def submit(self, job_id: str, processor: Callable[[], Awaitable[Any]]) -> JobRecord:
        async with self._lock:
            now = time.time()
            self._records = {key: value for key, value in self._records.items()
                             if value.state in (JobState.QUEUED, JobState.PROCESSING)
                             or now - value.created_at < 3600}
            current = self._records.get(job_id)
            if current and current.state in (JobState.QUEUED, JobState.PROCESSING):
                return current
            pending = sum(r.state in (JobState.QUEUED, JobState.PROCESSING) for r in self._records.values())
            if pending >= self.max_pending:
                raise JobQueueFull("طابور معالجة الفيديو ممتلئ مؤقتًا؛ حاول بعد انتهاء بعض المهام.")
            record = JobRecord(job_id)
            self._records[job_id] = record
            record.task = asyncio.create_task(self._run(record, processor), name=f"video-{job_id}")
            return record

    async def _run(self, record: JobRecord, processor: Callable[[], Awaitable[Any]]) -> None:
        try:
            async with self._semaphore:
                record.state = JobState.PROCESSING
                await processor()
                record.state = JobState.COMPLETED
        except asyncio.CancelledError:
            record.state = JobState.CANCELLED
            raise
        except Exception as exc:
            record.state = JobState.FAILED
            record.error = str(exc)[:500]

    async def cancel(self, job_id: str) -> bool:
        async with self._lock:
            record = self._records.get(job_id)
            if not record or not record.task or record.task.done():
                return False
            record.task.cancel()
        try:
            await record.task
        except asyncio.CancelledError:
            pass
        return True

    async def get(self, job_id: str) -> JobRecord | None:
        async with self._lock:
            return self._records.get(job_id)


video_jobs = VideoJobManager()
