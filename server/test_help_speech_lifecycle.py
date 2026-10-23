import unittest
import asyncio
from unittest.mock import AsyncMock, patch
from help_assistant.speech_service import SpeechService

class SpeechLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_prepares_cpu_recognizer_and_decoder_without_gpu_generation(self):
        service = SpeechService()
        with patch.object(service, 'available', return_value=True), patch.object(service.decoder, 'prepare') as prepare, patch.object(service, 'call', new=AsyncMock()) as call:
            service.prepare_voice()
            await service.asr_warmup
            prepare.assert_called_once()
            call.assert_awaited_once_with('warmup', {})

    async def test_first_transcription_waits_for_warmup_instead_of_returning_busy(self):
        service = SpeechService()
        ready = asyncio.Event()
        async def warmup():
            async with service.busy:
                await ready.wait()
        service.asr_warmup = asyncio.create_task(warmup())
        await asyncio.sleep(0)
        request = asyncio.create_task(service.call('transcribe', {}))
        await asyncio.sleep(0)
        self.assertFalse(request.done())
        request.cancel()
        with self.assertRaises(asyncio.CancelledError): await request
        self.assertFalse(service.asr_warmup.cancelled())
        ready.set(); await service.asr_warmup

    async def test_input_recovery_preserves_other_callers_gpu_workers(self):
        service = SpeechService()
        service.process = object()
        with patch('help_assistant.speech_service.reap', new=AsyncMock()) as reap, patch.object(service.kitten, 'close', new=AsyncMock()) as kitten, patch.object(service.decoder, 'close', new=AsyncMock()) as decoder:
            await service.close_asr()
            reap.assert_awaited_once()
            kitten.assert_not_called()
            decoder.assert_not_called()
            self.assertIsNone(service.process)

    async def test_full_shutdown_closes_both_gpu_workers_and_input_worker(self):
        service = SpeechService()
        with patch('help_assistant.speech_service.reap', new=AsyncMock()) as reap, patch.object(service.kitten, 'close', new=AsyncMock()) as kitten, patch.object(service.decoder, 'close', new=AsyncMock()) as decoder:
            await service.close()
            kitten.assert_awaited_once()
            decoder.assert_awaited_once()
            reap.assert_awaited_once()
