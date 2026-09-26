"""Continuously publish and repair the eFlow Cloudflare Quick Tunnel."""

import signal
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

from tunnel_config import load_tunnel_settings
from tunnel_process import QuickTunnelProcess, find_cloudflared
from tunnel_state import TunnelStatePublisher
from tunnel_control import consume_tunnel_rotation_request


RESTARTING_MESSAGE = (
    "The AI service connection is down. The system detected the outage and "
    "is automatically restarting it."
)
STARTING_MESSAGE = "The AI services are ready. The secure connection is starting."
ONLINE_MESSAGE = "The AI service is online and its endpoint was published automatically."


class TunnelRotationRequested(RuntimeError):
    """Raised internally when an operator requests a fresh Quick Tunnel URL."""


def _is_healthy(url: str, timeout_seconds: float = 3.0) -> bool:
    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            return response.status == 200
    except (URLError, OSError):
        return False


class TunnelSupervisor:
    def __init__(self) -> None:
        self._settings = load_tunnel_settings()
        self._publisher = TunnelStatePublisher(self._settings)
        self._shutdown = threading.Event()
        self._tunnel: QuickTunnelProcess | None = None
        self._public_endpoint: str | None = None
        # Tracks the last endpoint we successfully published so the finally block
        # can mark Supabase offline even after _public_endpoint is cleared during
        # a crash / rotation cycle.
        self._last_published_endpoint: str | None = None
        self._last_state: tuple[str, str, str | None, bool] | None = None

    def request_shutdown(self, *_args) -> None:
        self._shutdown.set()
        if self._tunnel:
            self._tunnel.stop()

    def run(self) -> int:
        executable: str | None = None
        retry_delay = self._settings.retry_seconds

        try:
            while not self._shutdown.is_set():
                try:
                    # A pending request is already satisfied by the fresh tunnel this
                    # loop is about to create, so consume it before startup.
                    consume_tunnel_rotation_request()
                    executable = executable or find_cloudflared(
                        self._settings.cloudflared_path
                    )
                    self._wait_for_gateway()
                    if self._shutdown.is_set():
                        break

                    print(f"[START] {STARTING_MESSAGE}", flush=True)
                    self._tunnel = QuickTunnelProcess(
                        executable,
                        self._settings.gateway_origin,
                    )
                    tunnel_origin = self._tunnel.wait_for_url()
                    self._public_endpoint = (
                        f"{tunnel_origin}{self._settings.public_api_suffix}"
                    )
                    self._tunnel.wait_until_connected()
                    ai_ready = _is_healthy(self._settings.ai_health_url)
                    self._publish_with_retry(
                        "online" if ai_ready else "restarting",
                        ONLINE_MESSAGE if ai_ready else RESTARTING_MESSAGE,
                        endpoint=self._public_endpoint,
                    )
                    # Record the endpoint we just published so the finally block can
                    # mark it offline on a clean or unclean exit.
                    self._last_published_endpoint = self._public_endpoint
                    print(f"[ONLINE] Published {self._public_endpoint}", flush=True)
                    retry_delay = self._settings.retry_seconds
                    self._monitor_tunnel(tunnel_origin)
                except Exception as exc:
                    if self._shutdown.is_set():
                        break
                    prefix = "[ROTATE]" if isinstance(exc, TunnelRotationRequested) else "[WARN]"
                    print(f"{prefix} {exc}", file=sys.stderr, flush=True)
                    if self._tunnel:
                        self._tunnel.stop()
                        self._tunnel = None
                    self._publish_with_retry(
                        "restarting",
                        RESTARTING_MESSAGE,
                        endpoint=self._public_endpoint,
                        require_owner=True,
                    )
                    self._public_endpoint = None
                    self._shutdown.wait(retry_delay)
                    retry_delay = min(retry_delay * 2, 60.0)
        finally:
            if self._tunnel:
                self._tunnel.stop()
            # Use _last_published_endpoint as a fallback so we always mark the
            # last-known Supabase endpoint as offline, even when _public_endpoint
            # was cleared to None during a crash or rotation cycle.
            offline_endpoint = self._public_endpoint or self._last_published_endpoint
            try:
                self._publisher.mark_offline_if_owner(offline_endpoint)
            except Exception as exc:
                print(f"[WARN] Could not publish offline status: {exc}", file=sys.stderr)
        return 0

    def _wait_for_gateway(self) -> None:
        """Wait only for the public gateway; AI restarts must not stop Admin APIs."""
        last_missing: tuple[str, ...] | None = None
        last_reported_at = 0.0
        while not self._shutdown.is_set():
            gateway_ready = _is_healthy(self._settings.gateway_health_url)
            if gateway_ready:
                return
            missing = ["eFlow gateway :8322"]
            missing_state = tuple(missing)
            now = time.monotonic()
            if missing_state != last_missing or now - last_reported_at >= 60.0:
                print(
                    f"[WAIT] Waiting for {' and '.join(missing)}; automatic retry is active.",
                    flush=True,
                )
                last_missing = missing_state
                last_reported_at = now
            self._shutdown.wait(self._settings.retry_seconds)

    def _monitor_tunnel(self, tunnel_origin: str) -> None:
        failures = 0
        last_ai_ready: bool | None = None
        public_health_url = (
            f"{tunnel_origin}{self._settings.public_api_suffix}/health"
        )
        while not self._shutdown.wait(self._settings.health_interval_seconds):
            if consume_tunnel_rotation_request():
                raise TunnelRotationRequested(
                    "Dashboard requested a fresh Cloudflare Quick Tunnel URL."
                )
            if not self._tunnel or self._tunnel.return_code is not None:
                raise RuntimeError("cloudflared stopped unexpectedly")
            if not _is_healthy(self._settings.gateway_health_url):
                raise RuntimeError("eFlow gateway health check failed")

            ai_ready = _is_healthy(self._settings.ai_health_url)
            if ai_ready != last_ai_ready:
                self._publish_with_retry(
                    "online" if ai_ready else "restarting",
                    ONLINE_MESSAGE if ai_ready else RESTARTING_MESSAGE,
                    endpoint=self._public_endpoint,
                    require_owner=True,
                )
                print(
                    "[AI] Local AI service is online."
                    if ai_ready
                    else "[AI] Local AI service is restarting; the gateway and tunnel remain online.",
                    flush=True,
                )
                last_ai_ready = ai_ready
            public_healthy = _is_healthy(public_health_url, timeout_seconds=8.0)
            failures = 0 if public_healthy else failures + 1
            if failures == self._settings.failure_threshold:
                print(
                    "[WARN] The local public-URL self-check cannot resolve the "
                    "Quick Tunnel. Cloudflare remains connected; clients will "
                    "continue using the published endpoint.",
                    file=sys.stderr,
                    flush=True,
                )
            try:
                self._publisher.heartbeat(self._public_endpoint)
            except Exception as exc:
                print(
                    f"[WARN] Supabase heartbeat delayed: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

    def _publish(
        self,
        status: str,
        message: str,
        *,
        endpoint: str | None = None,
        require_owner: bool = False,
    ) -> bool:
        state = (status, message, endpoint, require_owner)
        if state == self._last_state:
            return True
        published = self._publisher.publish(
            status,
            message,
            endpoint=endpoint,
            require_owner=require_owner,
        )
        if not published:
            return False
        self._last_state = state
        return True

    def _publish_with_retry(
        self,
        status: str,
        message: str,
        *,
        endpoint: str | None = None,
        require_owner: bool = False,
    ) -> None:
        while not self._shutdown.is_set():
            try:
                published = self._publish(
                    status,
                    message,
                    endpoint=endpoint,
                    require_owner=require_owner,
                )
                if not published:
                    return
                return
            except Exception as exc:
                print(
                    f"[WARN] Supabase state publication delayed: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                self._shutdown.wait(self._settings.retry_seconds)


def main() -> int:
    supervisor = TunnelSupervisor()
    signal.signal(signal.SIGINT, supervisor.request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, supervisor.request_shutdown)
    return supervisor.run()


if __name__ == "__main__":
    raise SystemExit(main())
