"""Observe an existing host before spawning a conflicting private API."""
import io
import unittest
from unittest.mock import Mock, patch
import start

class HealthyResponse(io.BytesIO):
    status = 200

class LauncherReadinessTests(unittest.TestCase):
    def test_only_the_expected_private_health_response_is_reusable(self):
        with patch.object(start, 'urlopen', return_value=HealthyResponse(b'{"status":"ok"}')):
            self.assertTrue(start._ai_api_is_healthy())
        with patch.object(start, 'urlopen', return_value=HealthyResponse(b'{"status":"unavailable"}')):
            self.assertFalse(start._ai_api_is_healthy())
        with patch.object(start, 'urlopen', side_effect=OSError('offline')):
            self.assertFalse(start._ai_api_is_healthy())
        with patch.object(start, 'urlopen', return_value=HealthyResponse(b'[]')):
            self.assertFalse(start._ai_api_is_healthy())

    def test_supervisor_does_not_spawn_or_claim_an_already_healthy_api(self):
        tunnel = Mock()
        with patch.object(start, '_gateway_mode', return_value='external'), \
             patch.object(start, '_gateway_is_healthy', return_value=True), \
             patch.object(start, '_ai_api_is_healthy', return_value=True), \
             patch.object(start.signal, 'signal'), \
             patch.object(start.time, 'sleep', side_effect=KeyboardInterrupt), \
             patch.object(start.subprocess, 'Popen', return_value=tunnel) as spawn, \
             patch.object(start, '_stop_child') as stop:
            self.assertEqual(start.supervise_services(), 0)
        self.assertEqual(spawn.call_count, 1)
        self.assertTrue(spawn.call_args.args[0][1].endswith('tunnel_supervisor.py'))
        stop.assert_any_call(None)
        stop.assert_any_call(tunnel)

    def test_supervisor_starts_its_own_api_if_the_reused_host_goes_offline(self):
        tunnel = Mock(); tunnel.poll.return_value = None
        owned_api = Mock()
        with patch.object(start, '_gateway_mode', return_value='external'), \
             patch.object(start, '_gateway_is_healthy', return_value=True), \
             patch.object(start, '_ai_api_is_healthy', side_effect=[True, False]), \
             patch.object(start.signal, 'signal'), \
             patch.object(start.time, 'sleep', side_effect=[None, KeyboardInterrupt]), \
             patch.object(start.subprocess, 'Popen', side_effect=[tunnel, owned_api]) as spawn, \
             patch.object(start, '_stop_child') as stop:
            self.assertEqual(start.supervise_services(), 0)
        self.assertEqual(spawn.call_count, 2)
        self.assertTrue(spawn.call_args.args[0][1].endswith('run_api.py'))
        stop.assert_any_call(owned_api)
