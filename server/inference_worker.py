"""One warm inference process; cancellation reaps it before releasing the GPU."""
import asyncio
from collections import deque
import multiprocessing
import os
import time
from uuid import uuid4
from service_monitor import monitor, event_sink, run_origin

from job_queue import _progress_reporter, report_job_progress


def worker_main(connection):
    from model_runtime import ModelManager, execute_job
    manager = ModelManager()
    try:
        while True:
            body = connection.recv()
            if body is None:
                break
            if body.get('_unload'):
                manager.unload()
                connection.send(('loaded', {'model': None}))
                connection.send(('result', {'unloaded': True}))
                continue
            def send(kind, payload):
                connection.send((kind, payload))
            marker = _progress_reporter.set(lambda progress: send('progress', progress))
            service_marker = event_sink.set(lambda record: send('service', record))
            origin_marker = run_origin.set('decomposition')
            try:
                send('result', execute_job(manager, body, send))
            except Exception as exc:
                send('loaded', {'model': manager.loaded_tag})
                send('error', str(exc) or exc.__class__.__name__)
            finally:
                _progress_reporter.reset(marker)
                event_sink.reset(service_marker)
                run_origin.reset(origin_marker)
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        manager.unload()
        connection.close()


class InferenceWorker:
    def __init__(self, *, target=worker_main, timeout_seconds=None):
        self._target = target
        self.timeout_seconds = timeout_seconds or float(os.getenv('EFLOW_INFERENCE_TIMEOUT_SECONDS', '7200'))
        self._context = multiprocessing.get_context('spawn')
        self._process = None
        self._connection = None
        self._lock = asyncio.Lock()
        self._loaded_tag = None
        self.restarts = 0
        self._runs = deque(maxlen=60)

    @property
    def pid(self):
        return self._process.pid if self._process and self._process.is_alive() else None

    @property
    def loaded_tag(self):
        return self._loaded_tag if self.pid else None

    def _start(self):
        if self.pid:
            return
        if self._connection:
            self._connection.close()
        if self._process:
            self._process.join(timeout=0)
            self._process.close()
        parent, child = self._context.Pipe()
        self._process = self._context.Process(target=self._target, args=(child,), daemon=True,
                                              name='eflow-inference')
        self._process.start()
        child.close()
        self._connection = parent
        self._loaded_tag = None

    async def _reap(self):
        process, connection = self._process, self._connection
        self._process = self._connection = None
        self._loaded_tag = None
        if process:
            if process.is_alive():
                process.terminate()
            await asyncio.to_thread(process.join, 3)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join)
            process.close()
        if connection:
            connection.close()

    async def close(self):
        async with self._lock:
            await self._reap()

    async def unload(self):
        """Free model weights for speech while retaining imported native code."""
        if self.pid:
            await self.execute({'model': '__unload__', '_unload': True})

    async def execute(self, body, on_chunk=None):
        async with self._lock:
            self._start()
            connection = self._connection
            scope = str(uuid4())
            cancelled = False
            async def receive():
                # A failed send/receive is a worker failure, never a reason to
                # continue on a stale native model handle.
                await asyncio.to_thread(connection.send, body)
                while True:
                    kind, payload = await asyncio.to_thread(connection.recv)
                    if kind == 'loaded':
                        self._loaded_tag = payload['model']
                    elif kind == 'progress':
                        report_job_progress(payload['stage'], payload['message'], payload.get('current'), payload.get('total'))
                    elif kind == 'service':
                        monitor.ingest(payload, scope)
                    elif kind == 'chunk' and on_chunk:
                        await on_chunk(payload)
                    elif kind == 'error':
                        raise ValueError(payload)
                    elif kind == 'result':
                        if body.get('_unload'):
                            return payload
                        self._runs.append({'model': body['model'], 'completed_at': time.time(),
                                           'tokens': payload.get('eval_count', 0),
                                           'first_token_ms': payload.get('first_token_ms'),
                                           'pipeline_status': payload.get('pipeline_status'),
                                           **payload.get('timings_ms', {})})
                        return payload
            try:
                return await asyncio.wait_for(receive(), timeout=self.timeout_seconds)
            except (asyncio.CancelledError, asyncio.TimeoutError, EOFError, BrokenPipeError, OSError) as exc:
                cancelled = isinstance(exc, asyncio.CancelledError)
                self.restarts += 1
                cleanup = asyncio.create_task(self._reap())
                while True:
                    try:
                        await asyncio.shield(cleanup)
                        break
                    except asyncio.CancelledError:
                        # Repeated disconnect/cancel signals cannot release the
                        # GPU lock before the native process actually exits.
                        continue
                raise
            finally:
                monitor.close_scope(scope, cancelled=cancelled)

    def overview(self):
        return {'pid': self.pid, 'loaded_model': self.loaded_tag, 'restarts': self.restarts,
                'timeout_seconds': self.timeout_seconds, 'recent_runs': list(self._runs)}
