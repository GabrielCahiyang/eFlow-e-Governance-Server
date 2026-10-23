"""Decoder residency and cancellation without loading GPU models."""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch
from help_assistant.decoder_process import DecoderProcess

def worker(*responses):
    process = Mock(returncode=None, pid=123)
    process.stdout.readline = AsyncMock(side_effect=responses)
    process.stdin.drain = AsyncMock()
    return process

class DecoderTests(unittest.IsolatedAsyncioTestCase):
    async def test_preload_decode_release_decode_share_one_owned_worker(self):
        decoder = DecoderProcess()
        process = worker(b'{"ready":true}\n', b'{"audio_seconds":1}\n', b'{"released":true}\n', b'{"audio_seconds":2}\n')
        with patch('asyncio.create_subprocess_exec', new=AsyncMock(return_value=process)) as spawn, patch('help_assistant.decoder_process.reap', new=AsyncMock()) as reap:
            decoder.prepare({})
            await decoder.warmup
            await decoder.decode('first.json', 'first.wav', {})
            await decoder.release_gpu()
            result = await decoder.decode('second.json', 'second.wav', {})
            self.assertEqual(result['audio_seconds'], 2)
            spawn.assert_awaited_once()
            self.assertIn(b'{"operation":"release"}\n', [call.args[0] for call in process.stdin.write.call_args_list])
            reap.assert_not_called()
            await decoder.close()
            reap.assert_awaited_once_with(process)

    async def test_cpu_preload_does_not_delay_other_gpu_work(self):
        decoder = DecoderProcess()
        waiting = asyncio.Event()
        with patch.object(decoder, '_start', new=AsyncMock(side_effect=lambda env: None)):
            async def startup(env):
                await waiting.wait()
            decoder._start.side_effect = startup
            decoder.prepare({})
            await asyncio.sleep(0)
            await asyncio.wait_for(decoder.release_gpu(), .1)
            await decoder.close()
            self.assertIsNone(decoder.process)

    async def test_broken_decode_reaps_worker_before_next_job(self):
        decoder = DecoderProcess()
        decoder.process = worker(b'{"error":"failed"}\n')
        with patch('help_assistant.decoder_process.reap', new=AsyncMock()) as reap:
            with self.assertRaises(RuntimeError):
                await decoder.decode('input.json', 'output.wav', {})
            reap.assert_awaited_once()
            self.assertIsNone(decoder.process)

    async def test_shutdown_cancels_incomplete_background_load(self):
        decoder = DecoderProcess()
        process = worker()
        process.stdout.readline.side_effect = None
        process.stdout.readline.return_value = b'{"ready":true}\n'
        pending = asyncio.Event()
        async def never_ready():
            await pending.wait()
        process.stdout.readline.side_effect = never_ready
        with patch('asyncio.create_subprocess_exec', new=AsyncMock(return_value=process)), patch('help_assistant.decoder_process.reap', new=AsyncMock()) as reap:
            decoder.prepare({})
            await asyncio.sleep(.01)
            await asyncio.wait_for(decoder.close(), 1)
            self.assertIsNone(decoder.process)
            self.assertTrue(any(call.args == (process,) for call in reap.await_args_list))

if __name__ == '__main__':
    unittest.main()
