import unittest
from unittest.mock import AsyncMock, Mock
from help_assistant.parakeet_runtime import ParakeetRuntime


class Response:
    status = 200
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def json(self): return {'text': 'Open the project table.'}


class ParakeetRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_consecutive_previews_reuse_the_same_owned_loaded_process(self):
        runtime = ParakeetRuntime()
        process = Mock(returncode=None, pid=123)
        process.wait = AsyncMock()
        session = Mock(); session.close = AsyncMock(); session.post.return_value = Response()
        runtime.process = process; runtime.session = session; runtime.origin = 'http://127.0.0.1:12345'
        first = await runtime.transcribe(b'first PCM WAV')
        second = await runtime.transcribe(b'longer PCM WAV')
        self.assertEqual(first['text'], 'Open the project table.')
        self.assertEqual(second['model'], 'moondream/parakeet-redux')
        self.assertIs(runtime.process, process)
        self.assertEqual(session.post.call_count, 2)
        process.kill.assert_not_called()
        await runtime.close()
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()
        session.close.assert_awaited_once()

    async def test_failed_preview_reaps_its_owned_process_before_retry(self):
        runtime = ParakeetRuntime()
        process = Mock(returncode=None); process.wait = AsyncMock()
        session = Mock(); session.close = AsyncMock(); session.post.side_effect = TimeoutError()
        runtime.process = process; runtime.session = session; runtime.origin = 'http://127.0.0.1:12345'
        with self.assertRaises(TimeoutError):
            await runtime.transcribe(b'PCM WAV')
        self.assertIsNone(runtime.process)
        self.assertIsNone(runtime.session)
        process.kill.assert_called_once()
