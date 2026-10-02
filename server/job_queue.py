"""In-memory FIFO queue for serial execution on the single local model."""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from contextvars import ContextVar
import time
from typing import Any, Awaitable, Callable, Literal
from uuid import uuid4


JobStatus = Literal["queued", "processing", "completed", "failed"]
JobProcessor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_progress_reporter: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar("eflow_job_progress", default=None)


def report_job_progress(stage: str, message: str, current: int | None = None, total: int | None = None) -> None:
    """Internal worker progress; no credentials, prompts, or model reasoning."""
    reporter = _progress_reporter.get()
    if reporter:
        reporter({"stage": stage, "message": message, "current": current, "total": total, "updated_at": time.time()})



@dataclass
class AiJob:
    id: str
    owner_id: str
    payload: dict[str, Any]
    status: JobStatus
    submitted_at: float
    request_id: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    progress: dict[str, Any] | None = None
    progress_history: list[dict[str, Any]] = field(default_factory=list)


class AiJobQueue:
    """A fair, single-consumer queue with owner-scoped status snapshots."""

    def __init__(
        self,
        processor: JobProcessor,
        *,
        result_ttl_seconds: int = 3600,
        max_retained_jobs: int = 200,
    ) -> None:
        self._processor = processor
        self._result_ttl_seconds = result_ttl_seconds
        self._max_retained_jobs = max_retained_jobs
        self._jobs: dict[str, AiJob] = {}
        self._request_jobs: dict[tuple[str, str], str] = {}
        self._waiting: deque[str] = deque()
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._active_job_id: str | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._worker and not self._worker.done():
            return
        self._worker = asyncio.create_task(self._run(), name="eflow-ai-job-worker")

    async def stop(self) -> None:
        if not self._worker:
            return
        await self._queue.put(None)
        await self._worker
        self._worker = None

    async def submit(
        self,
        owner_id: str,
        payload: dict[str, Any],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        job = AiJob(
            id=str(uuid4()),
            owner_id=owner_id,
            payload=payload,
            status="queued",
            submitted_at=time.time(),
            request_id=request_id,
        )
        async with self._lock:
            self._prune_locked()
            if request_id:
                existing_id = self._request_jobs.get((owner_id, request_id))
                existing = self._jobs.get(existing_id or "")
                if existing:
                    return self._snapshot_locked(existing)
            self._jobs[job.id] = job
            if request_id:
                self._request_jobs[(owner_id, request_id)] = job.id
            self._waiting.append(job.id)
            await self._queue.put(job.id)
            return self._snapshot_locked(job)

    async def snapshot(self, job_id: str, owner_id: str) -> dict[str, Any] | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.owner_id != owner_id:
                return None
            return self._snapshot_locked(job)

    async def overview(self) -> dict[str, Any]:
        """Return privacy-safe queue telemetry for the local operations UI."""
        async with self._lock:
            now = time.time()
            active = self._jobs.get(self._active_job_id or "")
            oldest_wait = (
                self._jobs.get(self._waiting[0]) if self._waiting else None
            )
            completed = sum(job.status == "completed" for job in self._jobs.values())
            failed = sum(job.status == "failed" for job in self._jobs.values())
            return {
                "depth": len(self._waiting) + (1 if active else 0),
                "waiting": len(self._waiting),
                "processing": 1 if active else 0,
                "worker_online": bool(self._worker and not self._worker.done()),
                "active_job": (
                    {
                        "job_id": active.id,
                        "model": str(active.payload.get("model") or "Unknown model"),
                        "running_seconds": round(now - (active.started_at or now)),
                    }
                    if active
                    else None
                ),
                "oldest_wait_seconds": (
                    round(now - oldest_wait.submitted_at) if oldest_wait else 0
                ),
                "completed_retained": completed,
                "failed_retained": failed,
            }

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            if job_id is None:
                self._queue.task_done()
                return

            async with self._lock:
                job = self._jobs.get(job_id)
                if not job:
                    self._queue.task_done()
                    continue
                if self._waiting and self._waiting[0] == job_id:
                    self._waiting.popleft()
                else:
                    try:
                        self._waiting.remove(job_id)
                    except ValueError:
                        pass
                self._active_job_id = job_id
                job.status = "processing"
                job.started_at = time.time()

            loop = asyncio.get_running_loop()
            progress_token = _progress_reporter.set(
                lambda metadata, target_id=job_id: loop.call_soon_threadsafe(self._record_progress, target_id, metadata)
            )
            try:
                result = await self._processor(job.payload)
                async with self._lock:
                    job.result = result
                    job.status = "completed"
                    job.completed_at = time.time()
            except Exception as exc:
                async with self._lock:
                    job.error = str(exc) or exc.__class__.__name__
                    job.status = "failed"
                    job.completed_at = time.time()
            finally:
                _progress_reporter.reset(progress_token)
                async with self._lock:
                    if self._active_job_id == job_id:
                        self._active_job_id = None
                self._queue.task_done()

    def _record_progress(self, job_id: str, metadata: dict[str, Any]) -> None:
        # Always runs on the event loop, including reports from to_thread.
        job = self._jobs.get(job_id)
        if not job or job.status not in {"processing", "completed"}:
            return
        job.progress = dict(metadata)
        if not job.progress_history or job.progress_history[-1]["stage"] != metadata["stage"]:
            job.progress_history.append(dict(metadata))
            job.progress_history = job.progress_history[-20:]

    def _snapshot_locked(self, job: AiJob) -> dict[str, Any]:
        position: int | None = None
        jobs_ahead = 0
        if job.status == "processing":
            position = 1
        elif job.status == "queued":
            try:
                waiting_index = self._waiting.index(job.id)
            except ValueError:
                waiting_index = 0
            active_count = 1 if self._active_job_id else 0
            position = active_count + waiting_index + 1
            jobs_ahead = max(0, position - 1)

        return {
            "job_id": job.id,
            "status": job.status,
            "progress": ({**job.progress, "history": list(job.progress_history)} if job.progress else None),
            "position": position,
            "jobs_ahead": jobs_ahead,
            "queue_depth": len(self._waiting) + (1 if self._active_job_id else 0),
            "submitted_at": job.submitted_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "result": job.result if job.status == "completed" else None,
            "error": job.error if job.status == "failed" else None,
        }

    def _prune_locked(self) -> None:
        now = time.time()
        removable = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in {"completed", "failed"}
            and job.completed_at is not None
            and now - job.completed_at > self._result_ttl_seconds
        ]
        for job_id in removable:
            job = self._jobs.pop(job_id, None)
            if job and job.request_id:
                self._request_jobs.pop((job.owner_id, job.request_id), None)

        if len(self._jobs) <= self._max_retained_jobs:
            return
        completed = sorted(
            (
                job
                for job in self._jobs.values()
                if job.status in {"completed", "failed"}
            ),
            key=lambda job: job.completed_at or job.submitted_at,
        )
        for job in completed[: max(0, len(self._jobs) - self._max_retained_jobs)]:
            self._jobs.pop(job.id, None)
            if job.request_id:
                self._request_jobs.pop((job.owner_id, job.request_id), None)
