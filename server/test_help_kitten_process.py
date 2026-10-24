import asyncio
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch, mock_open
from help_assistant.kitten_process import KittenProcess

class KittenProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_replies_reuse_model_and_normalizer(self):
        runtime = KittenProcess()
        process = Mock(returncode=None)
        process.stdin.drain = AsyncMock()
        process.stdout.readline = AsyncMock(side_effect=[b'{"ready":true}\n', b'{"complete":true}\n', b'{"complete":true}\n'])
        log = mock_open(read_data=b'offloaded 29/29 layers to GPU')
        log.return_value.tell.return_value = 0
        with patch('asyncio.create_subprocess_exec', new=AsyncMock(return_value=process)) as spawn, patch.object(Path, 'open', log), patch.object(Path, 'exists', return_value=True), patch('help_assistant.kitten_process.reap', new=AsyncMock()) as reap:
            await runtime.generate('Open the project.', 'one.json', {})
            self.assertTrue(runtime.last_timing['cold_worker'])
            await runtime.generate('Check the task.', 'two.json', {})
            self.assertFalse(runtime.last_timing['cold_worker'])
            self.assertEqual(runtime.last_timing['worker_start_seconds'], 0)
            spawn.assert_awaited_once()
            self.assertTrue(any(str(arg).endswith('model-gpu-f16.gguf') for arg in spawn.call_args.args))
            self.assertEqual(process.stdin.write.call_count, 2)
            reap.assert_not_called()
            await runtime.close()
            reap.assert_awaited_once_with(process)

    async def test_gpu_check_reads_end_of_verbose_current_startup_log(self):
        runtime = KittenProcess()
        process = Mock(returncode=None)
        process.stdin.drain = AsyncMock()
        process.stdout.readline = AsyncMock(side_effect=[b'{"ready":true}\n', b'{"complete":true}\n'])
        log = mock_open(read_data=b'offloaded 29/29 layers to GPU')
        log.return_value.tell.side_effect = [1000, 501000]
        with patch('asyncio.create_subprocess_exec', new=AsyncMock(return_value=process)), patch.object(Path, 'open', log), patch.object(Path, 'exists', return_value=True), patch('help_assistant.kitten_process.reap', new=AsyncMock()):
            await runtime.generate('Open the project.', 'one.json', {})
            self.assertIn(unittest.mock.call(437000), log.return_value.seek.call_args_list)
            await runtime.close()

    async def test_cpu_fallback_is_rejected_and_owned_worker_is_reaped(self):
        runtime = KittenProcess()
        process = Mock(returncode=None)
        process.stdout.readline = AsyncMock(return_value=b'{"ready":true}\n')
        log = mock_open(read_data=b'offloaded 0/29 layers to GPU')
        log.return_value.tell.return_value = 0
        with patch('asyncio.create_subprocess_exec', new=AsyncMock(return_value=process)), patch.object(Path, 'open', log), patch('help_assistant.kitten_process.reap', new=AsyncMock()) as reap:
            with self.assertRaisesRegex(RuntimeError, 'GPU'):
                await runtime.generate('Open the project.', 'one.json', {})
            reap.assert_awaited_once_with(process)
            self.assertIsNone(runtime.process)

    async def test_cancelled_generation_reaps_before_returning(self):
        runtime = KittenProcess()
        process = Mock(returncode=None)
        process.stdin.drain = AsyncMock()
        process.stdout.readline = AsyncMock(side_effect=asyncio.CancelledError())
        runtime.process = process
        with patch('help_assistant.kitten_process.reap', new=AsyncMock()) as reap:
            with self.assertRaises(asyncio.CancelledError):
                await runtime.generate('Open the project.', 'one.json', {})
            reap.assert_awaited_once_with(process)
