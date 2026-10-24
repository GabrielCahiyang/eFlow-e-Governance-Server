import unittest
import asyncio
from unittest.mock import AsyncMock, patch
from help_assistant.speech_service import SpeechService
from fastapi import HTTPException
from unittest.mock import Mock

class SpeechLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_waits_for_previous_preview_and_admission_is_bounded(self):
        service = SpeechService()
        entered = asyncio.Event(); finish = asyncio.Event()
        calls = []
        class Response:
            status = 200
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
            async def json(self):
                calls.append('transcribed')
                if len(calls) == 1:
                    entered.set(); await finish.wait()
                return {'text': 'Recognized speech'}
        session = Mock(); session.post.return_value = Response()
        with patch.object(service, 'start', new=AsyncMock()), patch('help_assistant.speech_service.get_session', new=AsyncMock(return_value=session)), patch('help_assistant.speech_service.record_latency'):
            preview = asyncio.create_task(service.call('transcribe', {'audio':'preview'}))
            await entered.wait()
            final = asyncio.create_task(service.call('transcribe', {'audio':'final'}))
            await asyncio.sleep(0)
            with self.assertRaises(HTTPException) as overflow:
                await service.call('transcribe', {'audio':'extra'})
            self.assertEqual(overflow.exception.status_code, 429)
            finish.set()
            self.assertEqual((await preview)['text'], 'Recognized speech')
            self.assertEqual((await final)['text'], 'Recognized speech')
            self.assertEqual(session.post.call_count, 2)
            self.assertEqual(service.admitted_calls, 0)
            self.assertEqual(service.waiting_transcriptions, 0)

    async def test_cancelled_waiting_final_does_not_release_active_lock(self):
        service = SpeechService()
        await service.busy.acquire()
        pending = asyncio.create_task(service.call('transcribe', {}))
        await asyncio.sleep(0)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError): await pending
        self.assertTrue(service.busy.locked())
        self.assertEqual(service.admitted_calls, 0)
        self.assertEqual(service.waiting_transcriptions, 0)
        service.busy.release()

    async def test_simultaneous_admission_never_exceeds_one_active_one_waiting(self):
        service = SpeechService()
        entered = asyncio.Event()
        async def blocked_start():
            entered.set(); await asyncio.Event().wait()
        with patch.object(service, 'start', new=AsyncMock(side_effect=blocked_start)), patch('help_assistant.speech_service.record_latency'):
            first = asyncio.create_task(service.call('transcribe', {}))
            second = asyncio.create_task(service.call('transcribe', {}))
            await entered.wait()
            with self.assertRaises(HTTPException): await service.call('transcribe', {})
            first.cancel(); second.cancel()
            await asyncio.gather(first, second, return_exceptions=True)
        self.assertFalse(service.busy.locked())
        self.assertEqual(service.admitted_calls, 0)

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
