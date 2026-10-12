"""Bounded operational metadata; never retains task/document bodies or secrets.

Thread workers own their completion records even if the HTTP caller disconnects.
Inference-process events are forwarded over its existing pipe to the API process.
"""
import asyncio
from collections import deque
from contextvars import ContextVar, copy_context
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import importlib.util
import logging
import math
from functools import wraps
import threading
import time
from uuid import uuid4


event_sink = ContextVar("eflow_service_events", default=None)
current_run = ContextVar("eflow_service_run", default=None)
run_origin = ContextVar("eflow_service_origin", default="standalone")
SERVICES = ("pygad", "laya", "blockchain")
TERMINAL = {"completed", "failed", "cancelled", "skipped", "unconfirmed"}
_TEXT = {"profile", "proposal_id", "event_type", "tx_hash", "document_hash", "engine"}
_NUMBERS = {"tasks", "employees", "generations", "generation", "fitness_score", "chain_id", "block_number"}
_METRICS = {"skill_match_score", "workload_variance", "makespan_days", "total_budget"}


def safe_metadata(values):
    result = {}
    for key, value in (values or {}).items():
        if key in _TEXT and isinstance(value, str):
            result[key] = value[:128]
        elif key in _NUMBERS and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            result[key] = value
        elif key in {"simulated", "valid"} and isinstance(value, bool):
            result[key] = value
        elif key == "generation_history" and isinstance(value, list):
            result[key] = [v for v in value[-200:] if isinstance(v, (float, int)) and math.isfinite(v)]
        elif key == "metrics" and isinstance(value, dict):
            result[key] = {k: v for k, v in value.items() if k in _METRICS and isinstance(v, (int, float)) and math.isfinite(v)}
    return result


class ServiceMonitor:
    def __init__(self, history_limit=60):
        self._lock = threading.RLock()
        self._active = {}
        self._recent = {s: deque(maxlen=history_limit) for s in SERVICES}
        self._counts = {s: {state: 0 for state in TERMINAL} for s in SERVICES}
        self.started_at = time.time()

    def _emit(self, record):
        sink = event_sink.get()
        if sink:
            sink(deepcopy(record))
        elif record["status"] in TERMINAL:
            # Exception text can include RPC credentials or document fragments.
            # Log operational facts only; the endpoint retains its existing error handling.
            level = logging.ERROR if record["status"] == "failed" else logging.WARNING if record["status"] == "unconfirmed" else logging.INFO
            logging.getLogger(f"eflow.service.{record['service']}").log(level,
                "%s %s (%s), %.0f ms", record["operation"], record["status"],
                record["run_id"][:8], record.get("duration_ms", 0),
            )

    def begin(self, service, operation, metadata=None, *, queued=False, origin=None):
        if service not in SERVICES:
            raise ValueError("Unknown monitored service")
        now = time.time()
        record = {"run_id": str(uuid4()), "service": service, "operation": operation,
                  "origin": origin or run_origin.get(), "status": "waiting" if queued else "running",
                  "submitted_at": now, "started_at": None if queued else now,
                  "completed_at": None, "metadata": safe_metadata(metadata)}
        with self._lock:
            self._active[record["run_id"]] = record
            self._emit(record)
        return record["run_id"]

    def update(self, run_id, metadata=None, *, running=False):
        with self._lock:
            record = self._active.get(run_id)
            if record is None:
                return
            if running and record["status"] == "waiting":
                record.update(status="running", started_at=time.time())
            record["metadata"].update(safe_metadata(metadata))
            self._emit(record)

    def finish(self, run_id, status="completed", result=None, error=None):
        with self._lock:
            record = self._active.pop(run_id, None)
            if record is None:
                return
            if is_dataclass(result):
                result = asdict(result)
            if isinstance(result, dict):
                record["metadata"].update(safe_metadata({**result, "profile": result.get("profile_used", record["metadata"].get("profile"))}))
                if result.get("error"):
                    status, error = "failed", "Service returned an error; see the activity log."
            if record["service"] == "blockchain" and record["operation"].startswith("anchor") and status == "failed" and record["metadata"].get("tx_hash") and record["metadata"].get("block_number") is None:
                status = "unconfirmed"
            now = time.time()
            record.update(status=status, completed_at=now,
                          duration_ms=round((now - (record["started_at"] or now)) * 1000, 1),
                          wait_ms=round(((record["started_at"] or now) - record["submitted_at"]) * 1000, 1))
            if error:
                record["error"] = error[:160]
            self._counts[record["service"]][status] += 1
            self._recent[record["service"]].appendleft(record)
            self._emit(record)

    def ingest(self, record, scope):
        """Accept events only from our child process; tie them to its execution."""
        service, run_id = record["service"], record["run_id"]
        if service not in SERVICES:
            return
        with self._lock:
            if record["status"] in TERMINAL:
                self._active.pop(run_id, None)
                self._counts[service][record["status"]] += 1
                self._recent[service].appendleft(deepcopy(record))
                self._emit(record)
            else:
                self._active[run_id] = {**deepcopy(record), "scope": scope}

    def close_scope(self, scope, *, cancelled=False):
        with self._lock:
            for record in list(self._active.values()):
                if record.get("scope") == scope:
                    self.finish(record["run_id"], "cancelled" if cancelled else "failed",
                                error="Inference worker stopped before this stage finished.")

    def snapshot(self):
        with self._lock:
            return {s: {"running": sum(r["service"] == s and r["status"] == "running" for r in self._active.values()),
                        "waiting": sum(r["service"] == s and r["status"] == "waiting" for r in self._active.values()),
                        "counts": dict(self._counts[s]),
                        "active_runs": [{k: deepcopy(v) for k, v in r.items() if k != "scope"} for r in self._active.values() if r["service"] == s],
                        "recent_runs": deepcopy(list(self._recent[s]))} for s in SERVICES}


