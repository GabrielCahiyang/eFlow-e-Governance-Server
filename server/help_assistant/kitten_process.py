"""Owned native Kitten token worker, used only by the serialized GPU queue."""
import asyncio
import json
import os
from pathlib import Path
import re
from .decoder_process import reap

class KittenProcess:
    def __init__(self):
        self.process = None

    async def close(self):
        process, self.process = self.process, None
        cleanup = asyncio.create_task(reap(process))
        while True:
            try:
                await asyncio.shield(cleanup)
                return
            except asyncio.CancelledError:
                continue

    async def generate(self, text, report, environment):
        root = Path(__file__).resolve().parents[1]
        binary = Path.home() / '.cache' / 'eflow-speech' / 'build-compat' / 'eflow-kitten-worker.exe'
        cache = root.parent / '.cache' / 'kitten-tts'
        model = cache / 'KittenML' / 'kitten-tts-2' / 'main' / 'cpp' / 'model-gpu-f16.gguf'
        log_path = root / 'speech-token-runtime.log'
        try:
            if not self.process or self.process.returncode is not None:
                command = [str(binary), '--model', str(model), '--cache-dir', str(cache), '--decoder', 'student_w4', '--threads', '6', '--gpu-layers', '99', '--data', str(root / '.speech-venv' / 'Lib' / 'site-packages' / 'kitten_tts_cpp' / 'data')]
                with log_path.open('ab', buffering=0) as log:
                    offset = log.tell()
                    self.process = await asyncio.create_subprocess_exec(*command, env=environment, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=log, **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
                line = await asyncio.wait_for(self.process.stdout.readline(), 180)
                if not line or not json.loads(line).get('ready'):
                    raise RuntimeError('Kitten-TTS 2 could not start')
                with log_path.open('rb') as diagnostics:
                    diagnostics.seek(0, 2)
                    diagnostics.seek(max(offset, diagnostics.tell() - 64_000))
                    if not re.search(rb'offloaded [1-9]\d*/[1-9]\d* layers to GPU', diagnostics.read(64_000)):
                        raise RuntimeError('Speech GPU acceleration is unavailable')
            self.process.stdin.write((json.dumps({'text': text, 'report': str(report)}) + '\n').encode())
            await self.process.stdin.drain()
            line = await asyncio.wait_for(self.process.stdout.readline(), 120)
            if not line or not json.loads(line).get('complete') or not Path(report).exists():
                raise RuntimeError('Kitten-TTS 2 could not finish this reply')
        except BaseException:
            await self.close()
            raise
