"""Isolated, CPU-only speech runtime. Binds loopback; never exposes model keys."""
import asyncio
import base64
import hmac
import io
import os
import sys
import wave
import aiohttp
from contextlib import asynccontextmanager

try:
    from .parakeet_runtime import ParakeetRuntime
except ImportError:
    from parakeet_runtime import ParakeetRuntime

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

asr = ParakeetRuntime()

@asynccontextmanager
async def lifespan(_app):
    yield
    await asr.close()

app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
busy = asyncio.Lock()

@app.middleware('http')
async def authenticate(request: Request, call_next):
    from fastapi.responses import JSONResponse
    expected = os.environ.get('EFLOW_HELP_SPEECH_TOKEN', '')
    if not expected or not hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + expected):
        return JSONResponse({'detail': 'Unauthorized'}, status_code=401)
    return await call_next(request)

class AudioRequest(BaseModel):
    audio: str = Field(min_length=44, max_length=1_500_000)

def checked_audio(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        with wave.open(io.BytesIO(raw)) as wav:
            duration = wav.getnframes() / wav.getframerate()
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000 or not .25 <= duration <= 25:
                raise ValueError('Unsupported audio')
        return raw
    except (ValueError, wave.Error, EOFError, ZeroDivisionError) as exc:
        raise HTTPException(422, 'Send mono 16 kHz PCM WAV audio between 0.25 and 25 seconds.') from exc

async def transcribe(encoded):
    try:
        return await asr.transcribe(checked_audio(encoded))
    except (aiohttp.ClientError, TimeoutError, RuntimeError) as exc:
        raise HTTPException(503, 'Parakeet could not finish. Check the AI server or retry the mic.') from exc

@app.get('/status')
def status():
    return {'ready': True, 'runtime': 'Parakeet Redux CPU'}

@app.post('/warmup')
async def warmup():
    async with busy:
        await asr.start()
    return {'ready': True}

@app.post('/transcribe')
async def transcription(payload: AudioRequest):
    if busy.locked():
        raise HTTPException(429, 'Speech is busy. Please try again shortly.')
    async with busy:
        return await transcribe(payload.audio)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
