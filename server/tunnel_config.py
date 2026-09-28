"""Configuration for the automatic eFlow Quick Tunnel supervisor."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


# The tunnel shares the local backend configuration.  Use the file values when
# the parent PowerShell session carries empty environment variables.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)


def _required_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise RuntimeError(f"Missing required environment variable: {' or '.join(names)}")


@dataclass(frozen=True)
class TunnelSettings:
    supabase_url: str
    service_role_key: str
    ai_health_url: str
    gateway_origin: str
    gateway_health_url: str
    public_api_suffix: str
    cloudflared_path: str | None
    retry_seconds: float
    public_ready_timeout_seconds: float
    health_interval_seconds: float
    failure_threshold: int


def load_tunnel_settings() -> TunnelSettings:
    gateway_origin = os.getenv(
        "EFLOW_GATEWAY_ORIGIN",
        "http://127.0.0.1:8322",
    ).rstrip("/")
    return TunnelSettings(
        supabase_url=_required_env("SUPABASE_URL", "VITE_SUPABASE_URL").rstrip("/"),
        service_role_key=_required_env("SUPABASE_SERVICE_ROLE_KEY"),
        ai_health_url=os.getenv(
            "EFLOW_AI_HEALTH_URL",
            "http://127.0.0.1:8321/controlpanelEflow/api/health",
        ),
        gateway_origin=gateway_origin,
        gateway_health_url=os.getenv(
            "EFLOW_GATEWAY_HEALTH_URL",
            f"{gateway_origin}/controlpanelEflow/api/health",
        ),
        public_api_suffix=os.getenv(
            "EFLOW_PUBLIC_API_SUFFIX",
            "/controlpanelEflow/api",
        ),
        cloudflared_path=os.getenv("CLOUDFLARED_PATH") or None,
        retry_seconds=max(1.0, float(os.getenv("EFLOW_TUNNEL_RETRY_SECONDS", "5"))),
        public_ready_timeout_seconds=max(
            30.0,
            float(os.getenv("EFLOW_TUNNEL_PUBLIC_READY_TIMEOUT_SECONDS", "90")),
        ),
        health_interval_seconds=max(
            5.0,
            float(os.getenv("EFLOW_TUNNEL_HEALTH_INTERVAL_SECONDS", "5")),
        ),
        failure_threshold=max(
            1,
            int(os.getenv("EFLOW_TUNNEL_FAILURE_THRESHOLD", "3")),
        ),
    )
