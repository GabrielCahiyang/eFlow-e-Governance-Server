"""Publish the AI tunnel's endpoint and health state to Supabase."""

from datetime import datetime, timezone
import json
import time
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import Request, urlopen

from tunnel_config import TunnelSettings


class TunnelStatePublisher:
    def __init__(self, settings: TunnelSettings) -> None:
        self._settings = settings
        self._last_heartbeat = 0.0

    def publish(
        self,
        status: str,
        message: str,
        *,
        endpoint: str | None = None,
    ) -> None:
        heartbeat = datetime.now(timezone.utc).isoformat()
        values = {
            "ai_endpoint_status": status,
            "ai_endpoint_status_message": message,
            "ai_endpoint_heartbeat": heartbeat,
        }
        if endpoint:
            values["ai_endpoint"] = endpoint
        self._upsert(values)
        self._last_heartbeat = time.monotonic()

    def heartbeat(self) -> None:
        """Refresh the online lease so clients can detect abrupt process death."""
        if time.monotonic() - self._last_heartbeat < 15.0:
            return
        self._upsert(
            {"ai_endpoint_heartbeat": datetime.now(timezone.utc).isoformat()}
        )
        self._last_heartbeat = time.monotonic()

    def mark_offline_if_owner(self, endpoint: str | None) -> None:
        if endpoint and self._read_value("ai_endpoint") != endpoint:
            return
        self.publish(
            "offline",
            "The AI service is offline. Its automatic tunnel supervisor is not running.",
        )

    def _headers(self) -> dict[str, str]:
        key = self._settings.service_role_key
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _upsert(self, values: dict[str, str]) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        rows = [
            {"key": key, "value": value, "updated_at": updated_at}
            for key, value in values.items()
        ]
        request = Request(
            f"{self._settings.supabase_url}/rest/v1/system_config?on_conflict=key",
            data=json.dumps(rows).encode("utf-8"),
            headers={
                **self._headers(),
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            method="POST",
        )
        for attempt in range(3):
            try:
                with urlopen(request, timeout=10) as response:
                    if response.status not in {200, 201, 204}:
                        raise RuntimeError(
                            f"Supabase status publish failed ({response.status})"
                        )
                return
            except (OSError, TimeoutError, URLError):
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)

    def _read_value(self, key: str) -> str | None:
        query = urlencode({"key": f"eq.{key}", "select": "value"})
        request = Request(
            f"{self._settings.supabase_url}/rest/v1/system_config?{query}",
            headers=self._headers(),
        )
        with urlopen(request, timeout=10) as response:
            rows = json.loads(response.read().decode("utf-8"))
        if not rows:
            return None
        return str(rows[0].get("value") or "") or None
