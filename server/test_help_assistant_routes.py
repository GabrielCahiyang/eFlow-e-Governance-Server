"""Isolated API contract tests; native inference and deployed auth are mocked."""
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
from help_assistant.routes import make_router
from help_assistant.grounding import OFF_TOPIC
from help_assistant.speech_service import speech

USER = '00000000-0000-4000-8000-000000000001'
REQUEST = '10000000-0000-4000-8000-000000000001'
FACT = {'id': 'task:one', 'text': 'QA work is awaiting review.', 'title': 'QA work', 'kind': 'task'}

class HelpRouteTests(unittest.TestCase):
    def test_chunked_speech_preserves_words_and_rechecks_each_part(self):
        fact = {**FACT, 'text': 'Open the project table and select the task to review its recorded budget. Then choose Request petty cash and provide the required details.'}
        requested = []
        async def submit(owner, body, **kwargs):
            if '_help_speech' not in body:
                return {'job_id': 'chat', 'status': 'completed', 'result': {'message': {'content': '{"source_ids":["task:one"]}'}}}
            operation = body['_help_speech']; requested.append(operation['text'])
            speech.results[operation['id']] = {'audio': 'synthetic', 'mimeType': 'audio/wav'}
            return {'job_id': 'speech', 'status': 'completed'}
        self.queue.submit.side_effect = submit
        with patch('help_assistant.routes.Caller', return_value=self.caller), patch('help_assistant.routes.guides', return_value=[fact]):
            reply = self.client.post('/api/help-assistant/chat', headers=self.headers, json={'question': 'How do I request petty cash?', 'requestId': REQUEST}).json()
            first = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'replyId': reply['replyId'], 'part': 0})
            self.assertEqual(first.status_code, 200)
            self.assertGreater(first.json()['parts'], 1)
            for part in range(1, first.json()['parts']):
                response = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'replyId': reply['replyId'], 'part': part})
                self.assertEqual(response.status_code, 200)
            self.assertEqual(' '.join(requested), fact['text'])
            self.assertLessEqual(len(requested[0]), 65)
            self.caller.recheck.side_effect = HTTPException(403, 'Access revoked')
            denied = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'replyId': reply['replyId'], 'part': 0})
            self.assertEqual(denied.status_code, 403)

    def test_invalid_speech_part_is_rejected_without_generation(self):
        with patch('help_assistant.routes.Caller', return_value=self.caller), patch('help_assistant.routes.guides', return_value=[FACT]):
            reply = self.client.post('/api/help-assistant/chat', headers=self.headers, json={'question': 'Which task needs review?', 'requestId': REQUEST}).json()
            self.queue.submit.reset_mock()
            for part in (-1, 1, 4):
                response = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'replyId': reply['replyId'], 'part': part})
                self.assertEqual(response.status_code, 422)
            self.queue.submit.assert_not_called()

    def setUp(self):
        self.caller = AsyncMock()
        self.caller.profile = {'id': USER, 'role': 'head'}
        self.caller.verify.return_value = self.caller
        self.caller.project_facts.return_value = []
        self.queue = AsyncMock()
        self.queue.submit.return_value = {'job_id': 'qa-job', 'status': 'completed', 'result': {'message': {'content': '{"source_ids":["task:one"]}'}}}
        self.app = FastAPI(); self.app.include_router(make_router(self.queue))
        self.client = TestClient(self.app)
        self.headers = {'X-eFlow-User-Id': USER, 'X-eFlow-Session': 'synthetic-session'}

    def test_off_topic_request_never_sends_project_records_to_the_model(self):
        with patch('help_assistant.routes.Caller', return_value=self.caller):
            response = self.client.post('/api/help-assistant/chat', headers=self.headers, json={'question': 'Tell me the distance between planets.', 'requestId': REQUEST})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['answer'], OFF_TOPIC)
        self.caller.project_facts.assert_not_called(); self.queue.submit.assert_not_called()

    def test_checked_sources_are_returned_instead_of_model_generated_claims(self):
        with patch('help_assistant.routes.Caller', return_value=self.caller), patch('help_assistant.routes.guides', return_value=[FACT]):
            response = self.client.post('/api/help-assistant/chat', headers=self.headers, json={'question': 'Why is my project waiting?', 'requestId': REQUEST})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['answer'], FACT['text'])
        self.caller.recheck.assert_awaited_once_with([FACT])
        self.assertEqual(self.caller.verify.await_count, 2)
        self.assertEqual(self.queue.submit.call_args.args[1]['model'], 'qwen3.5:2b')

    def test_speech_accepts_only_owner_scoped_server_reply_ids(self):
        with patch('help_assistant.routes.Caller', return_value=self.caller), patch('help_assistant.routes.speech.call', new_callable=AsyncMock) as speech:
            arbitrary = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'text': 'Speak unrelated content.'})
            unknown = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'replyId': REQUEST})
        self.assertEqual(arbitrary.status_code, 422)
        self.assertEqual(unknown.status_code, 404)
        speech.assert_not_called()

    def test_no_caller_header_is_denied_before_any_record_query(self):
        with patch('help_assistant.routes.Caller') as factory:
            response = self.client.get('/api/help-assistant/projects')
        self.assertEqual(response.status_code, 401); factory.assert_not_called()

    def test_speech_rechecks_access_after_inference_and_discards_audio_if_revoked(self):
        async def submit(owner, body, **kwargs):
            if '_help_speech' in body:
                operation = body['_help_speech']['id']
                speech.results[operation] = {'audio': 'synthetic', 'mimeType': 'audio/wav'}
                return {'job_id': 'speech-job', 'status': 'completed'}
            return {'job_id': 'chat-job', 'status': 'completed', 'result': {'message': {'content': '{"source_ids":["task:one"]}'}}}
        self.queue.submit.side_effect = submit
        with patch('help_assistant.routes.Caller', return_value=self.caller), patch('help_assistant.routes.guides', return_value=[FACT]):
            reply = self.client.post('/api/help-assistant/chat', headers=self.headers, json={'question': 'Which task needs review?', 'requestId': REQUEST}).json()
            self.caller.recheck.side_effect = [None, HTTPException(403, 'Project access changed.')]
            response = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'replyId': reply['replyId']})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(speech.results)
        self.assertEqual(self.queue.cancel.call_args.args[0], 'speech-job')

    def test_another_user_cannot_replay_a_private_reply(self):
        with patch('help_assistant.routes.Caller', return_value=self.caller), patch('help_assistant.routes.guides', return_value=[FACT]):
            reply = self.client.post('/api/help-assistant/chat', headers=self.headers, json={'question': 'Which task needs review?', 'requestId': REQUEST}).json()
            self.queue.submit.reset_mock()
            self.caller.profile = {'id': 'another-user', 'role': 'head'}
            response = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'replyId': reply['replyId']})
        self.assertEqual(response.status_code, 404)
        self.queue.submit.assert_not_called()

    def test_cached_audio_still_rechecks_permission_before_delivery(self):
        async def submit(owner, body, **kwargs):
            operation = body['_help_speech']['id']
            speech.results[operation] = {'audio': 'synthetic', 'mimeType': 'audio/wav'}
            return {'job_id': 'speech-job', 'status': 'completed'}
        with patch('help_assistant.routes.Caller', return_value=self.caller), patch('help_assistant.routes.guides', return_value=[FACT]):
            reply = self.client.post('/api/help-assistant/chat', headers=self.headers, json={'question': 'Which task needs review?', 'requestId': REQUEST}).json()
            self.queue.submit.side_effect = submit
            first = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'replyId': reply['replyId']})
            self.assertEqual(first.status_code, 200)
            self.queue.submit.reset_mock()
            cached = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'replyId': reply['replyId']})
            self.assertEqual(cached.status_code, 200)
            self.queue.submit.assert_not_called()
            self.caller.recheck.side_effect = [None, HTTPException(403, 'Project access changed.')]
            revoked = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'replyId': reply['replyId']})
            self.assertEqual(revoked.status_code, 403)
            self.queue.submit.assert_not_called()

    def test_role_change_invalidates_an_old_spoken_answer(self):
        with patch('help_assistant.routes.Caller', return_value=self.caller), patch('help_assistant.routes.guides', return_value=[FACT]):
            reply = self.client.post('/api/help-assistant/chat', headers=self.headers, json={'question': 'Which task needs review?', 'requestId': REQUEST}).json()
            self.queue.submit.reset_mock()
            self.caller.profile = {'id': USER, 'role': 'admin'}
            response = self.client.post('/api/help-assistant/speech', headers=self.headers, json={'replyId': reply['replyId']})
        self.assertEqual(response.status_code, 409)
        self.queue.submit.assert_not_called()

    def test_custom_model_context_and_history_overflow_are_rejected(self):
        with patch('help_assistant.routes.Caller', return_value=self.caller):
            response = self.client.post('/api/help-assistant/chat', headers=self.headers, json={'question': 'Why is my project waiting?', 'requestId': REQUEST, 'context': {'private_records': 'invented'}})
        self.assertEqual(response.status_code, 422)
        self.queue.submit.assert_not_called()

if __name__ == '__main__':
    unittest.main()
