"""One owned, loopback-only Redux process; reuse loaded weights for previews."""
import asyncio
import os
from pathlib import Path
import socket
import aiohttp
import time
try:
    from .latency import record_latency
except ImportError:
    from latency import record_latency


class ParakeetRuntime:
    def __init__(self):
        self.process = None
        self.session = None
        self.origin = None

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None
        process, self.process = self.process, None
        if process and process.returncode is None:
            process.kill()
            await process.wait()

    async def start(self):
        if self.process and self.process.returncode is None:
            return
        await self.close()
        base = Path(__file__).resolve().parents[1] / '.speech-venv' / 'parakeet'
        binary = base / 'parakeet-v0.6.1-bin-win-cpu-x64' / 'parakeet-server.exe'
        model = base / 'redux-q8_0.gguf'
        if not binary.exists() or not model.exists():
            raise RuntimeError('The Parakeet Redux runtime is not installed.')
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0))
            port = reserve.getsockname()[1]
        self.origin = f'http://127.0.0.1:{port}'
        log_path = Path(__file__).resolve().parents[1] / 'speech-asr-runtime.log'
        with log_path.open('ab', buffering=0) as log:
            self.process = await asyncio.create_subprocess_exec(
                str(binary), '--model', str(model), '--host', '127.0.0.1',
                '--port', str(port), '--threads', '4', '--concurrency', '1',
                stdout=log, stderr=log,
                **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90))
        for _ in range(240):
            if self.process.returncode is not None:
                break
            try:
                async with self.session.get(self.origin + '/health', timeout=aiohttp.ClientTimeout(total=1)) as response:
                    if response.status == 200:
                        return
            except (aiohttp.ClientError, TimeoutError):
                pass
            await asyncio.sleep(.25)
        await self.close()
        raise RuntimeError('Parakeet could not start. Check the AI server speech log.')

    async def transcribe(self, audio):
        started = time.monotonic()
        await self.start()
        ready = time.monotonic()
        form = aiohttp.FormData()
        form.add_field('file', audio, filename='turn.wav', content_type='audio/wav')
        try:
            async with self.session.post(self.origin + '/v1/audio/transcriptions', data=form) as response:
                if response.status != 200:
                    raise RuntimeError('Parakeet could not transcribe this audio.')
                result = await response.json()
            return {'text': str(result.get('text') or '').strip()[:2000],
                    'model': 'moondream/parakeet-redux', 'runtime': 'parakeet.cpp v0.6.1 Q8'}
        except BaseException:
            await self.close()
            raise
        finally:
            record_latency('parakeet', startup_seconds=ready-started,
                           inference_http_seconds=time.monotonic()-ready, audio_bytes=len(audio))
