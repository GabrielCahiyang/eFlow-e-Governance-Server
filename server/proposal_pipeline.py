"""Server-Side Proposal Decomposition Pipeline (R1 WBS Extraction + Laya Decision Layer).

Coordinates:
1. Parsing incoming section prompts from EflowWeb without requiring client changes.
2. Prompting DeepSeek R1 8B purely for Work Breakdown Structure (tasks, skills, subtasks).
3. Piping R1's structured output into the Laya Decision Engine (routing, clearance, staffing, priority).
4. Returning the exact JSON structure expected by EflowWeb's DraftCockpit.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from laya_service import (
    enrich_task_with_laya,
    parse_employees_block,
)

logger = logging.getLogger("eflow.proposal_pipeline")


def is_proposal_decomposition_prompt(messages: list[dict[str, Any]]) -> bool:
    """Detect if the incoming chat completion is a proposal decomposition task."""
    if not messages:
        return False
    last_content = str(messages[-1].get("content") or "")
    markers = [
        "Break down ONE section of a government project proposal into actionable tasks.",
        "Section title:",
        "Available team:",
        "Produce 1-4 tasks for this section only",
    ]
    matches = sum(1 for m in markers if m in last_content)
    return matches >= 2


def parse_section_prompt(prompt_text: str) -> dict[str, Any]:
    """Extract section title, details, schedule, employee block, and budget block."""
    title_match = re.search(r'Section title:\s*"([^"]+)"', prompt_text, re.IGNORECASE)
    section_title = title_match.group(1).strip() if title_match else "General Activity"

    details_match = re.search(r'Details:\s*"([^"]+)"', prompt_text, re.IGNORECASE)
    section_details = details_match.group(1).strip() if details_match else ""

    sched_match = re.search(r'Schedule:\s*"([^"]+)"', prompt_text, re.IGNORECASE)
    schedule = sched_match.group(1).strip() if sched_match else "Month 1"

    # Extract available team block
    team_match = re.search(
        r"Available team:\s*([\s\S]*?)(?=Assignment rules:|Funding rules:|Proposal budget schedule:|Respond with JSON|$)",
        prompt_text,
        re.IGNORECASE,
    )
    team_text = team_match.group(1).strip() if team_match else ""
    parsed_employees = parse_employees_block(team_text)

    # Extract budget schedule block
    budget_match = re.search(
        r"Proposal budget schedule:\s*([\s\S]*?)(?=Respond with JSON|Produce 1-4 tasks|$)",
        prompt_text,
        re.IGNORECASE,
    )
    budget_text = budget_match.group(1).strip() if budget_match else ""

    return {
        "section_title": section_title,
        "section_details": section_details,
        "schedule": schedule,
        "team_text": team_text,
        "employees": parsed_employees,
        "budget_text": budget_text,
    }


def build_r1_wbs_prompt(
    section_title: str,
    section_details: str,
    schedule: str,
    budget_text: str = "",
) -> str:
    """Build a streamlined prompt for DeepSeek R1 8B focusing purely on WBS."""
    budget_ref = (
        f"Proposal budget schedule:\n{budget_text}"
        if budget_text and "No reliable budget schedule" not in budget_text
        else "No specific budget schedule was provided."
    )

    return f"""Break down ONE section of a local government project proposal into actionable tasks.

Section title: "{section_title}"
Details: "{section_details}"
Schedule: "{schedule}"

{budget_ref}

WBS extraction rules:
- Produce 1-4 concrete, actionable tasks for this section only.
- For each task, extract:
  * "title": Clear operational task title (maximum 100 characters)
  * "description": Concrete scope and expected deliverables
  * "estimatedDuration": Realistic timeframe (e.g. "2 weeks", "5 days")
  * "requiredSkills": Array of 2-4 specific technical/operational skills
  * "subtasks": Array of 3-5 sequential checklist steps to complete the task
- If a line from the budget schedule clearly belongs to this task, set budgetDecision to "funded" and include "budgetLines". Otherwise set budgetDecision to "missing".
- Do NOT assign employee IDs.

