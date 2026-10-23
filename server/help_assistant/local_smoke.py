"""Real local speech round-trip with synthetic text; never reads business data."""
import asyncio
import base64
import json
from pathlib import Path
import time
import wave
from .speech_service import speech
from http_client import close_session

async def run():
    root = Path(__file__).resolve().parents[1]
    results = []
    try:
        for text in ('Check the pending task review.', 'Open the project table to check its tasks.'):
            started = time.monotonic()
            result = await speech.native_speech(text)
            seconds = time.monotonic() - started
            target = root / f'help-voice-test-roundtrip-{len(results)}.wav'
            target.write_bytes(base64.b64decode(result['audio']))
            with wave.open(str(target)) as audio:
                duration = audio.getnframes() / audio.getframerate()
            # Same mono 16 kHz PCM WAV sent by the browser microphone.
            import numpy as np
            with wave.open(str(target)) as audio:
                samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2')
            frames = np.interp(np.arange(0, len(samples), 1.5), np.arange(len(samples)), samples).astype('<i2')
            import io
            memory = io.BytesIO()
            with wave.open(memory, 'wb') as output:
                output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000); output.writeframes(frames.tobytes())
            transcribed = await speech.call('transcribe', {'audio': base64.b64encode(memory.getvalue()).decode()})
            expected = set(text.lower().strip('.').split())
            actual = set(transcribed['text'].lower().strip('.').split())
            if len(expected & actual) / len(expected) < .7:
                raise RuntimeError('The speech roundtrip did not preserve the synthetic sentence')
            row = {'input': text, 'speech_seconds': round(seconds, 2), 'audio_seconds': duration, 'transcribed': transcribed['text']}
            results.append(row)
            print(json.dumps(row), flush=True)
        (root / '.speech-venv' / 'voice-ready.json').write_text(json.dumps({'verified': '2026-10-22', 'tts': 'KittenML/kitten-tts-2', 'asr': 'Parakeet Redux', 'runtime': 'cuda-f16-v1', 'roundtrips': results}, indent=2))
        (root / 'help-local-roundtrip-check.json').write_text(json.dumps(results, indent=2))
    finally:
        await speech.close()
        await close_session()

if __name__ == '__main__':
    asyncio.run(run())
