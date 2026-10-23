"""Start speech lazily in its own Python environment, with bounded admission."""
import asyncio
import os
from pathlib import Path
import secrets
import socket
import base64
import tempfile
import json
import time
import logging

import aiohttp
from fastapi import HTTPException
from http_client import get_session
from .decoder_process import DecoderProcess, reap
from .kitten_process import KittenProcess

class SpeechService:
    def __init__(self):
        root = Path(__file__).resolve().parents[1]
        self.python = root / '.speech-venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        self.script = Path(__file__).with_name('speech_worker.py')
        self.process = None
        self.key = secrets.token_urlsafe(32)
        self.port = None
        self.start_lock = asyncio.Lock()
        self.busy = asyncio.Lock()
        self.results = {}
        self.decoder = DecoderProcess()
        self.kitten = KittenProcess()
        self.asr_warmup = None

    def available(self):
        root = self.script.parents[1]
        try:
            receipt = json.loads((root / '.speech-venv' / 'voice-ready.json').read_text())
            return receipt.get('runtime') == 'cuda-f16-v1' and all(path.exists() for path in (
                self.python,
                root / '.speech-venv' / 'Lib' / 'site-packages' / 'aiohttp' / '__init__.py',
                root / '.speech-venv' / 'parakeet' / 'parakeet-v0.6.1-bin-win-cpu-x64' / 'parakeet-server.exe',
                root / '.speech-gpu-venv' / 'Scripts' / 'python.exe',
                root / '.speech-venv' / 'parakeet' / 'redux-q8_0.gguf',
                Path.home() / '.cache' / 'eflow-speech' / 'build-compat' / 'eflow-kitten-worker.exe',
                root.parent / '.cache' / 'kitten-tts' / 'KittenML' / 'kitten-tts-2' / 'main' / 'cpp' / 'model-gpu-f16.gguf',
            ))
        except (OSError, ValueError):
            return False

    def decoder_environment(self):
        root = self.script.parents[1]
        environment = {**os.environ}
        library = root / '.venv' / 'Lib' / 'site-packages' / 'llama_cpp' / 'lib'
        torch_library = root / '.speech-gpu-venv' / 'Lib' / 'site-packages' / 'torch' / 'lib'
        cuda = Path(os.getenv('CUDA_PATH', 'C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.4')) / 'bin'
        environment['PATH'] = os.pathsep.join(map(str, (torch_library, cuda, library))) + os.pathsep + environment.get('PATH', '')
        environment.pop('GGML_BACKEND_PATH', None)
        environment['GGML_CUDA_DISABLE_FUSION'] = '1'
        environment['GGML_CUDA_CUBLAS_COMPUTE_TYPE'] = 'f32'
        environment['OMP_NUM_THREADS'] = '6'
        environment['MKL_NUM_THREADS'] = '6'
        return environment

    def prepare_voice(self):
        if self.available():
            self.decoder.prepare(self.decoder_environment())
            if self.asr_warmup is None or self.asr_warmup.done():
                self.asr_warmup = asyncio.create_task(self._prepare_asr())

    async def _prepare_asr(self):
        try:
            await self.call('warmup', {})
        except Exception:
            logging.getLogger(__name__).warning('Parakeet warmup failed; the next microphone request will retry')

    async def native_speech(self, text):
        """The queue owns the resident models; cancellation reaps GPU work."""
        root = self.script.parents[1]
        binary = Path.home() / '.cache' / 'eflow-speech' / 'build-compat' / 'eflow-kitten-worker.exe'
        cache = root.parent / '.cache' / 'kitten-tts'
        model = cache / 'KittenML' / 'kitten-tts-2' / 'main' / 'cpp' / 'model-gpu-f16.gguf'
        if not binary.exists() or not model.exists():
            raise HTTPException(503, 'Kitten-TTS 2 is not ready on the AI server. Typed help is available.')
        environment = self.decoder_environment()
        self.decoder.prepare(environment)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='eflow-reply-') as folder:
            target = Path(folder) / 'answer.wav'
            report = Path(folder) / 'speech.json'
            try:
                await self.kitten.generate(text, report, environment)
                token_seconds = time.monotonic() - started
                decoded = await self.decoder.decode(report, target, environment)
                try:
                    with (root / 'speech-latency.jsonl').open('a', encoding='utf-8') as timing:
                        timing.write(json.dumps({'characters': len(text), 'tokens_seconds': round(token_seconds, 3), 'decoder_seconds': round(decoded['seconds'], 3), 'total_seconds': round(time.monotonic() - started, 3), 'audio_seconds': decoded['audio_seconds']}) + '\n')
                except OSError:
                    logging.getLogger(__name__).warning('Could not record speech timing')
                audio = target.read_bytes()
                if len(audio) < 44 or not audio.startswith(b'RIFF'):
                    raise HTTPException(503, 'Speech returned invalid audio. The written answer is available.')
                if len(audio) > 12_000_000:
                    raise HTTPException(503, 'This spoken reply is too long. The written answer is available.')
                return {'audio': base64.b64encode(audio).decode(), 'mimeType': 'audio/wav', 'model': 'KittenML/kitten-tts-2'}
            except BaseException:
                await self.kitten.close()
                await self.decoder.close()
                raise

    async def start(self):
        async with self.start_lock:
            if self.process and self.process.returncode is None:
                return
            if not self.python.exists():
                raise HTTPException(503, 'The speech runtime is not installed on the AI server. Typed help is available.')
            with socket.socket() as reserve:
                reserve.bind(('127.0.0.1', 0))
                self.port = reserve.getsockname()[1]
            log = open(self.script.parents[1] / 'speech-runtime.log', 'ab', buffering=0)
            try:
                self.process = await asyncio.create_subprocess_exec(str(self.python), str(self.script), str(self.port), env={**os.environ, 'EFLOW_HELP_SPEECH_TOKEN': self.key}, stdout=log, stderr=log, **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
            finally:
                log.close()
            session = await get_session()
            for _ in range(60):
                if self.process.returncode is not None:
                    break
                try:
                    async with session.get(f'http://127.0.0.1:{self.port}/status', headers={'Authorization': 'Bearer ' + self.key}, timeout=aiohttp.ClientTimeout(total=1)) as response:
                        if response.status == 200:
                            return
                except (aiohttp.ClientError, TimeoutError):
                    pass
                await asyncio.sleep(.25)
            await self.close_asr()
            raise HTTPException(503, 'The speech runtime could not start. Typed help is available.')

    async def call(self, operation, payload):
        if operation != 'warmup' and self.asr_warmup and not self.asr_warmup.done():
            await asyncio.shield(self.asr_warmup)
        if self.busy.locked():
            raise HTTPException(429, 'Speech is busy. Please try again shortly.')
        async with self.busy:
            await self.start()
            session = await get_session()
            try:
                async with session.post(f'http://127.0.0.1:{self.port}/{operation}', json=payload, headers={'Authorization': 'Bearer ' + self.key}, timeout=aiohttp.ClientTimeout(total=180)) as response:
                    if response.status != 200:
                        raise HTTPException(503, 'Speech processing could not finish. Typed help is available.')
                    return await response.json()
            except (aiohttp.ClientError, TimeoutError) as exc:
                await self.close_asr()
                raise HTTPException(503, 'Speech processing timed out. Typed help is available.') from exc

    async def close(self):
        if self.asr_warmup and self.asr_warmup is not asyncio.current_task():
            self.asr_warmup.cancel()
            await asyncio.gather(self.asr_warmup, return_exceptions=True)
        self.asr_warmup = None
        await self.kitten.close()
        await self.decoder.close()
        await self.close_asr()

    async def close_asr(self):
        # ASR runs independently of the GPU queue. Recovering a failed input
        # worker must not interrupt another caller's queued spoken response.
        process, self.process = self.process, None
        await reap(process)

speech = SpeechService()
