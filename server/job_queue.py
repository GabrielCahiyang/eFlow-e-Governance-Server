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


class QueueCapacityError(ValueError):
    """Retryable admission failure, distinct from an invalid payload."""

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
    cancelled: bool = False
    completion: asyncio.Event = field(default_factory=asyncio.Event)


class AiJobQueue:
    """A fair, single-consumer queue with owner-scoped status snapshots."""

    def __init__(
        self,
        processor: JobProcessor,
        *,
        result_ttl_seconds: int = 3600,
        max_retained_jobs: int = 200,
        max_waiting_jobs: int = 32,
        max_jobs_per_owner: int = 2,
        cleanup_interval_seconds: float = 30,
    ) -> None:
        self._processor = processor
        self._result_ttl_seconds = result_ttl_seconds
        self._max_retained_jobs = max_retained_jobs
        self._max_waiting_jobs = max_waiting_jobs
        self._max_jobs_per_owner = max_jobs_per_owner
        self._cleanup_interval_seconds = cleanup_interval_seconds
        self._jobs: dict[str, AiJob] = {}
        self._request_jobs: dict[tuple[str, str], str] = {}
        self._waiting: deque[str] = deque()
        self._wake = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._active_job_id: str | None = None
        self._lock = asyncio.Lock()
        self._cleanup_task = None
        self._processor_task = None
        self._accepting = True

    async def start(self) -> None:
        if self._worker and not self._worker.done():
            return
        self._worker = asyncio.create_task(self._run(), name="eflow-ai-job-worker")
        self._accepting = True
        self._cleanup_task = asyncio.create_task(self._cleanup(), name="eflow-job-cleanup")

    async def stop(self, *, drain: bool = True) -> None:
        if not self._worker:
            return
        self._accepting = False
        if not drain:
            for job in list(self._jobs.values()):
                if job.status in {"queued", "processing"}:
                    await self.cancel(job.id)
        self._wake.set()
        await self._worker
        self._worker = None
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

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
            if not self._accepting:
                raise QueueCapacityError("The AI worker is shutting down. Try again shortly.")
            if len(self._waiting) >= self._max_waiting_jobs:
                raise QueueCapacityError("The AI queue is full. Try again shortly.")
            owner_jobs = sum(j.owner_id == owner_id and j.status in {"queued", "processing"}
                             for j in self._jobs.values())
            if owner_jobs >= self._max_jobs_per_owner:
                raise QueueCapacityError("You already have the maximum number of outstanding AI requests.")
            self._jobs[job.id] = job
            if request_id:
                self._request_jobs[(owner_id, request_id)] = job.id
            self._waiting.append(job.id)
            self._wake.set()
            return self._snapshot_locked(job)

    async def wait(self, job_id: str, owner_id: str) -> dict[str, Any] | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.owner_id != owner_id:
                return None
        await job.completion.wait()
        return self._snapshot_locked(job)

    async def cancel(self, job_id: str, owner_id: str | None = None) -> dict[str, Any] | None:
        """None owner is reserved for the authenticated local operations API."""
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job or (owner_id is not None and job.owner_id != owner_id):
                return None
            if job.status in {"completed", "failed"} or job.cancelled:
                return self._snapshot_locked(job)
            job.cancelled = True
            if job.status == "queued":
                self._waiting.remove(job.id)
                job.status = "failed"
                job.error = "Cancelled by user"
                job.completed_at = time.time()
                job.payload = {"model": job.payload.get("model")}
                job.completion.set()
            elif self._processor_task:
                self._processor_task.cancel()
            return self._snapshot_locked(job)

    async def _cleanup(self):
        while True:
            await asyncio.sleep(self._cleanup_interval_seconds)
            async with self._lock:
                self._prune_locked()

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
                "capacity": self._max_waiting_jobs,
                "per_user_limit": self._max_jobs_per_owner,
                "jobs": [
                    {"job_id": j.id, "model": j.payload.get("model"), "status": j.status,
                     "submitted_at": j.submitted_at, "started_at": j.started_at,
                     "progress": ({**j.progress, "history": list(j.progress_history)} if j.progress else None), "cancelled": j.cancelled}
                    for j in ([active] if active else []) + [self._jobs[i] for i in self._waiting]
                ],
            }

    async def _run(self) -> None:
        while True:
            await self._wake.wait()
            async with self._lock:
                if not self._waiting:
                    self._wake.clear()
                    if not self._accepting:
                        return
                    continue
                job_id = self._waiting.popleft()
                if not self._waiting:
                    self._wake.clear()
                    if not self._accepting:
                        self._wake.set()
                job = self._jobs[job_id]
                self._active_job_id = job_id
                job.status = "processing"
                job.started_at = time.time()

            loop = asyncio.get_running_loop()
            progress_token = _progress_reporter.set(
                lambda metadata, target_id=job_id: loop.call_soon_threadsafe(self._record_progress, target_id, metadata)
            )
            try:
                self._processor_task = asyncio.create_task(self._processor(job.payload))
                result = await self._processor_task
                async with self._lock:
                    job.result = result
                    job.status = "completed"
                    job.completed_at = time.time()
            except asyncio.CancelledError:
                async with self._lock:
                    job.cancelled = True
                    job.error = "Cancelled by user"
                    job.status = "failed"
                    job.completed_at = time.time()
            except Exception as exc:
                async with self._lock:
                    job.error = str(exc) or exc.__class__.__name__
                    job.status = "failed"
                    job.completed_at = time.time()
            finally:
                _progress_reporter.reset(progress_token)
                async with self._lock:
                    self._processor_task = None
                    job.payload = {"model": job.payload.get("model")}
                    job.completion.set()
                    if self._active_job_id == job_id:
                        self._active_job_id = None

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
            "cancelled": job.cancelled,
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
