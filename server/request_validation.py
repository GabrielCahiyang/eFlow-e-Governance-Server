"""Lightweight admission checks shared by API and inference process."""
import json
import os


def validate_workspace_request(request):
    if not isinstance(request, dict) or request.get("schemaVersion") != 1:
        raise ValueError("Unsupported workspace decomposition version.")
    source = request.get("sourceText", "")
    if not isinstance(source, str) or not source.strip() or len(source) > 500000:
        raise ValueError("Provide source text of at most 500000 characters.")
    if not isinstance(request.get("context", {}), dict):
        raise ValueError("Workspace context must be an object.")


def validate_staffing_request(request):
    if not isinstance(request, dict) or request.get('schemaVersion') != 1:
        raise ValueError('Unsupported staffing version.')
    context = request.get('context') or {}
    if not isinstance(context, dict):
        raise ValueError('Staffing context must be an object.')
    candidates = context.get('candidates')
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 200:
        raise ValueError('Staffing requires between 1 and 200 confirmed eligible profiles.')
    if not isinstance(context.get('task'), dict):
        raise ValueError('Task context is required.')
    if len(json.dumps(context, ensure_ascii=False)) > 100000:
        raise ValueError('Confirmed profile context is too large. Shorten professional summaries before retrying.')



def validate_chat_request(body):
    if not isinstance(body, dict):
        raise ValueError("AI request must be an object")
    if 'model' in body and not isinstance(body['model'], str):
        raise ValueError("model must be a string")
    if 'stream' in body and not isinstance(body['stream'], bool):
        raise ValueError("stream must be a boolean")
    request_id = body.get('request_id')
    if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 128):
        raise ValueError("request_id must be a string of at most 128 characters")
    if any(str(key).startswith('_') for key in body):
        raise ValueError("Internal request fields are reserved")
    messages = body.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= 200:
        raise ValueError("Provide between 1 and 200 chat messages")
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("role"), str) or message.get("role") not in {"system", "user", "assistant"} or not isinstance(message.get("content"), str):
            raise ValueError("Invalid chat message")
    if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > int(os.getenv("EFLOW_MAX_REQUEST_BYTES", "1500000")):
        raise ValueError("AI request is too large. Split the document or shorten the conversation.")
    maximum = body.get("max_tokens")
    if maximum is not None and (isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 4096):
        raise ValueError("max_tokens must be between 1 and 4096")
    modes = ('workspace_decomposition', 'workspace_staffing', 'pdf_table_enrichment')
    if sum(body.get(mode) is not None for mode in modes) > 1:
        raise ValueError('Submit one structured AI operation per job')
    if body.get("stream") is True and any(body.get(mode) is not None for mode in modes):
        raise ValueError("Structured workspace jobs require stream=false")
    if body.get("workspace_decomposition") is not None and body.get("workspace_staffing") is not None:
        raise ValueError("Submit decomposition and staffing as separate jobs")
    if body.get("workspace_decomposition") is not None:
        validate_workspace_request(body["workspace_decomposition"])
    if body.get("workspace_staffing") is not None:
        validate_staffing_request(body["workspace_staffing"])
    if body.get('pdf_table_enrichment') is not None:
        from pdf_table_enrichment import validate_pdf_table_request
        validate_pdf_table_request(body['pdf_table_enrichment'])


