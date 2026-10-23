"""LAYA reviews Qwen's grounded shortlist; never grants access or writes people."""
from laya_service import ParsedEmployee, enrich_task_with_laya
from job_queue import report_job_progress
from service_monitor import run_origin


def review_auto_assignment(result, context, model_tag):
    report_job_progress('laya_review', 'LAYA is checking task routing, team fit and current workload.')
    candidates = {candidate['id']: candidate for candidate in context['candidates']}
    grounded = {row['userId']: row for row in result['recommendations']}
    employees = []
    for person_id in grounded:
        candidate = candidates[person_id]
        # Only confirmed professional entries; workload-only fallback text must
        # never become an asserted skill or invented utilization percentage.
        facts = [str(value) for key in ('skills', 'training', 'education', 'experience', 'specializations', 'certifications')
                 for value in candidate.get(key, [])]
        summary = candidate.get('experience_summary') or ''
        if summary and not summary.startswith('Professional details not confirmed.'):
            facts.append(summary)
        employees.append(ParsedEmployee(id=person_id, name=candidate.get('name', person_id),
            skills=facts, strengths=facts, remaining_hours=candidate['remainingHours'],
            unknown_effort_tasks=candidate['unknownEffortTasks'], active_tasks=candidate['activeTasks']))
    task = context['task']
    origin = run_origin.set('staffing')
    try:
        reviewed = enrich_task_with_laya({
            'title': task.get('title', ''), 'description': task.get('description', ''),
            'requiredSkills': task.get('skills', []),
        }, context_title=task.get('title', ''), employees=employees)
    finally:
        run_origin.reset(origin)
    # This action promises the model-backed LAYA layer. Its legacy heuristic
    # fallback is useful elsewhere, but must not silently save this team's work.
    if reviewed.get('decisionLayer', {}).get('engine') != 'laya':
        raise ValueError('LAYA model review is unavailable. No team was saved. Check the LAYA service and retry.')
    selected = reviewed.get('recommendedEmployeeIds')
    if not isinstance(selected, list) or not selected or len(selected) != len(set(selected)) or any(person not in grounded for person in selected):
        raise ValueError('LAYA did not return a valid team from the eligible shortlist. No team was saved. Retry.')
    result['recommendations'] = [grounded[person] for person in selected]
    result['pipeline'] = {'stages': [model_tag, 'laya', 'validation'], 'laya': 'completed', 'layaEngine': 'laya', 'validation': 'completed'}
    result['notice'] = 'Qwen recommendations reviewed by LAYA and validated against eligible people and supplied profile facts.'
    return result
