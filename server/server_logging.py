"""
Server Logging — ring buffer, Supabase persistence, and SSE broadcast.

Components
──────────
LogBuffer         Thread-safe ring buffer holding recent log entries.
SupabaseLogWriter Pushes significant log entries to the Supabase
                  `server_logs` table via the REST API using the
                  service-role key (bypasses RLS).
SSEManager        Manages connected SSE clients and broadcasts new entries.
"""

import asyncio
import logging
import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import aiohttp

# ── Log entry type ────────────────────────────────────────────────────

LOG_TYPE_STARTUP  = "startup"
LOG_TYPE_SHUTDOWN = "shutdown"
LOG_TYPE_MODEL    = "model_load"
LOG_TYPE_CHAT     = "chat_request"
LOG_TYPE_AUTH     = "auth"
LOG_TYPE_HEALTH   = "health"
LOG_TYPE_ERROR    = "error"
LOG_TYPE_GENERAL  = "general"

# Regex patterns used to auto-classify log messages
_PATTERNS: list[tuple[str, str]] = [
    (r"LLM Backend starting",            LOG_TYPE_STARTUP),
    (r"Route prefix",                    LOG_TYPE_STARTUP),
    (r"Registered models",               LOG_TYPE_STARTUP),
    (r"Application startup complete",    LOG_TYPE_STARTUP),
    (r"Uvicorn running on",              LOG_TYPE_STARTUP),
    (r"Started server process",          LOG_TYPE_STARTUP),
    (r"Waiting for application startup", LOG_TYPE_STARTUP),
    (r"Supabase",                        LOG_TYPE_STARTUP),
    (r"Auth Key",                        LOG_TYPE_STARTUP),
    (r"LLM Backend shut down",           LOG_TYPE_SHUTDOWN),
    (r"Loading model",                   LOG_TYPE_MODEL),
    (r"Model .+ loaded",                 LOG_TYPE_MODEL),
    (r"Model .+ already loaded",         LOG_TYPE_MODEL),
    (r"Unloading model",                 LOG_TYPE_MODEL),
    (r"Downloading",                     LOG_TYPE_MODEL),
    (r"POST .*/api/chat",                LOG_TYPE_CHAT),
    (r"Unauthorized",                    LOG_TYPE_AUTH),
    (r"401",                             LOG_TYPE_AUTH),
    (r"GET .*/api/health",               LOG_TYPE_HEALTH),
    (r"GET .*/api/tags",                 LOG_TYPE_HEALTH),
    (r"GET .*/api/ps",                   LOG_TYPE_HEALTH),
    (r"error|exception|traceback",       LOG_TYPE_ERROR),
]

_compiled_patterns = [(re.compile(pat, re.IGNORECASE), typ) for pat, typ in _PATTERNS]


def classify_log(message: str) -> str:
    """Return a log-type string for the given message."""
    for regex, log_type in _compiled_patterns:
        if regex.search(message):
            return log_type
    return LOG_TYPE_GENERAL


def _level_from_message(message: str) -> str:
    """Try to extract a log level from a raw message string."""
    upper = message.upper()
    if "ERROR" in upper or "EXCEPTION" in upper:
        return "ERROR"
    if "WARNING" in upper or "WARN" in upper:
        return "WARNING"
    return "INFO"


# ── Log entry dict factory ────────────────────────────────────────────

