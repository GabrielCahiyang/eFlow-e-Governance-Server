"""Only caller-JWT reads: project/task RLS is authoritative for every turn."""
import os
from datetime import datetime, timezone, timedelta
from uuid import UUID
import aiohttp
from fastapi import HTTPException
from http_client import get_session

class Caller:
    def __init__(self, token):
        self.token = token
        self.url = (os.getenv('VITE_SUPABASE_URL') or os.getenv('SUPABASE_URL', '')).rstrip('/')
        self.key = os.getenv('VITE_SUPABASE_ANON_KEY', '')
        if not self.key:
            raise HTTPException(503, 'Project context is not configured on the AI server.')
        if not token:
            raise HTTPException(401, 'A current eFlow session is required.')
        self.profile = None

    async def read(self, path, params=None):
        session = await get_session()
        try:
            async with session.get(self.url + path, params=params, headers={'apikey': self.key, 'Authorization': 'Bearer ' + self.token}, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status in (401, 403):
                    raise HTTPException(response.status, 'Your eFlow access could not be verified. Sign in again.')
                if response.status != 200:
                    raise HTTPException(503, 'The visible eFlow records could not be loaded.')
                return await response.json()
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise HTTPException(503, 'The eFlow connection is unavailable.') from exc

    async def verify(self, expected_owner):
        identity = await self.read('/auth/v1/user')
        if not identity.get('id') or identity['id'] != expected_owner:
            raise HTTPException(401, 'A current eFlow session is required.')
        rows = await self.read('/rest/v1/profiles', {'select': 'id,role,is_active', 'id': 'eq.' + identity['id']})
        if not rows or rows[0].get('is_active') is not True:
            raise HTTPException(403, 'An active eFlow account is required.')
        self.profile = rows[0]
        return self

    async def projects(self):
        if self.profile['role'] == 'admin':
            return []
        return await self.read('/rest/v1/projects', {'select': 'id,title,status', 'order': 'updated_at.desc', 'limit': '100'})

    async def project_facts(self, project_id):
        project_id = str(UUID(project_id))
        if self.profile['role'] == 'admin':
            raise HTTPException(403, 'Use an operational account to inspect project work.')
        rows = await self.read('/rest/v1/projects', {'select': 'id,title,status,target_date', 'id': 'eq.' + project_id})
        if not rows:
            raise HTTPException(404, 'This project is unavailable to your account.')
        project = rows[0]
        tasks = []
        # Paginate rather than claiming that a truncated first page is complete.
        for offset in range(0, 2000, 200):
            batch = await self.read('/rest/v1/tasks', {'select': 'id,title,status,due_date,assigned_to,recommendation_lead_id,dependency_ids,reviewer_id,review_route_mode,updated_at', 'linked_project_id': 'eq.' + project_id, 'deleted_at': 'is.null', 'archived_at': 'is.null', 'order': 'id', 'limit': '200', 'offset': str(offset)})
            tasks.extend(batch)
            if len(batch) < 200:
                break
        else:
            raise HTTPException(409, 'This project is too large for a complete summary. Use its task table.')
        facts = [{'id': 'project:status', 'title': project['title'], 'text': f"Project {project['title']} is {project['status']}. These are the records visible to your account; other work may be hidden.", 'kind': 'project', 'projectId': project_id}]
        closed = {'completed', 'cancelled'}
        open_tasks = [task for task in tasks if task['status'] not in closed]
        facts.append({'id': 'project:counts', 'title': 'Visible task status', 'text': f"You can see {len(tasks)} unarchived work items in this project; {len(open_tasks)} are not completed or cancelled.", 'kind': 'project', 'projectId': project_id})
        by_id = {task['id']: task for task in tasks}
        now = datetime.now(timezone.utc)
        def overdue(value):
            if not value:
                return False
            try:
                if len(value) == 10:
                    return value < now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
                due = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone(timedelta(hours=8)))
                return due < now
            except ValueError:
                return False
        for task in sorted(open_tasks, key=lambda item: (not overdue(item.get('due_date')), item.get('due_date') or '9999')):
            reasons = []
            if not (task.get('assigned_to') or task.get('recommendation_lead_id')):
                reasons.append('no assigned lead is recorded')
            if overdue(task.get('due_date')):
                reasons.append('its recorded due date was ' + task['due_date'][:10])
            if task['status'] == 'for_review':
                reasons.append('it is awaiting review, rather than approved as complete')
                if task.get('review_route_mode') == 'explicit' and task.get('reviewer_id'):
                    reviewer = await self.read('/rest/v1/profiles', {'select': 'full_name', 'id': 'eq.' + task['reviewer_id']})
                    if reviewer:
                        reasons.append('the recorded reviewer is ' + reviewer[0]['full_name'])
                else:
                    reasons.append('check task details for its current authorized review route')
            if task['status'] == 'changes_requested':
                reasons.append('changes have been requested')
            dependencies = [by_id[key]['title'] for key in (task.get('dependency_ids') or []) if key in by_id and by_id[key]['status'] != 'completed']
            if dependencies:
                reasons.append('visible prerequisites are incomplete: ' + ', '.join(dependencies[:3]))
            if not reasons:
                continue
            owner = task.get('assigned_to') or task.get('recommendation_lead_id')
            owner_label = 'No lead assigned'
            if owner:
                profiles = await self.read('/rest/v1/profiles', {'select': 'full_name', 'id': 'eq.' + owner})
                owner_label = profiles[0]['full_name'] if profiles else 'Lead name unavailable to your account'
            facts.append({'id': 'task:' + task['id'], 'title': task['title'], 'text': f"{task['title']}: {'; '.join(reasons)}. Recorded lead: {owner_label}. This identifies a follow-up, not proof of personal fault.", 'kind': 'task', 'projectId': project_id, 'taskId': task['id'], 'version': task.get('updated_at')})
            if len(facts) >= 10:
                break
        return facts

    async def recheck(self, facts):
        for project in {item['projectId'] for item in facts if item.get('projectId')}:
            if not await self.read('/rest/v1/projects', {'select': 'id', 'id': 'eq.' + project}):
                raise HTTPException(403, 'Your access to this project has changed.')
        for fact in facts:
            if fact.get('taskId'):
                rows = await self.read('/rest/v1/tasks', {'select': 'id,updated_at', 'id': 'eq.' + fact['taskId'], 'deleted_at': 'is.null', 'archived_at': 'is.null'})
                if not rows:
                    raise HTTPException(403, 'Your access to this task has changed.')
                if fact.get('version') and rows[0].get('updated_at') != fact['version']:
                    raise HTTPException(409, 'The task changed while preparing this answer. Ask again for its current state.')
