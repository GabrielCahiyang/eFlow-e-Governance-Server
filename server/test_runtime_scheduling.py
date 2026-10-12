import asyncio
import json
import os
import time
import unittest
from unittest.mock import patch

import psutil

from inference_worker import InferenceWorker
from job_queue import AiJobQueue, QueueCapacityError
from model_runtime import BoundedModel
from server_logging import SSEManager, SupabaseLogWriter, make_entry, LOG_TYPE_CHAT
from workspace_decomposition import document_chunks


def fake_inference_process(connection):
    """Real child process with deterministic stalls, failures and stream frames."""
    while True:
        body = connection.recv()
        connection.send(('loaded', {'model': body['model']}))
        if body.get('crash'):
            os._exit(2)
        if body.get('hang'):
            time.sleep(60)
        time.sleep(body.get('delay', 0))
        connection.send(('chunk', {'message': {'content': 'hello'}, 'done': False}))
        connection.send(('result', {'pid': os.getpid(), 'eval_count': 1,
                                     'timings_ms': {'total': 1}}))


class SchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def test_capacity_per_owner_and_idempotency(self):
        queue = AiJobQueue(lambda body: asyncio.sleep(0), max_waiting_jobs=3, max_jobs_per_owner=2)
        one = await queue.submit('one', {'model': 'test'}, 'retry')
        await queue.submit('one', {'model': 'test'})
        self.assertEqual((await queue.submit('one', {}, 'retry'))['job_id'], one['job_id'])
        with self.assertRaises(QueueCapacityError):
            await queue.submit('one', {})
        await queue.submit('two', {})
        with self.assertRaises(QueueCapacityError):
            await queue.submit('three', {})
        self.assertEqual((await queue.overview())['capacity'], 3)

    async def test_queued_cancel_is_owner_scoped_and_removes_backlog(self):
        calls = []
        async def process(body):
            calls.append(body['name'])
            return body
        queue = AiJobQueue(process)
        cancelled = await queue.submit('one', {'name': 'cancelled', 'secret': 'private'})
        self.assertIsNone(await queue.cancel(cancelled['job_id'], 'two'))
        await queue.cancel(cancelled['job_id'], 'one')
        next_job = await queue.submit('two', {'name': 'next'})
        await queue.start()
        await queue.stop()
        self.assertEqual(calls, ['next'])
        self.assertEqual((await queue.wait(cancelled['job_id'], 'one'))['status'], 'failed')
        self.assertEqual((await queue.wait(next_job['job_id'], 'two'))['status'], 'completed')
        self.assertNotIn('secret', str(await queue.overview()))

    async def test_active_cancel_waits_for_cleanup_before_next_job(self):
        started, cleanup, finish_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
        order = []
        async def process(body):
            order.append(body['name'])
            if body['name'] == 'first':
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleanup.set()
                    await finish_cleanup.wait()
            return body
        queue = AiJobQueue(process)
        await queue.start()
        first = await queue.submit('one', {'name': 'first'})
        await started.wait()
        second = await queue.submit('two', {'name': 'second'})
        await queue.cancel(first['job_id'], 'one')
        await cleanup.wait()
        self.assertEqual(order, ['first'])
        self.assertEqual((await queue.snapshot(first['job_id'], 'one'))['status'], 'processing')
        finish_cleanup.set()
        await queue.wait(second['job_id'], 'two')
        self.assertEqual(order, ['first', 'second'])
        self.assertTrue((await queue.wait(first['job_id'], 'one'))['cancelled'])
        await queue.stop()

    async def test_idle_cleanup_expires_results_and_idempotency(self):
        async def process(body):
            return {'done': True}
        queue = AiJobQueue(process, result_ttl_seconds=0.03, cleanup_interval_seconds=0.01)
        await queue.start()
        job = await queue.submit('one', {}, 'retry')
        await queue.wait(job['job_id'], 'one')
        await asyncio.sleep(0.08)
        self.assertIsNone(await queue.snapshot(job['job_id'], 'one'))
        retry = await queue.submit('one', {}, 'retry')
        self.assertNotEqual(job['job_id'], retry['job_id'])
        await queue.stop()

    async def test_shutdown_cancels_instead_of_draining(self):
        started = asyncio.Event()
        async def process(body):
            started.set()
            await asyncio.Event().wait()
        queue = AiJobQueue(process)
        await queue.start()
        first = await queue.submit('one', {})
        await started.wait()
        second = await queue.submit('two', {})
        await asyncio.wait_for(queue.stop(drain=False), 1)
        for job, owner in ((first, 'one'), (second, 'two')):
            self.assertTrue((await queue.wait(job['job_id'], owner))['cancelled'])


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.worker = InferenceWorker(target=fake_inference_process, timeout_seconds=10)

    async def asyncTearDown(self):
        await self.worker.close()

    async def test_warm_worker_stream_delivery_and_loop_responsiveness(self):
        frames = []
        async def chunk(frame):
            frames.append(frame)
        first = await self.worker.execute({'model': 'test'}, on_chunk=chunk)
        task = asyncio.create_task(self.worker.execute({'model': 'test', 'delay': 0.3}))
        ticks = 0
        while not task.done():
            await asyncio.sleep(0.01)
            ticks += 1
        second = await task
        self.assertEqual(first['pid'], second['pid'])
        self.assertGreater(ticks, 10)
        self.assertEqual(frames[0]['message']['content'], 'hello')

    async def test_cancel_reaps_child_then_starts_fresh_worker(self):
        await self.worker.execute({'model': 'test'})
        old_pid = self.worker.pid
        task = asyncio.create_task(self.worker.execute({'model': 'test', 'hang': True}))
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(psutil.pid_exists(old_pid))
        self.assertIsNone(self.worker.loaded_tag)
        result = await self.worker.execute({'model': 'test'})
        self.assertNotEqual(old_pid, result['pid'])

    async def test_timeout_and_crash_recover(self):
        await self.worker.execute({'model': 'test'})
        old_pid = self.worker.pid
        self.worker.timeout_seconds = 0.1
        with self.assertRaises(asyncio.TimeoutError):
            await self.worker.execute({'model': 'test', 'hang': True})
        self.assertFalse(psutil.pid_exists(old_pid))
        self.worker.timeout_seconds = 10
        with self.assertRaises((EOFError, OSError)):
            await self.worker.execute({'model': 'test', 'crash': True})
        result = await self.worker.execute({'model': 'test'})
        self.assertTrue(result['pid'])
        self.assertEqual(self.worker.restarts, 2)


