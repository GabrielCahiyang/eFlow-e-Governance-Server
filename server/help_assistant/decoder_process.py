"""Private stdin/stdout worker; keeps the expensive TorchScript load off each turn."""
import asyncio
import json
import os
from pathlib import Path

async def reap(process):
    if process and process.returncode is None:
        if os.name == 'nt':
            # Windows venv launchers own a child python.exe. Reap the tree so
            # cancellation cannot leave the decoder holding GPU memory.
            killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(process.pid), '/T', '/F', stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=0x08000000)
            await killer.wait()
        else:
            process.kill()
        await process.communicate()

class DecoderProcess:
    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()
        self.warmup = None

    def prepare(self, environment):
        """Load CPU assets in the background; GPU work still belongs to the queue."""
        if self.warmup is None or self.warmup.done():
            self.warmup = asyncio.create_task(self._prepare(environment))

    async def _prepare(self, environment):
        try:
            async with self.lock:
                await self._start(environment)
        except Exception:
            # Startup remains available. A real speech request retries and
            # reports a visible error if the installed runtime is broken.
            await self.close()

    async def close(self):
        if self.warmup and self.warmup is not asyncio.current_task():
            self.warmup.cancel()
            await asyncio.gather(self.warmup, return_exceptions=True)
        self.warmup = None
        process, self.process = self.process, None
        task = asyncio.create_task(reap(process))
        while True:
            try:
                await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                continue

    async def _start(self, environment):
        root = Path(__file__).resolve().parents[1]
        python = root / '.speech-gpu-venv' / 'Scripts' / 'python.exe'
        assets = root.parent / '.cache' / 'kitten-tts' / 'KittenML' / 'kitten-tts-2' / 'main' / 'cpp' / 'student_w4'
        if not self.process or self.process.returncode is not None:
            try:
                with (root / 'speech-decoder-runtime.log').open('ab', buffering=0) as log:
                    self.process = await asyncio.create_subprocess_exec(str(python), '-u', str(Path(__file__).with_name('gpu_decoder.py')), '--worker', str(assets), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=log, env=environment, **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
                ready = await asyncio.wait_for(self.process.stdout.readline(), 180)
                if not ready or not json.loads(ready).get('ready'):
                    raise RuntimeError('Speech decoder could not start')
            except BaseException:
                process, self.process = self.process, None
                await reap(process)
                raise

    async def release_gpu(self):
        # Never wait for CPU preloading before a staffing/PDF job: it has no
        # VRAM to release yet. Decode/release run inside the same GPU queue.
        if self.lock.locked() or not self.process or self.process.returncode is not None:
            return
        async with self.lock:
            try:
                self.process.stdin.write(b'{"operation":"release"}\n')
                await self.process.stdin.drain()
                response = await asyncio.wait_for(self.process.stdout.readline(), 30)
                if not response or not json.loads(response).get('released'):
                    raise RuntimeError('Speech decoder could not release GPU memory')
                if json.loads(response).get('allocated_bytes', 0) > 16 * 1024 * 1024:
                    # Some TorchScript versions retain compiled CUDA constants.
                    # Reap that owned process before a larger model can proceed.
                    await self.close()
            except BaseException:
                await self.close()
                raise

    async def decode(self, report, output, environment):
        async with self.lock:
            return await self._decode(report, output, environment)

    async def _decode(self, report, output, environment):
        try:
            await self._start(environment)
            self.process.stdin.write((json.dumps({'report': str(report), 'output': str(output)}) + '\n').encode())
            await self.process.stdin.drain()
            line = await asyncio.wait_for(self.process.stdout.readline(), 90)
            result = json.loads(line) if line else {}
            if result.get('error') or not result.get('audio_seconds'):
                raise RuntimeError('Speech decoder could not finish')
            return result
        except BaseException:
            await self.close()
            raise