Respond with JSON only, no preamble, no markdown fences:
{{
  "tasks": [
    {{
      "title": "Task title",
      "description": "Task deliverables and requirements",
      "estimatedDuration": "2 weeks",
      "requiredSkills": ["skill1", "skill2"],
      "budgetDecision": "missing",
      "budgetNoCostReason": "",
      "budgetLines": [],
      "subtasks": ["step 1", "step 2", "step 3"]
    }}
  ]
}}"""


def extract_json_payload(raw_content: str) -> dict[str, Any] | None:
    """Extract and parse JSON object from LLM response, stripping think tags."""
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw_content, flags=re.IGNORECASE).strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


_lead_history: dict[str, int] = {}
_last_decomposition_time = 0.0


def get_current_lead_history() -> dict[str, int]:
    """Maintain cumulative leadership assignments across sequential parts."""
    global _lead_history, _last_decomposition_time
    now = time.time()
    # Reset if a new proposal import is started (> 5 minutes idle between parts)
    if now - _last_decomposition_time > 300:
        _lead_history = {}
    _last_decomposition_time = now
    return _lead_history


def execute_proposal_pipeline(
    llm: Any,
    messages: list[dict[str, Any]],
    model_tag: str,
) -> dict[str, Any]:
    """Execute the full 2-Tier Pipeline: R1 WBS extraction -> Laya Decision Layer."""
    start_time = time.time_ns()
    user_prompt = str(messages[-1].get("content") or "")
    parsed_prompt = parse_section_prompt(user_prompt)

    section_title = parsed_prompt["section_title"]
    section_details = parsed_prompt["section_details"]
    schedule = parsed_prompt["schedule"]
    employees = parsed_prompt["employees"]
    budget_text = parsed_prompt["budget_text"]

    logger.info(
        f"[Proposal Pipeline] Decomposing '{section_title}' with {len(employees)} available team members"
    )

    # ─── TIER 1: DeepSeek R1 8B (Work Breakdown Structure) ─────────────
    r1_prompt = build_r1_wbs_prompt(section_title, section_details, schedule, budget_text)
    r1_messages = [{"role": "user", "content": r1_prompt}]

    eval_count = 0
    raw_tasks: list[dict[str, Any]] = []

    try:
        r1_result = llm.create_chat_completion(messages=r1_messages)
        content = (
            r1_result["choices"][0]["message"]["content"]
            if r1_result.get("choices")
            else ""
        )
        eval_count = r1_result.get("usage", {}).get("completion_tokens", 0)
        parsed_json = extract_json_payload(content)
        if parsed_json and isinstance(parsed_json.get("tasks"), list):
            raw_tasks = [t for t in parsed_json["tasks"] if isinstance(t, dict)]
    except Exception as exc:
        logger.warning(f"[Proposal Pipeline] DeepSeek R1 execution error: {exc}")

    # Fallback task if R1 failed or returned empty array
    if not raw_tasks:
        logger.info(f"[Proposal Pipeline] Using structured fallback for '{section_title}'")
        raw_tasks = [
            {
                "title": f"Execute {section_title}",
                "description": section_details or f"Deliver activities for {section_title}.",
                "estimatedDuration": "2 weeks",
                "requiredSkills": ["Project Management", "Coordination"],
                "subtasks": ["Prepare activity plan", "Coordinate stakeholders", "Deliver milestones"],
            }
        ]

    # ─── TIER 2: Laya Decision Layer (System-1 Bounded Decisions) ───────
    lead_history = get_current_lead_history()
    enriched_tasks: list[dict[str, Any]] = []
    for task in raw_tasks:
        enriched = enrich_task_with_laya(
            task,
            context_title=section_title,
            employees=employees,
            budget_schedule=budget_text,
            lead_history=lead_history,
        )
        enriched_tasks.append(enriched)

    final_payload = {"tasks": enriched_tasks}
    response_content = json.dumps(final_payload, indent=2)

    total_duration = time.time_ns() - start_time
    logger.info(
        f"[Proposal Pipeline] Completed {len(enriched_tasks)} tasks for '{section_title}' "
        f"in {total_duration / 1_000_000:.0f}ms (R1 + Laya)"
    )

    return {
        "model": model_tag,
        "message": {"role": "assistant", "content": response_content},
        "done": True,
        "total_duration": total_duration,
        "eval_count": eval_count,
    }