class BoundTests(unittest.TestCase):
    def test_unicode_document_sections_fit_context_and_preserve_source(self):
        class Model:
            output_limit = 512
            def n_ctx(self): return 2048
            def tokenize(self, data): return list(data)
        source = ('你好 😀 eFlow\n' * 150)
        chunks = document_chunks(Model(), source, {'title': 'Project'}, 'Read source data')
        self.assertGreater(len(chunks), 1)
        self.assertEqual(''.join(chunks), source)
        for chunk in chunks:
            count = len(('Read source data' + json.dumps({'context': {'title': 'Project'},
                                                        'documentSection': chunk}, ensure_ascii=False)).encode())
            self.assertLessEqual(count, 2048 - 512 - 384)

    def test_generation_respects_input_and_requested_output_budget(self):
        class Model:
            def n_ctx(self): return 1024
            def tokenize(self, data, **kwargs): return list(data)
            def create_chat_completion(self, **kwargs): return kwargs
        model = BoundedModel(Model(), 1024)
        result = model.create_chat_completion(messages=[{'content': 'x' * 500}], max_tokens=1000)
        self.assertEqual(result['max_tokens'], 268)
        result = model.create_chat_completion(messages=[{'content': 'x'}], max_tokens=12)
        self.assertEqual(result['max_tokens'], 12)
        with self.assertRaises(ValueError):
            model.create_chat_completion(messages=[{'content': 'x' * 800}])

    def test_fitness_does_not_repeat_text_comparisons(self):
        from pygad_optimizer import ProposalOptimizer
        optimizer = ProposalOptimizer([{'title': 'Network', 'requiredSkills': ['network']}],
                                       [{'id': 'one', 'skills': ['network']}])
        with patch('pygad_optimizer._calculate_skill_overlap', side_effect=AssertionError('Repeated work')):
            self.assertGreater(optimizer._fitness_function(None, [0], 0), 0)


class LogBoundsTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_log_consumers_and_remote_writer_remain_bounded(self):
        sse = SSEManager()
        client = sse.subscribe()
        writer = SupabaseLogWriter('', '')
        for index in range(600):
            entry = make_entry(str(index), log_type=LOG_TYPE_CHAT)
            await sse.broadcast(entry)
            writer.enqueue(entry)
        self.assertEqual(client.qsize(), 256)
        self.assertEqual(writer._pending.qsize(), 256)
        self.assertEqual(writer.dropped, 344)
        self.assertEqual((await client.get())['message'], '344')
