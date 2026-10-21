import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pdf_table_enrichment import execute_pdf_table_pipeline, validate_pdf_table_request
from request_validation import validate_chat_request
from model_runtime import execute_job
from network_logging import install_network_logging, SuccessfulHealthPoll
import logging


def request():
    return {'schemaVersion': 1,
            'tasks': [{'key': f'task-{i}', 'title': f'Action {i}', 'methodology': [], 'schedule': 'Month 1'} for i in range(1, 11)],
            'costs': [{'sourceId': f'budget-{i}', 'particular': f'Cost {i}', 'amount': i * 100} for i in range(1, 17)]}


def answer(**kwargs):
    schema = kwargs['response_format']['schema']
    values = {}
    for key, value in schema['properties'].items():
        values[key] = {'priority': 'high', 'estimatedHours': 8} if key.startswith('task-') else value['enum'][0]
    return {'choices': [{'message': {'content': json.dumps(values)}, 'finish_reason': 'stop'}]}


class PdfTableTests(unittest.TestCase):
    def test_complete_source_coverage_and_schema_required_keys(self):
        llm = Mock(); llm.create_chat_completion.side_effect = answer
        result = execute_pdf_table_pipeline(llm, request(), 'deepseek-r1:8b')
        parsed = json.loads(result['message']['content'])
        self.assertEqual([t['key'] for t in parsed['tasks']], [f'task-{i}' for i in range(1, 11)])
        self.assertEqual([a['sourceId'] for a in parsed['allocations']], [f'budget-{i}' for i in range(1, 17)])
        self.assertEqual(llm.create_chat_completion.call_count, 4)
        for call in llm.create_chat_completion.call_args_list:
            schema = call.kwargs['response_format']['schema']
            self.assertEqual(set(schema['required']), set(schema['properties']))
            self.assertFalse(schema['additionalProperties'])
        self.assertNotIn('amount', parsed['allocations'][0])

    def test_no_costs_needs_no_cost_generation(self):
        body = request(); body['tasks'] = body['tasks'][:1]; body['costs'] = []
        llm = Mock(); llm.create_chat_completion.side_effect = answer
        result = json.loads(execute_pdf_table_pipeline(llm, body, 'test')['message']['content'])
        self.assertEqual(len(result['tasks']), 1)
        self.assertEqual(result['allocations'], [])
        self.assertEqual(llm.create_chat_completion.call_count, 1)

    def test_wrong_count_repairs_once_without_changing_source(self):
        body = request(); before = copy.deepcopy(body)
        llm = Mock()
        calls = 0
        def generate(**kwargs):
            nonlocal calls
            calls += 1
            return {'choices': [{'message': {'content': '{}'}}]} if calls == 1 else answer(**kwargs)
        llm.create_chat_completion.side_effect = generate
        result = json.loads(execute_pdf_table_pipeline(llm, body, 'test')['message']['content'])
        self.assertEqual(len(result['tasks']), 10)
        self.assertEqual(llm.create_chat_completion.call_count, 5)
        self.assertEqual(body, before)

    def test_repeated_invalid_and_truncated_outputs_fail_closed(self):
        for response in ({'choices': [{'message': {'content': '{}'}}]},
                         {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}):
            llm = Mock(); llm.create_chat_completion.return_value = response
            with self.assertRaisesRegex(ValueError, 'No work was saved'):
                execute_pdf_table_pipeline(llm, request(), 'test')
            self.assertEqual(llm.create_chat_completion.call_count, 2)

    def test_admission_rejects_invalid_references_and_mixed_modes(self):
        for mutate in (lambda b: b['tasks'].append(b['tasks'][0]),
                       lambda b: b['costs'].append(b['costs'][0]),
                       lambda b: b.update(tasks=[])):
            body = request(); mutate(body)
            with self.assertRaises(ValueError): validate_pdf_table_request(body)
        for extra in ({'stream': True}, {'workspace_decomposition': {}}):
            with self.assertRaises(ValueError):
                validate_chat_request({'messages': [{'role': 'user', 'content': 'PDF'}],
                                       'pdf_table_enrichment': request(), **extra})

    def test_runtime_routes_pdf_to_pipeline_with_pipeline_token_budget(self):
        manager = Mock(); manager.load.return_value = 0
        manager.llm = Mock(); manager.llm.tokenize.return_value = []; manager.llm.n_ctx.return_value = 8192
        manager.llm.create_chat_completion.side_effect = answer
        with patch('model_registry.get_model', return_value=SimpleNamespace(n_ctx=8192)), \
             patch.dict('os.environ', {'EFLOW_CHAT_OUTPUT_TOKENS': '64', 'EFLOW_PIPELINE_OUTPUT_TOKENS': '4096'}):
            out = execute_job(manager, {'model': 'test', 'messages': [{'content': 'PDF'}], 'pdf_table_enrichment': request()}, Mock())
        self.assertEqual(len(json.loads(out['message']['content'])['tasks']), 10)
        self.assertEqual(manager.llm.create_chat_completion.call_args.kwargs['max_tokens'], 4096)

    def test_gateway_preserves_explicit_mode(self):
        from public_gateway import ChatRequest
        out = ChatRequest(model='test', messages=[{'role': 'user', 'content': 'PDF'}],
                          pdf_table_enrichment=request()).model_dump(exclude_none=True)
        self.assertEqual(out['pdf_table_enrichment'], request())


class NetworkLogTests(unittest.TestCase):
    def test_successful_health_only_filter(self):
        filt = SuccessfulHealthPoll()
        def record(path, status):
            return logging.LogRecord('uvicorn.access', 20, '', 0, '%s %s %s %s %s',
                                     ('peer', 'GET', path, '1.1', status), None)
        self.assertFalse(filt.filter(record('/controlpanelEflow/api/health', 200)))
        self.assertTrue(filt.filter(record('/controlpanelEflow/api/health', 503)))
        self.assertTrue(filt.filter(record('/controlpanelEflow/api/jobs', 200)))

    def test_only_known_windows_socket_callback_is_classified(self):
        loop = Mock(); previous = Mock(); loop.get_exception_handler.return_value = previous
        install_network_logging(loop)
        handler = loop.set_exception_handler.call_args.args[0]
        exc = ConnectionResetError(); exc.winerror = 10054
        context = {'exception': exc, 'handle': '_ProactorBasePipeTransport._call_connection_lost(None)'}
        handler(loop, context); previous.assert_not_called()
        for context in ({'exception': exc, 'handle': 'application_callback'}, {'exception': ValueError('real failure')}):
            handler(loop, context)
        self.assertEqual(previous.call_count, 2)


if __name__ == '__main__': unittest.main()
