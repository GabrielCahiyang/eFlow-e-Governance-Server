"""
Private Local LLM Backend Server — FastAPI + llama-cpp-python.

Exposes an Ollama-compatible REST API so the React frontend needs
minimal changes.  Models are GGUF files stored in ../models/ and
auto-downloaded from HuggingFace on first use.

All endpoints are served under the /controlpanelEflow/ prefix. The service
binds to loopback only and is reached remotely exclusively through the eFlow
gateway on port 8322. Every request must include
Authorization: Bearer <API_KEY>.

`server/start.py` supervises this AI process and the separate automatic tunnel
publisher. This module remains focused on the private model API and never owns
the eFlow gateway process.

The API key is read from the Supabase `app_config` table at startup
(key = 'llm_auth_key').  Run the SQL in README to create that row.

Endpoints (under /controlpanelEflow)
────────────────────────────────────
GET  /api/health        — liveness check
GET  /api/tags          — list available models (Ollama /api/tags format)
GET  /api/ps            — currently loaded model  (Ollama /api/ps format)
POST /api/chat          — streaming chat completion (NDJSON, Ollama format)
POST /api/jobs          — enqueue an eFlow non-streaming chat job
GET  /api/jobs/{id}     — poll an owner-scoped queued job
POST /api/download      — trigger model download
GET  /AUTHKEY           — fetch API key (no auth required)
GET  /api/authkey       — alias for /AUTHKEY
PUT  /api/authkey       — update auth key in Supabase app_config
"""

import os
import json
import time
import asyncio
import logging
import aiohttp
from http_client import get_session, close_session
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from job_queue import AiJobQueue, QueueCapacityError
from system_metrics import read_system_metrics
from service_status import service_status
from tunnel_control import request_tunnel_rotation, read_tunnel_state

from request_validation import validate_chat_request as _validate_chat_body
from model_registry import (
    get_model,
    list_all_models,
    download_model,
)
from server_logging import (
    LogBuffer,
    SSEManager,
    SupabaseLogWriter,
    BufferAndBroadcastHandler,
    make_entry,
    LOG_TYPE_CHAT,
)

# ── Load environment variables ────────────────────────────────────────
# This is a local, file-backed host.  A parent shell can carry empty VITE_
# variables (for example after a frontend restart); let the project .env file
# provide the backend credentials in that case.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

SUPABASE_URL: str = os.getenv("VITE_SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "VITE_SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env!"
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

# ── Server-wide logging infrastructure ────────────────────────────────
log_buffer = LogBuffer(maxlen=500)
sse_manager = SSEManager()
supabase_log_writer = SupabaseLogWriter(
    supabase_url=SUPABASE_URL,
    service_role_key=SUPABASE_SERVICE_ROLE_KEY,
)

# Attach the custom handler to the root logger so we capture everything
# (uvicorn, our app, llama-cpp, etc.)
_handler = BufferAndBroadcastHandler(
    log_buffer=log_buffer,
    sse_manager=sse_manager,
    firebase_writer=supabase_log_writer,  # param name kept for compat
)
_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
logging.getLogger().addHandler(_handler)

# Uvicorn loggers propagate to the root logger. Attaching the same handler to
# both levels duplicates every access and lifecycle entry in the dashboard.

logger.info(f"Supabase URL: {SUPABASE_URL}")
SERVER_STARTED_AT = time.time()


# ── API Key Cache (to avoid hammering Supabase on every request) ──────
_api_key_cache = {"value": None, "timestamp": 0, "ttl_seconds": 300}  # 5 min TTL


async def get_cached_api_key() -> Optional[str]:
    """Fetch the LLM auth key from Supabase app_config table (cached)."""
    current_time = time.time()

    # Return cached key if still valid
    if (
        _api_key_cache["value"]
        and (current_time - _api_key_cache["timestamp"]) < _api_key_cache["ttl_seconds"]
    ):
        return _api_key_cache["value"]

    # Fetch from Supabase via PostgREST REST API
    try:
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/app_config?key=eq.llm_auth_key&select=value"
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        }
        session = await get_session()
        async with session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data and isinstance(data, list) and data[0].get("value"):
                    api_key = data[0]["value"].strip()
                    _api_key_cache["value"] = api_key
                    _api_key_cache["timestamp"] = current_time
                    logger.debug("Fetched auth key from Supabase app_config")
                    return api_key
            else:
                body = await resp.text()
                logger.error(f"Supabase app_config fetch failed {resp.status}: {body[:200]}")
    except Exception as e:
        logger.error(f"Failed to fetch API key from Supabase: {e}")

    # Return stale cached value as last resort
    if _api_key_cache["value"]:
        logger.warning("Using stale cached API key")
        return _api_key_cache["value"]

    return None