monitor = ServiceMonitor()


def observe_sync(service, operation, function, *, metadata=None):
    """Reuse an executor admission record; otherwise observe a pipeline stage."""
    existing = current_run.get()
    owns = not (existing and existing[0] == service)
    run_id = monitor.begin(service, operation, metadata) if owns else existing[1]
    marker = current_run.set((service, run_id))
    monitor.update(run_id, metadata, running=True)
    try:
        result = function()
        if service == "laya" and isinstance(result, dict):
            monitor.update(run_id, {"engine": result.get("decisionLayer", {}).get("engine", "unknown")})
        if owns:
            monitor.finish(run_id, result=result)
        return result
    except Exception:
        if owns:
            monitor.finish(run_id, "failed", error="Service execution failed; see the activity log.")
        raise
    finally:
        current_run.reset(marker)


def update_current(metadata):
    record = current_run.get()
    if record:
        monitor.update(record[1], metadata)


def monitored_service(service, operation):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            return observe_sync(service, operation, lambda: function(*args, **kwargs))
        return wrapped
    return decorate


def record_skip(service, operation, reason):
    run_id = monitor.begin(service, operation)
    monitor.finish(run_id, "skipped", error=reason)


async def observed_executor(executor, slots, service, operation, function, *, metadata=None):
    """Track waiting before admission, and completion in the executing thread."""
    run_id = monitor.begin(service, operation, metadata, queued=True)
    future = None
    native_future = None
    acquired = False
    try:
        await slots.acquire()
        acquired = True
        context = copy_context()
        def execute():
            marker = current_run.set((service, run_id))
            monitor.update(run_id, running=True)
            try:
                result = function()
                monitor.finish(run_id, result=result)
                return result
            except Exception:
                monitor.finish(run_id, "failed", error="Service execution failed; see the activity log.")
                raise
            finally:
                current_run.reset(marker)
        native_future = executor.submit(context.run, execute)
        future = asyncio.wrap_future(native_future)
        # Caller cancellation must not turn a still-running native call into idle.
        # Hold its slot until actual completion and retrieve detached exceptions.
        def done(completed):
            slots.release()
            if not completed.cancelled():
                completed.exception()
        future.add_done_callback(done)
        acquired = False
        return await asyncio.shield(future)
    except BaseException:
        if future is None:
            monitor.finish(run_id, "cancelled", error="Request ended before execution.")
        elif native_future.cancel():
            monitor.finish(run_id, "cancelled", error="Request ended before execution.")
        raise
    finally:
        if acquired:
            slots.release()


def package_available(name):
    return importlib.util.find_spec(name) is not None
