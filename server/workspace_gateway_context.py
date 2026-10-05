"""Read-only project authority/context boundary for the embedded AI gateway."""
import asyncio
from copy import deepcopy
from fastapi import HTTPException


async def checked_workspace_payload(payload, user_id, read_rows):
    request = payload.get('workspace_decomposition')
    if not request:
        return payload
    profiles = await read_rows('profiles', {'select': 'id,role,org_id,is_active', 'id': f'eq.{user_id}'})
    profile = profiles[0] if profiles else {}
    if (profile.get('is_active') is not True
            or profile.get('role') not in ('head', 'dept_head', 'department_head')
            or not profile.get('org_id')):
        raise HTTPException(status_code=403, detail='Only an active Office Head can decompose project work.')
    project_id = request['projectId']
    projects = await read_rows('projects', {
        'select': 'id,org_id,title,description,start_date,target_date,status', 'id': f'eq.{project_id}',
    })
    project = projects[0] if projects else {}
    if (not project or project.get('org_id') != profile['org_id']
            or project.get('status') in ('completed', 'archived')):
        raise HTTPException(status_code=403, detail='Choose an open project belonging to your Office.')
    groups, tasks, offices, receipts = await asyncio.gather(
        read_rows('project_groups', {'select': 'id,title', 'project_id': f'eq.{project_id}', 'order': 'position.asc'}),
        read_rows('tasks', {'select': 'id,title,description,group_id', 'linked_project_id': f'eq.{project_id}', 'deleted_at': 'is.null', 'limit': '300'}),
        read_rows('organizations', {'select': 'id,name,slug'}),
        read_rows('project_import_batches', {'select': 'review', 'project_id': f'eq.{project_id}', 'order': 'created_at.desc', 'limit': '5'}),
    )
    responsibilities = []
    for receipt in receipts:
        review = receipt.get('review')
        proposals = review.get('offices') if isinstance(review, dict) else None
        if isinstance(proposals, list):
            responsibilities.extend(office for office in proposals if isinstance(office, dict))
    body = deepcopy(payload)
    body['workspace_decomposition']['context'] = {
        'title': project['title'], 'description': project.get('description', ''),
        'startDate': project.get('start_date'), 'targetDate': project.get('target_date'),
        'groups': groups, 'existingTasks': tasks, 'knownOffices': offices,
        'officeResponsibilities': responsibilities,
    }
    return body