# ── Supabase API-key auth middleware ──────────────────────────────────


class SupabaseKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    Reject any request that does not carry
    Authorization: Bearer <llm_auth_key from Supabase app_config>.
    """

    async def dispatch(self, request: Request, call_next):
        # Let CORS preflight through — browsers send OPTIONS without auth
        if request.method == "OPTIONS":
            return await call_next(request)

        # Allow unauthenticated access to auth key, health, and log stream endpoints
        if request.method == "GET" and request.url.path.endswith(("/AUTHKEY", "/api/authkey", "/api/health", "/api/logs/stream")):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        expected_key = await get_cached_api_key()

        if not expected_key:
            return JSONResponse(
                {"error": "Unauthorized – API key not available"},
                status_code=401,
            )

        if not auth_header.startswith("Bearer ") or auth_header[7:].strip() != expected_key:
            return JSONResponse(
                {"error": "Unauthorized – invalid or missing API key"},
                status_code=401,
            )
        return await call_next(request)


# ── Global model state ────────────────────────────────────────────────


from inference_worker import InferenceWorker

manager = InferenceWorker()
_stream_channels: dict[str, asyncio.Queue] = {}

# ── Disabled models set (controlled from the frontend) ────────────────
disabled_models: set[str] = set()

# ── FastAPI app ───────────────────────────────────────────────────────

ROUTE_PREFIX = "/controlpanelEflow"


@asynccontextmanager
async def lifespan(app: FastAPI):
    _handler.bind_loop(asyncio.get_running_loop())
    await supabase_log_writer.start()
    logger.info("LLM Backend starting …")
    logger.info(f"Route prefix : {ROUTE_PREFIX}")
    logger.info(f"Registered models: {[m.tag for m in list_all_models()]}")
    # Pre-warm the auth key cache at startup
    key = await get_cached_api_key()
    if key:
        logger.info("Auth key loaded from Supabase app_config.")
    else:
        logger.warning(
            "Could not load auth key from Supabase. "
            "Ensure the app_config table has a row with key='llm_auth_key'."
        )
    await job_queue.start()
    await service_status.start()
    logger.info("FIFO AI job worker started.")
    yield
    await job_queue.stop(drain=False)
    await manager.close()
    await service_status.stop()
    logger.info("LLM Backend shut down.")
    await supabase_log_writer.close()
    await close_session()


app = FastAPI(title="eFlow Server Side", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth middleware — applied after CORS so preflight OPTIONS still works
app.add_middleware(SupabaseKeyAuthMiddleware)

# All routes go on a sub-router mounted at /controlpanelEflow
router = APIRouter()


# ── Health ────────────────────────────────────────────────────────────


@router.get("/api/health")
async def health():
    return {"status": "ok"}


@router.get("/api/operations")
async def operations_snapshot():
    """Live operational facts used by the local server dashboard."""
    hardware, queue = await asyncio.gather(
        asyncio.to_thread(read_system_metrics, SERVER_STARTED_AT, manager.pid),
        job_queue.overview(),
    )
    return {
        **hardware,
        "queue": queue,
        "inference": manager.overview(),
        "services": service_status.snapshot(),
        "model": {
            "loaded": manager.loaded_tag,
            "registered": len(list_all_models()),
            "enabled": len(list_all_models()) - len(disabled_models),
        },
    }


@router.get("/api/tunnel/status")
async def tunnel_status():
    try:
        return await read_tunnel_state(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    except Exception as exc:
        logger.warning("Could not read published tunnel state: %s", exc)
        return JSONResponse(
            {"error": "Could not read Cloudflare state from Supabase"},
            status_code=503,
        )


@router.post("/api/tunnel/rotate")
async def rotate_tunnel():
    requested_at = request_tunnel_rotation()
    logger.warning("Cloudflare Quick Tunnel rotation requested from dashboard")
    return JSONResponse(
        {
            "accepted": True,
            "requested_at": requested_at,
            "message": "A fresh Cloudflare endpoint is being generated and will be published automatically.",
        },
        status_code=202,
    )


# ── Model Toggle (enable/disable) ────────────────────────────────────


@router.put("/api/models/toggle")
async def toggle_model(request: Request):
    """Enable or disable a model. Disabled models reject chat requests."""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("AI request must be an object")
        _validate_chat_body(body)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    model_tag = body.get("model", "")
    enabled = body.get("enabled", True)

    entry = get_model(model_tag)
    if not entry:
        return JSONResponse({"error": f"Unknown model: {model_tag}"}, status_code=404)

    if enabled:
        disabled_models.discard(model_tag)
        logger.info(f"Model {model_tag} enabled via control panel")
    else:
        disabled_models.add(model_tag)
        logger.info(f"Model {model_tag} disabled via control panel")

    return {
        "model": model_tag,
        "enabled": enabled,
        "disabled_models": list(disabled_models),
    }


@router.get("/api/models/status")
async def models_status():
    """Return the current enabled/disabled state of all models."""
    return {
        "disabled_models": list(disabled_models),
    }


# ── Server Log Stream (SSE) ───────────────────────────────────────────


@router.get("/api/logs/stream")
async def log_stream():
    """Server-Sent Events endpoint that streams live server logs."""
    queue = sse_manager.subscribe()

    async def event_generator():
        # Send backlog first so the client has context
        for entry in log_buffer.snapshot():
            yield f"data: {json.dumps(entry)}\n\n"

        # Then stream live
        try:
            while True:
                entry = await queue.get()
                yield f"data: {json.dumps(entry)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            sse_manager.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Get / Update Auth Key ─────────────────────────────────────────────


@router.get("/AUTHKEY")
async def get_auth_key():
    """Returns the LLM API key from Supabase app_config."""
    api_key = await get_cached_api_key()
    if not api_key:
        return JSONResponse(
            {"error": "Failed to retrieve API key from Supabase app_config"},
            status_code=500,
        )
    return {"api_key": api_key}


@router.get("/api/authkey")
async def get_auth_key_api():
    """Alias for /AUTHKEY to support /api proxy paths."""
    return await get_auth_key()


@router.put("/api/authkey")
async def update_auth_key(request: Request):
    """Update the API key in Supabase app_config table."""
    body = await request.json()
    new_key = body.get("api_key", "")
    if not new_key or not isinstance(new_key, str) or len(new_key) < 4:
        return JSONResponse(
            {"error": "Invalid API key — must be at least 4 characters"},
            status_code=400,
        )

    try:
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/app_config?key=eq.llm_auth_key"
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }
        payload = {"value": new_key, "updated_at": "now()"}
        session = await get_session()
        async with session.patch(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status >= 400:
                body_text = await resp.text()
                logger.error(f"Failed to update auth key in Supabase: {resp.status} {body_text}")
                return JSONResponse(
                    {"error": f"Supabase write failed: {resp.status}"},
                    status_code=500,
                )

        # Invalidate cache so the new key is used immediately
        _api_key_cache["value"] = new_key
        _api_key_cache["timestamp"] = time.time()
        logger.info("Auth key updated successfully in Supabase app_config")

        return {"status": "ok", "message": "Auth key updated"}
    except Exception as e:
        logger.exception("Failed to update auth key")
        return JSONResponse({"error": str(e)}, status_code=500)


# ── List models (Ollama /api/tags format) ─────────────────────────────


@router.get("/api/tags")
async def list_models():
    models_out = []
    for entry in list_all_models():
        models_out.append(
            {
                "name": entry.tag,
                "model": entry.tag,
                "modified_at": "",
                "size": entry.size_bytes,
                "digest": "",
                "details": {
                    "parent_model": "",
                    "format": "gguf",
                    "family": entry.family,
                    "families": [entry.family] if entry.family else None,
                    "parameter_size": entry.parameter_size,
                    "quantization_level": entry.quantization,
                },
                # Extra fields for the frontend
                "downloaded": entry.is_downloaded,
            }
        )
    return {"models": models_out}


# ── Running models (Ollama /api/ps format) ────────────────────────────


@router.get("/api/ps")
async def running_models():
    models_out = []
    if manager.loaded_tag:
        entry = get_model(manager.loaded_tag)
        if entry:
            models_out.append(
                {
                    "name": entry.tag,
                    "model": entry.tag,
                    "size": entry.size_bytes,
                    "size_vram": entry.size_bytes,
                    "expires_at": "",
                }
            )
    return {"models": models_out}


# ── Download model ────────────────────────────────────────────────────


@router.post("/api/download")
async def trigger_download(request: Request):
    body = await request.json()
    tag = body.get("model", "")
    entry = get_model(tag)
    if not entry:
        return JSONResponse({"error": f"Unknown model: {tag}"}, status_code=404)

    try:
        await asyncio.to_thread(download_model, entry)
        return {"status": "ok", "model": tag, "path": str(entry.local_path)}
    except Exception as e:
        logger.exception(f"Download failed for {tag}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Chat completion (Ollama /api/chat format) ─────────────────────────


@router.post("/api/chat")
@router.post("/api/chat/{model_tag:path}")
async def chat(request: Request, model_tag: Optional[str] = None):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("AI request must be an object")
        _validate_chat_body(body)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    model_tag = model_tag or body.get("model", "")
    messages = body.get("messages", [])
    stream = body.get("stream", True)

    entry = get_model(model_tag)
    if not entry:
        return JSONResponse(
            {"error": f"Unknown model: {model_tag}"},
            status_code=404,
        )

    # Check if model is disabled via control panel
    if model_tag in disabled_models:
        return JSONResponse(
            {"error": f"Model {model_tag} is currently disabled"},
            status_code=403,
        )

    try:
        owner_id = request.headers.get("X-eFlow-User-Id", "").strip() or f"legacy-local-{uuid4()}"
        stream_id = str(uuid4()) if stream else None
        if stream_id:
            _stream_channels[stream_id] = asyncio.Queue(maxsize=16)
        payload = {**body, "model": model_tag, "stream": False}
        if stream_id:
            payload["_stream_id"] = stream_id
        snapshot = await job_queue.submit(owner_id, payload, request_id=body.get("request_id") if not stream else None)
    except QueueCapacityError as exc:
        if stream_id:
            _stream_channels.pop(stream_id, None)
        return JSONResponse({"error": str(exc)}, status_code=429, headers={"Retry-After": "5"})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if stream_id:
        return StreamingResponse(_queued_stream(snapshot, owner_id, stream_id, model_tag),
                                 media_type="application/x-ndjson")
    result = await job_queue.wait(snapshot["job_id"], owner_id)
    if not result or result["status"] == "failed":
        return JSONResponse({"error": (result or {}).get("error") or "Queued AI request failed"}, status_code=500)
    return result["result"]


async def _process_queued_chat(body):
    if body["model"] in disabled_models:
        raise PermissionError("This model is disabled")
    channel = _stream_channels.get(body.get("_stream_id"))
    async def on_chunk(chunk):
        await asyncio.wait_for(channel.put(chunk), timeout=30)
    try:
        result = await manager.execute(body, on_chunk=on_chunk if channel else None)
        elapsed_ms = result.get("total_duration", 0) / 1e6
        entry = make_entry(message=f"Chat completion: {body['model']} — {result.get('eval_count', 0)} tokens in {elapsed_ms:.0f}ms",
                           source="chat", log_type=LOG_TYPE_CHAT,
                           extra={"model": body["model"], "tokens": result.get("eval_count", 0),
                                  "latency_ms": round(elapsed_ms), "stream": channel is not None,
                                  "timings_ms": result.get("timings_ms")})
        log_buffer.push(entry)
        await sse_manager.broadcast(entry)
        supabase_log_writer.enqueue(entry)
        if channel:
            await asyncio.wait_for(channel.put({"model": body["model"], "done": True,
                                                "eval_count": result.get("eval_count", 0),
                                                "total_duration": result.get("total_duration", 0)}), timeout=30)
        return result
    except asyncio.TimeoutError:
        raise RuntimeError("AI execution exceeded its deadline or the stream stopped reading. Retry with a smaller request.")
    except BaseException as exc:
        if channel:
            if channel.full():
                channel.get_nowait()
            channel.put_nowait({"model": body["model"], "done": True, "error": str(exc) or "Request cancelled"})
        raise


job_queue = AiJobQueue(_process_queued_chat,
                       max_waiting_jobs=int(os.getenv("EFLOW_QUEUE_CAPACITY", "32")),
                       max_jobs_per_owner=int(os.getenv("EFLOW_QUEUE_PER_USER", "2")))


def _request_owner(request):
    owner_id = request.headers.get("X-eFlow-User-Id", "").strip()
    if not owner_id:
        raise ValueError("X-eFlow-User-Id is required for queued jobs")
    return owner_id


@router.post("/api/jobs")
async def enqueue_chat_job(request: Request):
    try:
        owner_id = _request_owner(request)
        body = await request.json()
        _validate_chat_body(body)
        if body.get("stream") is True:
            return JSONResponse({"error": "Queued jobs support non-streaming requests only"}, status_code=400)
        if not get_model(body.get("model", "")):
            return JSONResponse({"error": "Unknown model"}, status_code=404)
        if body["model"] in disabled_models:
            return JSONResponse({"error": "This model is disabled"}, status_code=403)
        snapshot = await job_queue.submit(owner_id, {**body, "stream": False}, request_id=body.get("request_id"))
        return JSONResponse(snapshot, status_code=202)
    except QueueCapacityError as exc:
        return JSONResponse({"error": str(exc)}, status_code=429, headers={"Retry-After": "5"})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get("/api/jobs/{job_id}")
async def get_chat_job(job_id: str, request: Request):
    try:
        snapshot = await job_queue.snapshot(job_id, _request_owner(request))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return snapshot or JSONResponse({"error": "AI job not found"}, status_code=404)


@router.delete("/api/jobs/{job_id}")
async def cancel_chat_job(job_id: str, request: Request):
    try:
        snapshot = await job_queue.cancel(job_id, _request_owner(request))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return snapshot or JSONResponse({"error": "AI job not found"}, status_code=404)


@router.delete("/api/operations/jobs/{job_id}")
async def cancel_operation_job(job_id: str):
    snapshot = await job_queue.cancel(job_id)
    return snapshot or JSONResponse({"error": "AI job not found"}, status_code=404)


async def _queued_stream(snapshot, owner_id, stream_id, model_tag):
    channel = _stream_channels[stream_id]
    finished = False
    try:
        yield json.dumps({"model": model_tag, "done": False, "status": snapshot["status"],
                          "job_id": snapshot["job_id"], "position": snapshot["position"]}) + "\n"
        while True:
            try:
                chunk = await asyncio.wait_for(channel.get(), timeout=15)
            except asyncio.TimeoutError:
                current = await job_queue.snapshot(snapshot["job_id"], owner_id)
                if current and current["status"] == "failed":
                    finished = True
                    yield json.dumps({"model": model_tag, "done": True, "error": current["error"]}) + "\n"
                    return
                yield json.dumps({"model": model_tag, "done": False, "status": (current or {}).get("status", "queued"),
                                  "position": (current or {}).get("position")}) + "\n"
                continue
            if chunk.get("done"):
                finished = True
            yield json.dumps(chunk) + "\n"
            if chunk.get("done"):
                return
    finally:
        if not finished:
            await job_queue.cancel(snapshot["job_id"], owner_id)
        _stream_channels.pop(stream_id, None)


# ── Mount router under prefix ─────────────────────────────────────────

app.include_router(router, prefix=ROUTE_PREFIX)

# ── Mount feature sub-routers ─────────────────────────────────────────

from routers.optimization import router as optimization_router  # noqa: E402
from routers.blockchain import router as blockchain_router       # noqa: E402
from routers.proposals import router as proposals_router         # noqa: E402

app.include_router(optimization_router, prefix=ROUTE_PREFIX)
app.include_router(blockchain_router, prefix=ROUTE_PREFIX)
app.include_router(proposals_router, prefix=ROUTE_PREFIX)


# ── Main ──────────────────────────────────────────────────────────────


if __name__ == "__main__":
    # A lightweight entry point prevents Windows spawn from importing the API
    # (and its logging/environment state) inside the inference child.
    import sys
    os.execv(sys.executable, [sys.executable, str(Path(__file__).with_name("run_api.py"))])
