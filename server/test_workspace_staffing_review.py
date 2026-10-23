import copy
import json
import unittest
from unittest.mock import Mock, patch
from workspace_staffing import execute_staffing_pipeline
from workspace_staffing_review import review_auto_assignment
from laya_service import ParsedEmployee, match_personnel
from service_monitor import run_origin

CONTEXT = {'task': {'id': 'task', 'title': 'Survey a site', 'skills': ['Surveying']}, 'candidates': [
    {'id': 'one', 'name': 'One', 'skills': ['Surveying'], 'activeTasks': 3, 'remainingHours': 16, 'unknownEffortTasks': 1},
    {'id': 'two', 'name': 'Two', 'skills': ['Surveying'], 'activeTasks': 1, 'remainingHours': 2, 'unknownEffortTasks': 0},
]}
RESULT = {'recommendations': [{'userId': 'one', 'evidence': ['Surveying']}, {'userId': 'two', 'evidence': ['Surveying']}]}

class StaffingReviewTests(unittest.TestCase):
    @patch('workspace_staffing_review.enrich_task_with_laya')
    def test_laya_changes_the_team_and_retains_only_grounded_evidence(self, enrich):
        def decision(*args, **kwargs):
            self.assertEqual(run_origin.get(), 'staffing')
            return {'decisionLayer': {'engine': 'laya'}, 'recommendedEmployeeIds': ['two']}
        enrich.side_effect = decision
        result = review_auto_assignment(copy.deepcopy(RESULT), CONTEXT, 'qwen3.5:4b')
        self.assertEqual(run_origin.get(), 'standalone')
        self.assertEqual(result['recommendations'], [RESULT['recommendations'][1]])
        self.assertEqual(result['pipeline']['laya'], 'completed')
        people = enrich.call_args.kwargs['employees']
        self.assertEqual(people[0].remaining_hours, 16)
        self.assertEqual(people[0].unknown_effort_tasks, 1)
        self.assertEqual(enrich.call_args.args[0]['requiredSkills'], ['Surveying'])

    @patch('workspace_staffing_review.enrich_task_with_laya')
    def test_no_silent_fallback_or_ineligible_selection(self, enrich):
        for layer, selected in [('heuristic_fallback', ['one']), ('laya', ['foreign']), ('laya', []), ('laya', ['one', 'one'])]:
            enrich.return_value = {'decisionLayer': {'engine': layer}, 'recommendedEmployeeIds': selected}
            with self.assertRaisesRegex(ValueError, 'No team was saved'):
                review_auto_assignment(copy.deepcopy(RESULT), CONTEXT, 'qwen3.5:4b')

    @patch('workspace_staffing_review.enrich_task_with_laya')
    def test_confirmed_summaries_are_used_but_workload_fallback_is_not_a_skill(self, enrich):
        context = copy.deepcopy(CONTEXT)
        context['candidates'][0]['experience_summary'] = 'Experienced in site survey planning.'
        context['candidates'][1]['skills'] = []
        fallback = 'Professional details not confirmed. Current active tasks: 1; known remaining hours: 2; tasks with unknown effort: 0.'
        context['candidates'][1]['experience_summary'] = fallback
        grounded = copy.deepcopy(RESULT)
        grounded['recommendations'][1]['evidence'] = [fallback]
        enrich.return_value = {'decisionLayer': {'engine': 'laya'}, 'recommendedEmployeeIds': ['one']}
        review_auto_assignment(grounded, context, 'qwen3.5:4b')
        people = enrich.call_args.kwargs['employees']
        self.assertIn('Experienced in site survey planning.', people[0].skills)
        self.assertEqual(people[1].skills, [])

    def test_hours_and_unknown_effort_affect_laya_staff_selection(self):
        people = [ParsedEmployee(id=c['id'], name=c['name'], skills=c['skills'], remaining_hours=c['remainingHours'],
            active_tasks=c['activeTasks'], unknown_effort_tasks=c['unknownEffortTasks']) for c in CONTEXT['candidates']]
        selected, _ = match_personnel(['Surveying'], 'Survey a site', '', people)
        self.assertEqual(selected, ['two'])

    @patch('workspace_staffing_review.enrich_task_with_laya')
    def test_full_small_assignment_pipeline_requires_real_laya(self, enrich):
        enrich.return_value = {'decisionLayer': {'engine': 'laya'}, 'recommendedEmployeeIds': ['two']}
        model = Mock()
        model.create_chat_completion.return_value = {'choices': [{'message': {'content': json.dumps(RESULT)}}]}
        response = execute_staffing_pipeline(model, {'schemaVersion': 1, 'context': CONTEXT, 'autoAssign': True}, 'qwen3.5:4b')
        self.assertEqual(json.loads(response['message']['content'])['recommendations'][0]['userId'], 'two')
        enrich.assert_called_once()
        model.create_chat_completion.assert_called_once()
        enrich.side_effect = RuntimeError('LAYA stopped')
        with self.assertRaisesRegex(RuntimeError, 'LAYA stopped'):
            execute_staffing_pipeline(model, {'schemaVersion': 1, 'context': CONTEXT, 'autoAssign': True}, 'qwen3.5:4b')

if __name__ == '__main__':
    unittest.main()