def make_entry(
    message: str,
    level: str = "INFO",
    source: str = "server",
    log_type: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Create a log-entry dict."""
    now = datetime.now(timezone.utc)
    entry: dict = {
        "timestamp": now.isoformat(),
        "level": level.upper(),
        "message": message,
        "source": source,
        "type": log_type or classify_log(message),
    }
    if extra:
        entry["extra"] = extra
    return entry


# ── LogBuffer ─────────────────────────────────────────────────────────

class LogBuffer:
    """Thread-safe ring buffer that keeps the last *maxlen* log entries."""

    def __init__(self, maxlen: int = 500):
        self._buf: deque[dict] = deque(maxlen=maxlen)

    def push(self, entry: dict) -> None:
        self._buf.append(entry)

    def snapshot(self) -> list[dict]:
        """Return a copy of all buffered entries (oldest → newest)."""
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)


# ── SSEManager ────────────────────────────────────────────────────────

class SSEManager:
    """Manages async queues for connected SSE clients."""

    def __init__(self):
        self._clients: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._clients.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._clients.remove(q)
        except ValueError:
            pass

    async def broadcast(self, entry: dict) -> None:
        dead: list[asyncio.Queue] = []
        for q in self._clients:
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._clients.remove(q)

    @property
    def client_count(self) -> int:
        return len(self._clients)


# ── SupabaseLogWriter ─────────────────────────────────────────────────

# Which log types are "meaningful" and worth persisting to Supabase
_PERSIST_TYPES = {
    LOG_TYPE_STARTUP,
    LOG_TYPE_SHUTDOWN,
    LOG_TYPE_MODEL,
    LOG_TYPE_CHAT,
    LOG_TYPE_AUTH,
    LOG_TYPE_ERROR,
}


class SupabaseLogWriter:
    """
    Pushes significant log entries to the Supabase `server_logs` table
    via the PostgREST REST API using the service-role key.

    Table schema (run once in Supabase SQL editor):

        CREATE TABLE IF NOT EXISTS server_logs (
            id          BIGSERIAL PRIMARY KEY,
            timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            level       TEXT NOT NULL,
            message     TEXT NOT NULL,
            source      TEXT DEFAULT 'server',
            type        TEXT DEFAULT 'general',
            extra       JSONB
        );

        ALTER TABLE server_logs ENABLE ROW LEVEL SECURITY;
        -- Only service role can insert/select (the LLM server uses service role key)
        CREATE POLICY "service_role_only" ON server_logs
            USING (auth.role() = 'service_role');
    """

    def __init__(self, supabase_url: str, service_role_key: str):
        self._base_url = supabase_url.rstrip("/")
        self._key = service_role_key
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={
                "apikey": self._key,
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            })
        return self._session

    async def write(self, entry: dict) -> None:
        """Fire-and-forget insert of a single log entry into server_logs."""
        log_type = entry.get("type", LOG_TYPE_GENERAL)
        if log_type not in _PERSIST_TYPES:
            return  # skip health polls etc.

        if not self._base_url or not self._key:
            return  # not configured

        try:
            payload = {
                "timestamp": entry.get("timestamp"),
                "level":     entry.get("level", "INFO"),
                "message":   entry.get("message", ""),
                "source":    entry.get("source", "server"),
                "type":      log_type,
                "extra":     entry.get("extra"),
            }
            url = f"{self._base_url}/rest/v1/server_logs"
            session = await self._get_session()
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    print(f"[SupabaseLogWriter] POST {resp.status}: {body[:200]}")
        except Exception as exc:
            print(f"[SupabaseLogWriter] Error: {exc}")

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


# Keep a type alias so main.py import doesn't break
FirebaseLogWriter = SupabaseLogWriter


# ── Custom logging.Handler ────────────────────────────────────────────

class BufferAndBroadcastHandler(logging.Handler):
    """
    A stdlib logging handler that:
      1. Pushes every record into the LogBuffer
      2. Schedules an SSE broadcast to all connected clients
      3. Schedules a Supabase write for significant records
    """

    def __init__(
        self,
        log_buffer: LogBuffer,
        sse_manager: SSEManager,
        firebase_writer: Optional[SupabaseLogWriter] = None,
        level: int = logging.DEBUG,
    ):
        super().__init__(level)
        self.log_buffer = log_buffer
        self.sse_manager = sse_manager
        self.firebase_writer = firebase_writer  # name kept for compatibility

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            entry = make_entry(
                message=msg,
                level=record.levelname,
                source=record.name,
            )

            self.log_buffer.push(entry)

            # Schedule broadcast + Supabase write on the running event loop
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.sse_manager.broadcast(entry))
                if self.firebase_writer:
                    loop.create_task(self.firebase_writer.write(entry))
            except RuntimeError:
                # No running event loop (e.g. during startup before uvicorn)
                pass
        except Exception:
            self.handleError(record)
