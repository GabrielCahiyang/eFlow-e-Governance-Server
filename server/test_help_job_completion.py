import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from help_assistant.job_completion import wait_for_job


class JobCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_completion_wakes_without_a_quarter_second_poll(self):
        ready = asyncio.Event()
        completed = {'status': 'completed', 'job_id': 'one'}
        async def wait(job, owner):
            self.assertEqual((job, owner), ('one', 'owner'))
            await ready.wait()
            return completed
        queue = AsyncMock(); queue.wait.side_effect = wait
        request = AsyncMock(); request.is_disconnected.return_value = False
        with patch('help_assistant.job_completion.record_latency'):
            task = asyncio.create_task(wait_for_job(queue, {'status':'processing','job_id':'one'}, 'owner', request, 10, 'Timed out'))
            await asyncio.sleep(0)
            ready.set()
            # A full 250ms polling delay would fail this event-driven check.
            self.assertEqual(await asyncio.wait_for(task, .1), completed)
        queue.snapshot.assert_not_called()

    async def test_disconnect_cancels_and_joins_only_the_owned_waiter(self):
        queue = AsyncMock(); request = AsyncMock(); request.is_disconnected.return_value = True
        with patch('help_assistant.job_completion.record_latency'):
            with self.assertRaises(asyncio.CancelledError):
                await wait_for_job(queue, {'status':'queued','job_id':'one'}, 'owner', request, 10, 'Timeout')
        queue.cancel.assert_not_called()  # Owning route retains its finally/cancel.

    async def test_timeout_is_bounded_and_missing_job_is_visible(self):
        queue = AsyncMock(); request = AsyncMock(); request.is_disconnected.return_value = False
        with patch('help_assistant.job_completion.record_latency'):
            with self.assertRaises(HTTPException) as timeout:
                await wait_for_job(queue, {'status':'queued','job_id':'one'}, 'owner', request, 0, 'Timeout')
            self.assertEqual(timeout.exception.status_code, 504)
            queue.wait.return_value = None
            with self.assertRaises(HTTPException) as missing:
                await wait_for_job(queue, {'status':'queued','job_id':'one'}, 'owner', request, 1, 'Timeout')
            self.assertEqual(missing.exception.status_code, 503)

    async def test_already_completed_job_needs_no_waiter(self):
        queue = AsyncMock()
        result = {'status':'completed','job_id':'one'}
        self.assertEqual(await wait_for_job(queue, result, 'owner', AsyncMock(), 10, 'Timeout'), result)
        queue.wait.assert_not_called()
