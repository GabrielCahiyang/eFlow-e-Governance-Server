"""Exercise real API contracts with no remote services or GPU required."""
import asyncio
import time
import unittest
from unittest.mock import patch

import httpx

import main
from inference_worker import InferenceWorker
from job_queue import AiJobQueue
from test_runtime_scheduling import fake_inference_process


class ApiSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.worker = InferenceWorker(target=fake_inference_process, timeout_seconds=10)
        self.queue = AiJobQueue(main._process_queued_chat, max_waiting_jobs=2, max_jobs_per_owner=2)
        main._api_key_cache.update(value='test-local', timestamp=time.time())
        self.patches = [patch.object(main, 'manager', self.worker),
                        patch.object(main, 'job_queue', self.queue),
                        patch.object(main.supabase_log_writer, 'enqueue')]
        for item in self.patches: item.start()
        await self.queue.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                       base_url='http://test/controlpanelEflow/api/',
                                       headers={'Authorization': 'Bearer test-local', 'X-eFlow-User-Id': 'owner'})

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.queue.stop(drain=False)
        await self.worker.close()
        for item in reversed(self.patches): item.stop()
        main._stream_channels.clear()

    def body(self, **extra):
        return {'model': 'qwen3.5:2b', 'messages': [{'role': 'user', 'content': 'Hello'}], **extra}

    async def test_health_remains_responsive_during_blocking_inference_and_fifo_admission(self):
        first = await self.client.post('jobs', json=self.body(hang=True))
        self.assertEqual(first.status_code, 202)
        await asyncio.sleep(0.05)
        chat = asyncio.create_task(self.client.post('chat', json=self.body(stream=False)))
        await asyncio.sleep(0.05)
        started = time.perf_counter()
        health = await asyncio.wait_for(self.client.get('health'), 0.5)
        self.assertEqual(health.status_code, 200)
        self.assertLess(time.perf_counter() - started, 0.5)
        full = await self.client.post('jobs', json=self.body())
        self.assertEqual(full.status_code, 429)
        self.assertEqual(full.headers['Retry-After'], '5')
        cancelled = await self.client.delete(f"jobs/{first.json()['job_id']}")
        self.assertEqual(cancelled.status_code, 200)
        result = await asyncio.wait_for(chat, 10)
        self.assertEqual(result.status_code, 200)
        self.assertEqual((await self.queue.overview())['processing'], 0)

    async def test_streaming_uses_same_worker_and_does_not_cancel_success(self):
        response = await self.client.post('chat', json=self.body(stream=True))
        self.assertEqual(response.status_code, 200)
        import json
        frames = [json.loads(line) for line in response.text.splitlines()]
        self.assertIn('job_id', frames[0])
        self.assertEqual(frames[1]['message']['content'], 'hello')
        self.assertTrue(frames[-1]['done'])
        snapshot = await self.queue.wait(frames[0]['job_id'], 'owner')
        self.assertEqual(snapshot['status'], 'completed')
        self.assertFalse(snapshot['cancelled'])
        self.assertFalse(main._stream_channels)

    async def test_job_owner_and_auth_cannot_be_bypassed(self):
        submitted = await self.client.post('jobs', json=self.body(hang=True))
        job_id = submitted.json()['job_id']
        wrong = await self.client.delete(f'jobs/{job_id}', headers={'X-eFlow-User-Id': 'wrong'})
        self.assertEqual(wrong.status_code, 404)
        denied = await self.client.put('authkey', json={'api_key': 'must-not-change'},
                                       headers={'Authorization': 'Bearer wrong'})
        self.assertEqual(denied.status_code, 401)

    async def test_invalid_requests_never_enter_queue(self):
        response = await self.client.post('jobs', json=self.body(max_tokens=100000))
        self.assertEqual(response.status_code, 400)
        for malformed in ([], self.body(model={}), self.body(stream='false'),
                          self.body(messages=[{'role': [], 'content': 'invalid'}])):
            response = await self.client.post('chat', json=malformed)
            self.assertEqual(response.status_code, 400)
        self.assertEqual((await self.queue.overview())['depth'], 0)

    async def test_service_monitoring_is_authenticated_and_contains_no_rpc_secrets(self):
        denied = await self.client.get('operations', headers={'Authorization': 'Bearer wrong'})
        self.assertEqual(denied.status_code, 401)
        response = await self.client.get('operations')
        self.assertEqual(response.status_code, 200)
        services = response.json()['services']
        for name in ('pygad', 'laya', 'blockchain'):
            self.assertIn('recent_runs', services[name])
            self.assertIn('active_runs', services[name])
        self.assertNotIn('private_key', str(services))
        self.assertNotIn('rpc_url', str(services))
