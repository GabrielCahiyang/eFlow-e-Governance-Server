"""Live model routing, constrained references and memory policy without weights."""
import unittest
import json
from unittest.mock import AsyncMock, patch
from help_assistant.grounding import selection_payload, grounded_answer, UNKNOWN
from help_assistant.model_policy import CHAT_MODEL, LIVE_MODEL, model_for, speech_needs_unload
from model_registry import get_model
import test_help_assistant_routes as routes_test
FACT, REQUEST = routes_test.FACT, routes_test.REQUEST

class LiveModelTests(unittest.TestCase):
    def test_download_is_pinned_and_qwen_is_retained(self):
        entry = get_model(LIVE_MODEL)
        self.assertEqual(entry.extra_kwargs['n_gpu_layers'], 99)
        self.assertEqual(len(entry.sha256), 64)
        self.assertIsNotNone(entry.hf_revision)
        self.assertIsNotNone(get_model(CHAT_MODEL))
        self.assertEqual(model_for('chat'), CHAT_MODEL)
        self.assertEqual(model_for('live'), LIVE_MODEL)
        self.assertFalse(speech_needs_unload(LIVE_MODEL))
        for tag in (None, CHAT_MODEL, 'qwen3.5:4b', 'deepseek-r1:8b'):
            self.assertTrue(speech_needs_unload(tag))

    def test_numbered_selection_maps_only_checked_sources_and_preserves_original_ids(self):
        body = selection_payload('Why is this task waiting?', [FACT], [], LIVE_MODEL)
        self.assertEqual(body['_help_selection'], ['0'])
        self.assertEqual(body['model'], LIVE_MODEL)
        self.assertNotIn('task:one', body['messages'][-1]['content'])
        self.assertEqual(json.loads(body['messages'][-1]['content'])['sources'][0]['id'], '0')
        answer = grounded_answer('{"source_ids":["0"]}', [FACT], LIVE_MODEL)
        self.assertEqual(answer['sources'], [FACT])
        self.assertEqual(answer['model'], LIVE_MODEL)
        for raw in ('{"source_ids":["1"]}', '{"source_ids":[{"id":"0"}]}', '{"source_ids":["task:one"]}'):
            self.assertEqual(grounded_answer(raw, [FACT], LIVE_MODEL)['answer'], UNKNOWN)

    def test_selected_workflow_keeps_its_permission_rule_without_adding_project_records(self):
        facts = [
            {'id':'guide:review:0', 'kind':'guide', 'text':'Independent review is needed.'},
            {'id':'guide:review:1', 'kind':'guide', 'text':'Review permission does not permit posting.'},
            FACT,
        ]
        answer = grounded_answer('{"source_ids":["0"]}', facts, LIVE_MODEL)
        self.assertEqual(answer['sources'], facts[:2])

class LiveRouteTests(unittest.TestCase):
    setUp = routes_test.HelpRouteTests.setUp
    def test_live_uses_tiny_model_but_does_not_allow_arbitrary_model_selection(self):
        self.queue.submit.return_value['result']['message']['content'] = '{"source_ids":["0"]}'
        with patch('help_assistant.routes.Caller', return_value=self.caller), patch('help_assistant.routes.guides', return_value=[FACT]):
            response = self.client.post('/api/help-assistant/chat', headers=self.headers, json={'question': 'Why is this project waiting?', 'requestId': REQUEST, 'mode': 'live'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['model'], LIVE_MODEL)
            self.assertEqual(response.json()['sources'], [FACT])
            self.assertEqual(self.queue.submit.call_args.args[1]['model'], LIVE_MODEL)
            self.caller.recheck.assert_awaited_once_with([FACT])
            self.queue.submit.reset_mock()
            invalid = self.client.post('/api/help-assistant/chat', headers=self.headers, json={'question': 'Help', 'requestId': REQUEST, 'mode': 'custom'})
            self.assertEqual(invalid.status_code, 422)
            self.queue.submit.assert_not_called()

class LiveResidencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_speech_reuses_only_the_tiny_selector_and_releases_qwen(self):
        import main
        from help_assistant.speech_service import speech
        for model in (LIVE_MODEL, CHAT_MODEL, 'qwen3.5:4b'):
            manager = AsyncMock()
            manager.loaded_tag = model
            with patch.object(main, 'manager', manager), patch.object(speech, 'native_speech', new=AsyncMock(return_value={'audio':'test'})):
                await main._process_queued_chat({'model':'kitten-tts-2', '_help_speech':{'id':'qa-resident', 'text':'Check the task.'}})
                self.assertEqual(manager.unload.await_count, 0 if model == LIVE_MODEL else 1)
                speech.results.pop('qa-resident', None)
