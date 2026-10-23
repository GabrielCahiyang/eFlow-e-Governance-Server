"""Model ownership and bounded generation, confined to the inference process."""
import gc
import json
import logging
import os
import time

from model_registry import download_model

logger = logging.getLogger(__name__)


class ModelManager:
    def __init__(self):
        self.llm = None
        self.loaded_tag = None

    def load(self, entry):
        if self.loaded_tag == entry.tag and self.llm is not None:
            return 0.0
        self.unload()
        if not entry.is_downloaded:
            download_model(entry)
        from llama_cpp import Llama
        started = time.perf_counter()
        kwargs = dict(model_path=str(entry.local_path), n_ctx=entry.n_ctx,
                      n_gpu_layers=99, chat_format=entry.chat_format, verbose=False)
        kwargs.update(entry.extra_kwargs)
        self.llm = Llama(**kwargs)
        self.loaded_tag = entry.tag
        return (time.perf_counter() - started) * 1000

    def unload(self):
        if self.llm is not None:
            self.llm.close()
            self.llm = None
        self.loaded_tag = None
        gc.collect()


class BoundedModel:
    """Use the real model's token/context API and bound each generation call."""
    def __init__(self, llm, output_limit):
        self._llm = llm
        self.output_limit = output_limit
        self.inference_ms = 0.0
        self.calls = 0

    def __getattr__(self, key):
        return getattr(self._llm, key)

    def create_chat_completion(self, **kwargs):
        messages = kwargs.get('messages', [])
        prompt_tokens = sum(len(self._llm.tokenize(m['content'].encode('utf-8'), add_bos=False))
                            for m in messages) + 256
        available = self._llm.n_ctx() - prompt_tokens
        if available < 64:
            raise ValueError('The conversation exceeds this model context. Shorten it or split the document.')
        kwargs['max_tokens'] = min(int(kwargs.get('max_tokens') or self.output_limit), self.output_limit, available)
        started = time.perf_counter()
        result = self._llm.create_chat_completion(**kwargs)
        self.inference_ms += (time.perf_counter() - started) * 1000
        self.calls += 1
        return result


def execute_job(manager, body, send):
    from model_registry import get_model
    from proposal_pipeline import execute_proposal_pipeline, is_proposal_decomposition_prompt
    from workspace_decomposition import execute_workspace_pipeline, validate_workspace_request
    from workspace_staffing import execute_staffing_pipeline, validate_staffing_request
    from pdf_table_enrichment import execute_pdf_table_pipeline, validate_pdf_table_request
    from pdf_offices import execute_office_pipeline, validate_office_request

    tag = body['model']
    entry = get_model(tag)
    if not entry:
        raise ValueError(f'Unknown model: {tag}')
    if body.get('workspace_decomposition') is not None:
        validate_workspace_request(body['workspace_decomposition'])
    if body.get('workspace_staffing') is not None:
        validate_staffing_request(body['workspace_staffing'])
    if body.get('pdf_table_enrichment') is not None:
        validate_pdf_table_request(body['pdf_table_enrichment'])
    if body.get('pdf_office_extraction') is not None:
        validate_office_request(body['pdf_office_extraction'])
    started = time.perf_counter()
    send('progress', {'stage': 'loading_model', 'message': 'Preparing the AI.'})
    load_ms = manager.load(entry)
    send('loaded', {'model': tag, 'load_ms': round(load_ms, 1)})
    messages = [{'role': m.get('role', 'user'), 'content': m.get('content', '')}
                for m in body.get('messages', [])]
    heavy = (body.get('workspace_decomposition') is not None
             or body.get('pdf_table_enrichment') is not None
             or body.get('pdf_office_extraction') is not None
             or body.get('workspace_staffing') is not None
             or is_proposal_decomposition_prompt(messages))
    maximum = int(os.getenv('EFLOW_PIPELINE_OUTPUT_TOKENS', '4096') if heavy
                  else os.getenv('EFLOW_CHAT_OUTPUT_TOKENS', '1024'))
    maximum = max(64, min(maximum, entry.n_ctx - 64))
    llm = BoundedModel(manager.llm, maximum)
    generate_started = time.time_ns()
    if not heavy or body.get('_stream_id'):
        send('progress', {'stage': 'generating_response', 'message': 'Generating the response.'})
    if body.get('_stream_id'):
        content = ''
        first_token_ms = None
        for chunk in llm.create_chat_completion(
                messages=messages, stream=True,
                max_tokens=min(int(body.get('max_tokens') or maximum), maximum)):
            choices = chunk.get('choices') or []
            token = choices[0].get('delta', {}).get('content', '') if choices else ''
            if token:
                if first_token_ms is None:
                    first_token_ms = (time.time_ns() - generate_started) / 1e6
                content += token
                send('chunk', {'model': tag, 'message': {'role': 'assistant', 'content': token}, 'done': False})
        count = len(manager.llm.tokenize(content.encode('utf-8'), add_bos=False))
        result = {'model': tag, 'message': {'role': 'assistant', 'content': content},
                  'done': True, 'eval_count': count, 'total_duration': time.time_ns() - generate_started}
        llm.inference_ms = result['total_duration'] / 1e6
        llm.calls = 1
        result['first_token_ms'] = first_token_ms
    elif body.get('pdf_table_enrichment') is not None:
        result = execute_pdf_table_pipeline(llm, body['pdf_table_enrichment'], tag)
    elif body.get('pdf_office_extraction') is not None:
        result = execute_office_pipeline(llm, body['pdf_office_extraction'], tag)
    elif body.get('workspace_staffing') is not None:
        result = execute_staffing_pipeline(llm, body['workspace_staffing'], tag)
    elif body.get('workspace_decomposition') is not None:
        result = execute_workspace_pipeline(llm, body['workspace_decomposition'], tag)
    elif is_proposal_decomposition_prompt(messages):
        result = execute_proposal_pipeline(llm, messages, tag)
    else:
        options = {}
        if body.get('_help_selection') is not None:
            options = {'temperature': 0, 'response_format': {'type': 'json_object', 'schema': {
                'type': 'object', 'properties': {'source_ids': {'type': 'array', 'items': {'type': 'string', 'enum': body['_help_selection']}, 'maxItems': 1}},
                'required': ['source_ids'], 'additionalProperties': False,
            }}}
        response = llm.create_chat_completion(messages=messages, max_tokens=body.get('max_tokens'), **options)
        result = {'model': tag, 'message': {'role': 'assistant', 'content': response['choices'][0]['message']['content']},
                  'done': True, 'eval_count': response.get('usage', {}).get('completion_tokens', 0),
                  'total_duration': time.time_ns() - generate_started}
    result['timings_ms'] = {'model_load': round(load_ms, 1), 'inference': round(llm.inference_ms, 1),
                            'pipeline': round(max(0, (time.perf_counter() - started) * 1000 - load_ms - llm.inference_ms), 1),
                            'total': round((time.perf_counter() - started) * 1000, 1), 'generation_calls': llm.calls}
    if heavy and not body.get('_stream_id'):
        try:
            pipeline = json.loads(result['message']['content']).get('pipeline', {})
            result['pipeline_status'] = {key: pipeline[key] for key in ('deepseek', 'laya', 'pygad') if key in pipeline}
        except (ValueError, TypeError, AttributeError, KeyError):
            pass
    return result
