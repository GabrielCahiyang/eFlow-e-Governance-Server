"""Regression tests for safe Quick Tunnel publication."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import tunnel_supervisor


class _JsonResponse:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self._payload


class TunnelReadinessTests(unittest.TestCase):
    def test_doh_requires_a_successful_dns_answer(self):
        with patch.object(
            tunnel_supervisor,
            "urlopen",
            return_value=_JsonResponse(b'{"Status":0,"Answer":[{"type":1}]}'),
        ):
            self.assertTrue(
                tunnel_supervisor._public_dns_ready(
                    "https://ready-host.trycloudflare.com"
                )
            )

        with patch.object(
            tunnel_supervisor,
            "urlopen",
            return_value=_JsonResponse(b'{"Status":3}'),
        ):
            self.assertFalse(
                tunnel_supervisor._public_dns_ready(
                    "https://missing-host.trycloudflare.com"
                )
            )

    def test_public_health_is_not_called_before_cloudflare_dns_is_ready(self):
        supervisor = tunnel_supervisor.TunnelSupervisor.__new__(
            tunnel_supervisor.TunnelSupervisor
        )
        supervisor._settings = SimpleNamespace(
            public_api_suffix="/controlpanelEflow/api",
            public_ready_timeout_seconds=30.0,
            retry_seconds=0.0,
        )
        supervisor._shutdown = threading.Event()
        supervisor._tunnel = SimpleNamespace(return_code=None)

        call_order: list[str] = []

        def dns_ready(_origin: str) -> bool:
            call_order.append("dns")
            return call_order.count("dns") > 1

        def healthy(_url: str, timeout_seconds: float = 3.0) -> bool:
            call_order.append("health")
            return True

        with patch.object(tunnel_supervisor, "_public_dns_ready", side_effect=dns_ready), patch.object(
            tunnel_supervisor,
            "_is_healthy",
            side_effect=healthy,
        ):
            supervisor._wait_for_public_endpoint(
                "https://ready-host.trycloudflare.com"
            )

        self.assertEqual(call_order, ["dns", "dns", "health"])


if __name__ == "__main__":
    unittest.main()
