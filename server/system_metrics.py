"""Live machine telemetry for the eFlow server operations dashboard."""

from __future__ import annotations

import csv
import os
import subprocess
import time
import threading
from io import StringIO
from typing import Any

import psutil

_cache = None
_cache_key = None
_cache_time = 0.0
_lock = threading.Lock()
_processes = {os.getpid(): psutil.Process()}


_GPU_QUERY = (
    "name,utilization.gpu,memory.used,memory.total,temperature.gpu,"
    "power.draw,power.limit,fan.speed"
)


def _number(value: str) -> float | None:
    cleaned = value.strip()
    if not cleaned or cleaned.upper() in {"N/A", "[N/A]", "NOT SUPPORTED"}:
        return None
    try:
        return round(float(cleaned), 1)
    except ValueError:
        return None


def _percentage(used: float | None, total: float | None) -> float | None:
    if used is None or total in {None, 0}:
        return None
    return round((used / total) * 100, 1)


def _read_gpus() -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={_GPU_QUERY}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            ),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    if result.returncode != 0:
        return []

    gpus: list[dict[str, Any]] = []
    for index, row in enumerate(csv.reader(StringIO(result.stdout))):
        if len(row) < 8:
            continue
        memory_used = _number(row[2])
        memory_total = _number(row[3])
        gpus.append(
            {
                "index": index,
                "name": row[0].strip(),
                "utilization_percent": _number(row[1]),
                "memory_used_mb": memory_used,
                "memory_total_mb": memory_total,
                "memory_percent": _percentage(memory_used, memory_total),
                "temperature_c": _number(row[4]),
                "power_draw_w": _number(row[5]),
                "power_limit_w": _number(row[6]),
                "fan_percent": _number(row[7]),
            }
        )
    return gpus


def read_system_metrics(started_at: float, worker_pid: int | None = None) -> dict[str, Any]:
    global _cache, _cache_key, _cache_time
    with _lock:
        key = (started_at, worker_pid)
        if _cache is not None and key == _cache_key and time.monotonic() - _cache_time < 2.5:
            return _cache
        _cache = _capture_metrics(started_at, worker_pid)
        _cache_key = key
        _cache_time = time.monotonic()
        return _cache


def _capture_metrics(started_at, worker_pid):
    """Return a serializable snapshot without inventing unavailable values."""
    memory = psutil.virtual_memory()
    for pid in list(_processes):
        if pid not in {os.getpid(), worker_pid}:
            _processes.pop(pid)
    if worker_pid and worker_pid not in _processes:
        try:
            _processes[worker_pid] = psutil.Process(worker_pid)
        except psutil.Error:
            pass
    process_memory = process_cpu = 0.0
    for process in list(_processes.values()):
        try:
            process_memory += process.memory_info().rss / (1024 * 1024)
            process_cpu += process.cpu_percent(interval=None)
        except psutil.Error:
            pass
    gpus = _read_gpus()
    return {
        "captured_at": time.time(),
        "uptime_seconds": max(0, round(time.time() - started_at)),
        "system": {
            "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
            "memory_percent": round(memory.percent, 1),
            "memory_used_gb": round(memory.used / (1024**3), 1),
            "memory_total_gb": round(memory.total / (1024**3), 1),
        },
        "process": {
            "cpu_percent": round(process_cpu, 1),
            "memory_mb": round(process_memory, 1),
        },
        "gpu_available": bool(gpus),
        "gpus": gpus,
    }
