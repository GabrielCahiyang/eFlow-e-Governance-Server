import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from model_runtime import execute_job
from pdf_offices import execute_office_pipeline, validate_office_request
from request_validation import validate_chat_request


def request():
    return {'schemaVersion': 1, 'document': 'CPDO coordinates the workshop.', 'tasks': [{'key': 't1', 'title': 'Workshop'}]}


def response(content=None, finish='stop'):
    data = content if content is not None else {'offices': [{'key': 'o1', 'name': 'CPDO', 'kind': 'responsible', 'evidence': 'CPDO coordinates the workshop.'}], 'taskOffices': {}, 'taskEvidence': {}}
    return {'choices': [{'message': {'content': json.dumps(data)}, 'finish_reason': finish}]}


class PdfOfficeTests(unittest.TestCase):
    def test_schema_prevents_prose_and_requires_the_expected_fields(self):
        llm = Mock(); llm.create_chat_completion.return_value = response()
        result = execute_office_pipeline(llm, request(), 'qwen3.5:4b')
        schema = llm.create_chat_completion.call_args.kwargs['response_format']['schema']
        self.assertEqual(set(schema['required']), {'offices', 'taskOffices', 'taskEvidence'})
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(json.loads(result['message']['content'])['offices'][0]['name'], 'CPDO')

    def test_unknown_office_evidence_and_truncation_fail_closed(self):
        for result in (response({'offices': [{'key': 'o', 'name': 'Fake Office', 'kind': 'responsible', 'evidence': 'Fake Office coordinates this.'}]}), response(finish='length')):
            llm = Mock(); llm.create_chat_completion.return_value = result
            with self.assertRaises(ValueError): execute_office_pipeline(llm, request(), 'test')

    def test_admission_bounds_context_and_rejects_mixed_or_streamed_modes(self):
        for mutate in (lambda r: r.update(document='x'*3201), lambda r: r['tasks'].append(r['tasks'][0]), lambda r: r.update(tasks='bad')):
            data = copy.deepcopy(request()); mutate(data)
            with self.assertRaises(ValueError): validate_office_request(data)
        for extra in ({'stream': True}, {'pdf_table_enrichment': {}}):
            with self.assertRaises(ValueError): validate_chat_request({'messages': [{'role': 'user', 'content': 'Offices'}], 'pdf_office_extraction': request(), **extra})

    def test_runtime_uses_schema_pipeline_budget_and_preserves_plain_chat(self):
        manager = Mock(); manager.load.return_value = 0
        manager.llm.tokenize.return_value = []; manager.llm.n_ctx.return_value = 8192
        manager.llm.create_chat_completion.return_value = response()
        with patch('model_registry.get_model', return_value=SimpleNamespace(n_ctx=8192)), patch.dict('os.environ', {'EFLOW_CHAT_OUTPUT_TOKENS': '64', 'EFLOW_PIPELINE_OUTPUT_TOKENS': '4096'}):
            execute_job(manager, {'model': 'test', 'messages': [{'role': 'user', 'content': 'Offices'}], 'pdf_office_extraction': request()}, Mock())
            self.assertEqual(manager.llm.create_chat_completion.call_args.kwargs['max_tokens'], 4096)
            execute_job(manager, {'model': 'test', 'messages': [{'role': 'user', 'content': 'Plain text'}]}, Mock())
            self.assertNotIn('response_format', manager.llm.create_chat_completion.call_args.kwargs)

    def test_public_gateway_preserves_the_operation(self):
        from public_gateway import ChatRequest
        body = ChatRequest(model='test', messages=[{'role': 'user', 'content': 'Offices'}], pdf_office_extraction=request())
        self.assertEqual(body.model_dump()['pdf_office_extraction'], request())


if __name__ == '__main__': unittest.main()
