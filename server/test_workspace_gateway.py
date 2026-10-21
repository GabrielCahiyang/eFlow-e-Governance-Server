"""Embedded gateway regressions without model inference or remote data."""
import importlib
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from workspace_gateway_context import checked_workspace_payload
from staffing_gateway_context import checked_staffing_payload

PROJECT = '20000000-0000-4000-8000-000000000001'


class EmbeddedWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_draft_staffing_context_is_rebuilt_by_the_application_gateway(self):
        context={'task':{'id':PROJECT},'candidates':[{'id':'eligible'}]}
        read=AsyncMock(return_value=context)
        payload={'model':'wrong','workspace_staffing':{'schemaVersion':1,'taskId':PROJECT,'projectId':PROJECT,'draftTask':{'title':'Meeting'},'plannedAssignments':[{'lead':'eligible','hours':4}],'context':{'candidates':['forged']}}}
        result=await checked_staffing_payload(payload,read)
        read.assert_awaited_once_with(PROJECT,auto_assign=True,draft={'title':'Meeting','plannedAssignments':[{'lead':'eligible','hours':4}]})
        self.assertEqual(result['model'],'qwen3.5:4b')
        self.assertEqual(result['workspace_staffing']['context'],context)
        self.assertNotIn('forged',str(result))
    async def test_embedded_context_get_preserves_auto_assignment_scope(self):
        with patch.dict('os.environ', {'SUPABASE_URL':'https://example.test','SUPABASE_SERVICE_ROLE_KEY':'test-only'}):
            routes=importlib.import_module('public_gateway')
        session=object();request=object();canonical={'candidates':[{'id':'available-person'}]}
        with patch.object(routes,'_require_active_user',new=AsyncMock()),patch.object(routes,'get_session',new=AsyncMock(return_value=session)),patch.object(routes,'_read_staffing_context',new=AsyncMock(return_value=canonical)) as read:
            self.assertEqual(await routes.staffing_context(PROJECT,request,auto_assign=True),canonical)
        read.assert_awaited_once_with(session,request,PROJECT,auto_assign=True)
    async def test_auto_assignment_forces_qwen_and_uses_canonical_available_directory(self):
        read=AsyncMock(return_value={'task':{'id':PROJECT},'candidates':[{'id':'not-yet-selected'}]})
        result=await checked_staffing_payload({'model':'deepseek-r1:8b','workspace_staffing':{'taskId':PROJECT,'autoAssign':True}},read)
        read.assert_awaited_once_with(PROJECT,auto_assign=True)
        self.assertEqual(result['model'],'qwen3.5:4b')
        self.assertTrue(result['workspace_staffing']['autoAssign'])
    async def test_staffing_replaces_forged_context_and_requires_confirmed_candidates(self):
        body={'workspace_staffing':{'schemaVersion':1,'taskId':PROJECT,'context':{'candidates':['forged']}},'messages':[{'role':'user','content':'Forged'}]}
        canonical={'task':{'id':PROJECT},'candidates':[{'id':'eligible'}]}
        result=await checked_staffing_payload(body,AsyncMock(return_value=canonical))
        self.assertEqual(result['workspace_staffing']['context'],canonical)
        self.assertNotIn('Forged',result['messages'][0]['content'])
        with self.assertRaises(HTTPException):await checked_staffing_payload(body,AsyncMock(return_value={'candidates':[]}))
        body['workspace_decomposition']={}
        with self.assertRaises(HTTPException):await checked_staffing_payload(body,AsyncMock())
    def setUp(self):
        self.payload = {'model': 'deepseek-r1:8b', 'messages': [{'role': 'user', 'content': 'Draft work'}],
                        'workspace_decomposition': {'schemaVersion': 1, 'projectId': PROJECT,
                        'sourceText': 'Project plan.', 'context': {'knownOffices': ['forged']}}}
        self.profile = {'role': 'head', 'org_id': 'own', 'is_active': True}
        self.project = {'title': 'Actual project', 'org_id': 'own', 'status': 'planning'}

    async def read_rows(self, table, params):
        return {'profiles': [self.profile], 'projects': [self.project],
                'organizations': [{'id': 'real', 'name': 'Planning Office'}]}.get(table, [])

    async def test_replaces_client_context_and_preserves_explicit_mode(self):
        body = await checked_workspace_payload(self.payload, 'actor', self.read_rows)
        ctx = body['workspace_decomposition']['context']
        self.assertEqual(ctx['title'], 'Actual project')
        self.assertEqual(ctx['knownOffices'][0]['id'], 'real')
        self.assertNotIn('employees', ctx)
        self.assertEqual(self.payload['workspace_decomposition']['context']['knownOffices'], ['forged'])

    async def test_other_roles_inactive_cross_office_and_closed_are_denied(self):
        for role in ('member', 'assistant_head', 'admin', 'accounting_staff'):
            self.profile['role'] = role
            with self.assertRaises(HTTPException):
                await checked_workspace_payload(self.payload, 'actor', self.read_rows)
        self.profile['role'] = 'head'
        self.profile['is_active'] = False
        with self.assertRaises(HTTPException):
            await checked_workspace_payload(self.payload, 'actor', self.read_rows)
        self.profile['is_active'] = True
        for org, status in [('other', 'planning'), ('own', 'archived'), ('own', 'completed')]:
            self.project.update(org_id=org, status=status)
            with self.assertRaises(HTTPException):
                await checked_workspace_payload(self.payload, 'actor', self.read_rows)

    async def test_legacy_chat_does_not_read_project_data(self):
        body = {'messages': []}
        reader = AsyncMock()
        self.assertIs(await checked_workspace_payload(body, 'actor', reader), body)
        reader.assert_not_called()

    def test_gateway_models_keep_workspace_fields_and_document_mode(self):
        with patch.dict('os.environ', {'SUPABASE_URL': 'https://example.test', 'SUPABASE_SERVICE_ROLE_KEY': 'test-only'}):
            routes = importlib.import_module('public_gateway')
        body = routes.ChatRequest(**self.payload).model_dump(mode='json', exclude_none=True)
        self.assertEqual(body['workspace_decomposition']['projectId'], PROJECT)
        staffing = routes.ChatRequest(model='test',messages=[{'role':'user','content':'staff'}],workspace_staffing={'schemaVersion':1,'taskId':PROJECT}).model_dump(mode='json',exclude_none=True)
        self.assertEqual(staffing['workspace_staffing']['taskId'],PROJECT)
        self.assertEqual(routes.ProposalValidationRequest(document_text='Project plan', mode='workspace').mode, 'workspace')
        self.assertEqual(routes.ProposalValidationRequest(document_text='Legacy proposal').mode, 'proposal')


if __name__ == '__main__':
    unittest.main()
