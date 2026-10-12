import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

import public_gateway as gateway
import http_client


class FakeContent:
    async def iter_any(self):
        yield b'{"done":false}\n'
        yield b'{"done":true}\n'


class FakeUpstream:
    def __init__(self, status=200):
        self.status = status
        self.headers = {'content-type': 'application/x-ndjson', 'Retry-After': '5'}
        self.content = FakeContent()
        self.closed = self.released = False
        self.read = AsyncMock(return_value=b'{"error":"full"}')

    def close(self): self.closed = True
    def release(self): self.released = True


class GatewayRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, upstream, payload):
        request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'headers': []})
        session = AsyncMock()
        session.request.return_value = upstream
        with patch.object(gateway, '_require_active_user', AsyncMock(return_value='verified-owner')) as auth, \
             patch.object(gateway.internal_ai_key, 'get', AsyncMock(return_value='private-test')), \
             patch.object(gateway, 'get_session', AsyncMock(return_value=session)):
            response = await gateway._proxy_ai_request('POST', 'chat', request, payload=payload, timeout_seconds=7200)
        auth.assert_awaited_once()
        kwargs = session.request.call_args.kwargs
        self.assertEqual(kwargs['headers']['X-eFlow-User-Id'], 'verified-owner')
        self.assertEqual(kwargs['timeout'].total, 7200)
        return response

    async def test_stream_is_incremental_and_disconnect_closes_upstream(self):
        upstream = FakeUpstream()
        response = await self.call(upstream, {'stream': True})
        frame = await anext(response.body_iterator)
        self.assertEqual(frame, b'{"done":false}\n')
        upstream.read.assert_not_awaited()
        await response.body_iterator.aclose()
        self.assertTrue(upstream.closed)

    async def test_queue_full_preserves_retry_header_and_releases_connection(self):
        upstream = FakeUpstream(status=429)
        response = await self.call(upstream, {'stream': False})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '5')
        self.assertTrue(upstream.released)

    async def test_services_reuse_and_close_outbound_session(self):
        await http_client.close_session()
        first = await http_client.get_session()
        second = await http_client.get_session()
        self.assertIs(first, second)
        self.assertEqual(first.connector.limit, 32)
        await http_client.close_session()
        self.assertTrue(first.closed)
