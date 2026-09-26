"""Public, JWT-protected AI gateway for the Cloudflare tunnel.

The model API remains private on 127.0.0.1:8321. This small gateway owns
127.0.0.1:8322 when a full eFlow gateway is not already running on the AI
host. It validates the caller's Supabase session, checks that the eFlow
profile is active, then adds the private model key while proxying only the
AI job routes.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SUPABASE_URL = (
    os.getenv("SUPABASE_URL", "").strip()
    or os.getenv("VITE_SUPABASE_URL", "").strip()
).rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
INTERNAL_AI_BASE_URL = os.getenv(
    "EFLOW_INTERNAL_AI_BASE_URL",
    "http://127.0.0.1:8321/controlpanelEflow/api",
).rstrip("/")
AI_TIMEOUT_SECONDS = float(os.getenv("EFLOW_AI_TIMEOUT_SECONDS", "7200"))

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "SUPABASE_URL (or VITE_SUPABASE_URL) and SUPABASE_SERVICE_ROLE_KEY "
        "must be set in .env."
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
logger = logging.getLogger("eflow.public_ai_gateway")


def _allowed_origins() -> list[str]:
    raw = os.getenv("EFLOW_ALLOWED_ORIGINS", "*")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["*"]


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1, max_length=500_000)


class ChatRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    stream: bool = False
    request_id: str | None = Field(default=None, min_length=1, max_length=100)


class InternalAiKeyCache:
    """Server-only cache for the key shared with the private model API."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl_seconds = ttl_seconds
        self._value: str | None = None
        self._loaded_at = 0.0

    async def get(self) -> str:
        now = time.monotonic()
        if self._value and now - self._loaded_at < self._ttl_seconds:
            return self._value

        headers = _service_headers()
        params = {"key": "eq.llm_auth_key", "select": "value"}
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=8)
            ) as session:
                async with session.get(
                    f"{SUPABASE_URL}/rest/v1/app_config",
                    params=params,
                    headers=headers,
                ) as response:
                    if response.status != 200:
                        detail = (await response.text())[:240]
                        raise RuntimeError(
                            f"Could not read the private AI key ({response.status}): {detail}"
                        )
                    rows = await response.json()
        except (aiohttp.ClientError, TimeoutError) as exc:
            if self._value:
                logger.warning("Using the cached private AI key after a Supabase error")
                return self._value
            raise RuntimeError("Could not reach Supabase for the private AI key") from exc

        value = str((rows or [{}])[0].get("value") or "").strip()
        if not value:
            raise RuntimeError("app_config.llm_auth_key is missing or empty")

        self._value = value
        self._loaded_at = now
        return value


internal_ai_key = InternalAiKeyCache()


def _service_headers() -> dict[str, str]:
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
    }


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid Supabase session is required.",
        )
    return token.strip()


async def _require_active_user(request: Request) -> str:
    """Validate the bearer token with Supabase and require an active profile."""
    token = _bearer_token(request)
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {token}",
                },
            ) as response:
                if response.status != 200:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired Supabase session.",
                    )
                auth_user: dict[str, Any] = await response.json()

            user_id = str(auth_user.get("id") or "").strip()
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired Supabase session.",
                )

            async with session.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"select": "id,is_active", "id": f"eq.{user_id}"},
                headers=_service_headers(),
            ) as response:
                if response.status != 200:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="The eFlow account could not be verified.",
                    )
                profiles = await response.json()
    except aiohttp.ClientError as exc:
        logger.warning("Supabase user validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The eFlow account could not be verified.",
        ) from exc

    profile = profiles[0] if isinstance(profiles, list) and profiles else None
    if not profile or profile.get("is_active") is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This eFlow account is inactive.",
        )
    return user_id


async def _proxy_ai_request(
    method: str,
    path: str,
    request: Request,
    *,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 30,
) -> Response:
    user_id = await _require_active_user(request)
    try:
        key = await internal_ai_key.get()
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout_seconds, connect=10),
        ) as session:
            async with session.request(
                method,
                f"{INTERNAL_AI_BASE_URL}/{path.lstrip('/')}",
                json=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "X-eFlow-User-Id": user_id,
                },
            ) as upstream:
                content = await upstream.read()
                content_type = upstream.headers.get("content-type", "application/json")
                return Response(
                    content=content,
                    status_code=upstream.status,
                    media_type=content_type.split(";", 1)[0],
                )
    except HTTPException:
        raise
    except (aiohttp.ClientError, TimeoutError) as exc:
        logger.warning("Private AI proxy request failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The local AI service is offline.",
        ) from exc
    except RuntimeError as exc:
        logger.error("Embedded AI gateway configuration failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI gateway is not configured.",
        ) from exc


app = FastAPI(title="eFlow Embedded AI Gateway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/controlpanelEflow/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "eflow-control-gateway"}


@app.post("/controlpanelEflow/api/ai/jobs")
async def enqueue_job(payload: ChatRequest, request: Request) -> Response:
    if payload.stream:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Queued AI jobs cannot stream.",
        )
    return await _proxy_ai_request(
        "POST",
        "jobs",
        request,
        payload=payload.model_dump(),
    )


@app.get("/controlpanelEflow/api/ai/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> Response:
    return await _proxy_ai_request("GET", f"jobs/{job_id}", request)


@app.post("/controlpanelEflow/api/ai/chat")
async def proxy_chat(payload: ChatRequest, request: Request) -> Response:
    return await _proxy_ai_request(
        "POST",
        "chat",
        request,
        payload=payload.model_dump(),
        timeout_seconds=AI_TIMEOUT_SECONDS,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "public_gateway:app",
        host=os.getenv("EFLOW_EMBEDDED_GATEWAY_HOST", "127.0.0.1"),
        port=int(os.getenv("EFLOW_EMBEDDED_GATEWAY_PORT", "8322")),
        log_level="info",
    )
