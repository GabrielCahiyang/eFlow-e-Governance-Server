"""Both gateways use the application's canonical, authenticated staffing context."""
from copy import deepcopy
from fastapi import HTTPException
async def checked_staffing_payload(payload, read_context):
    if payload.get('workspace_staffing') is None: return payload
    if payload.get('workspace_decomposition') is not None:
        raise HTTPException(422, 'Choose one AI operation.')
    auto_assign = payload['workspace_staffing'].get('autoAssign') is True
    if payload['workspace_staffing'].get('projectId'):
        auto_assign = True
        draft = {**(payload['workspace_staffing'].get('draftTask') or {}), 'plannedAssignments': payload['workspace_staffing'].get('plannedAssignments', [])}
        context = await read_context(payload['workspace_staffing']['projectId'], auto_assign=True, draft=draft)
    else:
        context = await read_context(payload['workspace_staffing']['taskId'], auto_assign=True) if auto_assign else await read_context(payload['workspace_staffing']['taskId'])
    if not context.get('candidates'):
        raise HTTPException(409, 'Ask eligible Office members to confirm their professional profiles first.')
    body = deepcopy(payload)
    body['workspace_staffing'] = {'schemaVersion':1,'taskId':payload['workspace_staffing']['taskId'],'context':context}
    if auto_assign:
        body['model'] = 'qwen3.5:4b'
        body['workspace_staffing']['autoAssign'] = True
    body['messages'] = [{'role':'user','content':'Recommend eligible Office staff from confirmed professional context.'}]
    return body
