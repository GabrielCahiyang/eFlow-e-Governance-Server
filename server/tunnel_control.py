"""Dashboard-facing Cloudflare state and rotation control."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp


ROTATION_REQUEST_PATH = Path(__file__).resolve().parent / ".tunnel-rotate.request"
TUNNEL_CONFIG_KEYS = (
    "ai_endpoint",
    "ai_endpoint_status",
    "ai_endpoint_status_message",
    "ai_endpoint_heartbeat",
)


def request_tunnel_rotation() -> str:
    """Signal the separate tunnel supervisor to replace the Quick Tunnel."""
    requested_at = datetime.now(timezone.utc).isoformat()
    temporary_path = ROTATION_REQUEST_PATH.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps({"requested_at": requested_at}),
        encoding="utf-8",
    )
    temporary_path.replace(ROTATION_REQUEST_PATH)
    return requested_at


def consume_tunnel_rotation_request() -> bool:
    if not ROTATION_REQUEST_PATH.exists():
        return False
    try:
        ROTATION_REQUEST_PATH.unlink()
    except FileNotFoundError:
        return False
    return True


async def read_tunnel_state(
    supabase_url: str,
    service_role_key: str,
) -> dict[str, Any]:
    query = (
        "select=key,value,updated_at&key=in.("
        + ",".join(TUNNEL_CONFIG_KEYS)
        + ")"
    )
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
    }
    url = f"{supabase_url.rstrip('/')}/rest/v1/system_config?{query}"
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=8),
        ) as response:
            if response.status != 200:
                detail = (await response.text())[:240]
                raise RuntimeError(
                    f"Supabase tunnel-state read failed ({response.status}): {detail}"
                )
            rows = await response.json()

    values = {row.get("key"): row.get("value") for row in rows}
    updates = {row.get("key"): row.get("updated_at") for row in rows}
    return {
        "endpoint": values.get("ai_endpoint"),
        "status": values.get("ai_endpoint_status") or "unknown",
        "message": values.get("ai_endpoint_status_message") or "",
        "heartbeat": values.get("ai_endpoint_heartbeat"),
        "endpoint_updated_at": updates.get("ai_endpoint"),
        "rotation_pending": ROTATION_REQUEST_PATH.exists(),
    }
