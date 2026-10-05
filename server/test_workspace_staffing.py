import json, unittest
from unittest.mock import Mock, patch
from workspace_staffing import normalize_recommendations, execute_staffing_pipeline
CONTEXT={'task':{'id':'task','title':'Survey a site'},'candidates':[{'id':'member','skills':['Surveying'],'training':['Safety'], 'activeTasks':3,'remainingHours':8,'unknownEffortTasks':1}]}
class StaffingTests(unittest.TestCase):
 def test_only_confirmed_candidate_facts_and_authoritative_workload_survive(self):
  out=normalize_recommendations({'recommendations':[{'userId':'foreign','evidence':['Surveying']},{'userId':'member','evidence':['Surveying','Invented experience'],'remainingHours':0},{'userId':'member','evidence':['Safety']}]},CONTEXT)
  self.assertEqual(out['recommendations'],[{'userId':'member','evidence':['Surveying'],'activeTasks':3,'remainingHours':8,'unknownEffortTasks':1}])
 def test_unsupported_evidence_is_rejected(self):
  for evidence in [['Unknown'], 'Surveying',None]:
   with self.assertRaises(ValueError):normalize_recommendations({'recommendations':[{'userId':'member','evidence':evidence}]},CONTEXT)
 def test_existing_model_pipeline_returns_advisory_json_without_assignment(self):
  llm=Mock();llm.create_chat_completion.return_value={'choices':[{'message':{'content':json.dumps({'recommendations':[{'userId':'member','evidence':['Surveying']}]})}}]}
  with patch('workspace_staffing.report_job_progress'):out=execute_staffing_pipeline(llm,{'schemaVersion':1,'context':CONTEXT},'test-model')
  self.assertTrue(out['done']);self.assertEqual(json.loads(out['message']['content'])['source'],'ai');self.assertIn('schema',llm.create_chat_completion.call_args.kwargs['response_format'])
  variant=llm.create_chat_completion.call_args.kwargs['response_format']['schema']['properties']['recommendations']['items']['oneOf'][0]
  self.assertEqual(variant['properties']['userId'],{'const':'member'})
  self.assertEqual(variant['properties']['evidence']['items']['enum'],['Surveying','Safety'])
if __name__=='__main__':unittest.main()
