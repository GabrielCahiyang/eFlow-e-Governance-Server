"""Laya Decision Layer (System-1 Bounded Decision Service).

Receives structured WBS tasks extracted by DeepSeek R1 8B and makes fast,
bounded municipal administrative decisions:
1. Municipal Workflow Routing (IT vs LEDIPO vs CPDO vs BPLO vs GSO vs Budget)
2. Governance & Statutory Clearance (BAC resolution, Petty Cash / Cash Advance, standard)
3. Priority & Urgency Classification (High / Med / Low with confidence)
4. Role & Personnel Matching (Skill vectors, manager notes, and workload signals)
5. Audit Reasoning Generation for eFlow compliance
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("eflow.laya")

_laya_router = None
_laya_router_init_tried = False


def get_laya_router() -> Any | None:
    """Lazily load the Laya Router from NandhaKishorM/laya."""
    global _laya_router, _laya_router_init_tried
    if _laya_router_init_tried:
        return _laya_router
    _laya_router_init_tried = True
    try:
        from laya import Router
        _laya_router = Router(standalone_repos=True, default="typed-decisions")
        logger.info("[Laya] Router successfully initialized with convaiinnovations/laya-typed-decisions")
    except Exception as exc:
        logger.warning(f"[Laya] Could not initialize laya.Router: {exc}. Using fallback heuristic engine.")
        _laya_router = None
    return _laya_router


@dataclass
class ParsedEmployee:
    id: str
    name: str
    role: str = ""
    workload: int = 0
    skills: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


# ─── Municipal Department & Workflow Definitions ────────────────────────

MUNICIPAL_DOMAINS = [
    {
        "department": "Information Technology & Digital Services",
        "workflow": "it_technical_deployment",
        "keywords": [
            "server", "network", "software", "database", "vlan", "infrastructure",
            "hardware", "digital", "portal", "cloud", "backup", "cybersecurity",
            "configure", "migration", "install", "telecom", "it ", "firewall",
            "systems", "developer", "coding", "interface", "api",
        ],
        "skills": ["Networking", "Database", "IT Support", "Systems Admin", "Security", "DevOps"],
    },
    {
        "department": "General Services Office / Procurement",
        "workflow": "procurement_standard",
        "keywords": [
            "procure", "canvass", "purchase", "bidding", "supply", "bids and awards",
            "bac", "vendor", "supplier", "rfq", "purchase order", "delivery",
            "procurement", "pr", "equipment", "asset", "inventory",
        ],
        "skills": ["Procurement", "Supply Management", "Logistics", "Contract Management"],
    },
    {
        "department": "City Planning & Development Office (CPDO)",
        "workflow": "planning_and_spatial_analysis",
        "keywords": [
            "master plan", "zoning", "land use", "demographic", "feasibility",
            "spatial", "urban planning", "framework", "inception", "survey", "gis",
            "mapping", "baseline", "socio-economic", "situation analysis",
        ],
        "skills": ["Planning", "Urban Design", "GIS", "Research", "Data Analysis"],
    },
    {
        "department": "Local Economic Development & Investment (LEDIPO)",
        "workflow": "economic_promotion",
        "keywords": [
            "investment", "trade", "fair", "msme", "business incentive", "tourism",
            "market study", "livelihood", "economic", "promotional", "cooperative",
            "diagnostic", "benchmarking", "roadmap", "investor", "local business",
        ],
        "skills": ["Economic Research", "Marketing", "Community Relations", "Event Management"],
    },
    {
        "department": "Business Permits & Licensing Office (BPLO)",
        "workflow": "permits_and_compliance",
        "keywords": [
            "permit", "license", "inspection", "compliance", "ordinance",
            "business registration", "enforcement", "taxation", "revenue",
            "clearance", "safety inspection",
        ],
        "skills": ["Inspection", "Legal Compliance", "Auditing", "Permitting"],
    },
    {
        "department": "City Budget & Accounting Office",
        "workflow": "financial_clearance",
        "keywords": [
            "voucher", "liquidation", "payroll", "budget", "allotment",
            "cash flow", "disbursement", "audit", "coa", "accounting", "petty cash",
            "fund", "appropriation", "financial report",
        ],
        "skills": ["Accounting", "Financial Analysis", "Auditing", "Budgeting"],
    },
    {
        "department": "Human Resource & Administration",
        "workflow": "hr_and_capacity_building",
        "keywords": [
            "training", "workshop", "personnel", "seminar", "capacity building",
            "onboarding", "staff", "facilitator", "human resource", "hr",
            "skills training", "coaching",
        ],
        "skills": ["Training", "HR", "Facilitation", "Administration", "Instruction"],
    },
]


def parse_employees_block(text: str) -> list[ParsedEmployee]:
    """Parse the compact employee roster text block sent in the prompt."""
    if not text or not text.strip():
        return []

    employees: list[ParsedEmployee] = []
    # Blocks start with "- ID: <id> | Name: <name> | Role: <role>"
    entry_pattern = re.compile(
        r"-\s*ID:\s*([^|\n]+)\s*\|\s*Name:\s*([^|\n]+)(?:\|\s*Role:\s*([^\n]+))?",
        re.IGNORECASE,
    )
    matches = list(entry_pattern.finditer(text))

    for idx, match in enumerate(matches):
        emp_id = match.group(1).strip()
        emp_name = match.group(2).strip()
        emp_role = (match.group(3) or "").strip()

        start_pos = match.end()
        end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        chunk = text[start_pos:end_pos]

        # Extract workload
        workload = 0
        wl_match = re.search(r"Workload:\s*(\d+)%", chunk, re.IGNORECASE)
        if wl_match:
            try:
                workload = int(wl_match.group(1))
            except ValueError:
                pass

        # Extract skills
        skills: list[str] = []
        skills_match = re.search(r"Skills:\s*([^\n]+)", chunk, re.IGNORECASE)
        if skills_match:
            skills = [s.strip() for s in skills_match.group(1).split(",") if s.strip()]

        # Extract strengths
        strengths: list[str] = []
        str_match = re.search(r"Strengths:\s*([^\n]+)", chunk, re.IGNORECASE)
        if str_match and "No manager strengths" not in str_match.group(1):
            strengths = [s.strip() for s in str_match.group(1).split(",") if s.strip()]

        # Extract weaknesses
        weaknesses: list[str] = []
        weak_match = re.search(r"Weakness/risk constraints:\s*([^\n]+)", chunk, re.IGNORECASE)
        if weak_match and "None recorded" not in weak_match.group(1):
            weaknesses = [w.strip() for w in weak_match.group(1).split(",") if w.strip()]

        # Extract tags
        tags: list[str] = []
        tags_match = re.search(r"Tags:\s*([^\n]+)", chunk, re.IGNORECASE)
        if tags_match and "None" not in tags_match.group(1):
            tags = [t.strip() for t in tags_match.group(1).split(",") if t.strip()]

        employees.append(
            ParsedEmployee(
                id=emp_id,
                name=emp_name,
                role=emp_role,
                workload=workload,
                skills=skills,
                strengths=strengths,
                weaknesses=weaknesses,
                tags=tags,
            )
        )

    return employees


LAYA_CHOICE_MAP = {
    "it": ("Information Technology & Digital Services", "it_technical_deployment"),
    "procurement": ("General Services Office / Procurement", "procurement_standard"),
    "cpdo": ("City Planning & Development Office (CPDO)", "planning_and_spatial_analysis"),
    "ledipo": ("Local Economic Development & Investment (LEDIPO)", "economic_promotion"),
    "bplo": ("Business Permits & Licensing Office (BPLO)", "permits_and_compliance"),
    "accounting": ("City Budget & Accounting Office", "financial_clearance"),
    "hr": ("Human Resource & Administration", "hr_and_capacity_building"),
}


def classify_with_laya_model(
    task_title: str,
    task_desc: str,
    skills: list[str],
    context: str = "",
) -> dict[str, Any] | None:
    """Use the real non-autoregressive laya.Router from NandhaKishorM/laya."""
    router = get_laya_router()
    if not router:
        return None

    state = {
        "task": task_title,
        "description": task_desc,
        "skills": ", ".join(skills),
        "section": context,
    }
    questions = {
        "workflow": {
            "type": "choice",
            "instructions": "Which municipal department handles this local government project task?",
            "criteria": {
                "it": "Information Technology: server, networking, software, database, cybersecurity",
                "procurement": "Procurement / GSO: purchasing hardware, supplies, bidding, BAC, canvassing",
                "cpdo": "City Planning & Development: zoning, land use, demographic studies, urban master plans",
                "ledipo": "Local Economic Development: trade fairs, investments, tourism, business promotion",
                "bplo": "Business Permits & Licensing: business inspections, permits, compliance, ordinances",
                "accounting": "City Budget & Accounting: liquidation, vouchers, disbursements, financial audit",
                "hr": "Human Resource: training workshops, seminars, capacity development, personnel",
            },
        },
        "urgency": {
            "type": "score",
            "instructions": "How urgent or critical is this task to the project schedule?",
            "criteria": ["low", "medium", "high"],
        },
        "requires_bac": {
            "type": "noul",
            "instructions": "Does this task require formal Bids and Awards Committee (BAC) resolution or high-value procurement?",
        },
    }

    try:
        prediction = router.predict(state, questions)
        answers = prediction.get("answers", {})

        wf_answer = answers.get("workflow", {})
        choice = wf_answer.get("choice", "")
        wf_conf = float(wf_answer.get("answer_confidence", 0.85))

        urg_answer = answers.get("urgency", {})
        urg_score = urg_answer.get("score", 1)
        priority_map = {0: "low", 1: "medium", 2: "high"}
        priority = priority_map.get(urg_score, "medium")

        bac_answer = answers.get("requires_bac", {})
        requires_bac = bool(bac_answer.get("answer", False)) or (float(bac_answer.get("probability", 0)) > 0.6)

        dept_info = LAYA_CHOICE_MAP.get(choice)
        if not dept_info:
            return None

        return {
            "department": dept_info[0],
            "workflow": dept_info[1],
            "confidence": round(wf_conf, 2),
            "priority": priority,
            "requires_bac": requires_bac,
        }
    except Exception as exc:
        logger.warning(f"[Laya] Router.predict failed: {exc}")
        return None


# ─── Decision Modules ──────────────────────────────────────────────────

def classify_workflow_routing(
    task_title: str,
    task_desc: str,
    skills: list[str],
    context: str = "",
) -> dict[str, Any]:
    """System-1 Classification: Which municipal department/workflow handles this task?"""
    # First: try real laya.Router prediction
    laya_pred = classify_with_laya_model(task_title, task_desc, skills, context)
    if laya_pred:
        return {
            "department": laya_pred["department"],
            "workflow": laya_pred["workflow"],
            "confidence": laya_pred["confidence"],
            "laya_model": True,
            "priority_hint": laya_pred.get("priority"),
            "requires_bac_hint": laya_pred.get("requires_bac"),
        }

    # Fallback: municipal keyword scoring
    combined = f"{task_title} {task_desc} {' '.join(skills)} {context}".lower()

    best_domain = MUNICIPAL_DOMAINS[0]
    highest_score = -1

    for domain in MUNICIPAL_DOMAINS:
        score = 0
        for kw in domain["keywords"]:
            if kw.lower() in combined:
                score += 2
        for sk in domain["skills"]:
            if sk.lower() in combined:
                score += 1
        if score > highest_score:
            highest_score = score
            best_domain = domain

    # Calibrated confidence metric (0.72 – 0.96)
    if highest_score >= 5:
        confidence = min(0.96, 0.86 + highest_score * 0.015)
    elif highest_score >= 2:
        confidence = 0.85
    elif highest_score == 1:
        confidence = 0.78
    else:
        confidence = 0.72

    return {
        "department": best_domain["department"],
        "workflow": best_domain["workflow"],
        "confidence": round(confidence, 2),
        "laya_model": False,
    }


def classify_clearance(
    task_title: str,
    task_desc: str,
    budget_lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """System-1 Decision: Does this task trigger BAC clearance, cash advances, or mayoral review?"""
    text = f"{task_title} {task_desc}".lower()
    total_amount = 0.0
    if budget_lines:
        for b in budget_lines:
            try:
                total_amount += float(b.get("amount", 0))
            except (ValueError, TypeError):
                pass

    is_high_value = total_amount >= 50_000
    has_procurement = any(
        kw in text for kw in [
            "procure", "purchase", "bidding", "server", "hardware",
            "equipment", "supplier", "canvass", "requisition", "asset",
        ]
    )
    requires_bac = (has_procurement and is_high_value) or "bids and awards" in text or "bac" in text

    has_cash_advance = any(
        kw in text for kw in [
            "travel", "transport", "meals", "snacks", "honoraria",
            "petty cash", "field supply", "per diem", "transit",
        ]
    )
    requires_cash_advance = has_cash_advance or (0 < total_amount < 50_000 and not requires_bac)

    if requires_bac:
        tier = "tier_2_bac_mayoral"
        badge = "BAC Resolution Required"
        reason = "High-value procurement requiring Bids and Awards Committee resolution and Mayoral sign-off."
        conf = 0.95
    elif has_procurement and not is_high_value:
        tier = "tier_1_procurement"
        badge = "Direct Procurement"
        reason = "Small-value procurement under statutory threshold."
        conf = 0.89
    elif requires_cash_advance:
        tier = "cash_advance"
        badge = "Petty Cash / Advance"
        reason = "Operational advance or field disbursement subject to COA liquidation."
        conf = 0.91
    else:
        tier = "standard_head"
        badge = "Department Standard"
        reason = "Standard departmental milestone and head review."
        conf = 0.93

    return {
        "requiresBAC": requires_bac,
        "requiresCashAdvance": requires_cash_advance,
        "approvalTier": tier,
        "badge": badge,
        "reason": reason,
        "confidence": round(conf, 2),
    }


def classify_priority(
    task_title: str,
    task_desc: str,
    skills: list[str],
    subtasks: list[str],
) -> str:
    """System-1 Decision: Evaluate priority based on criticality and dependencies."""
    combined = f"{task_title} {task_desc} {' '.join(skills)} {' '.join(subtasks)}".lower()

    high_keywords = [
        "prerequisite", "core", "infrastructure", "foundation", "inception",
        "compliance", "mandatory", "urgent", "security", "framework",
        "server", "procure servers", "network configuration", "critical",
    ]
    if any(k in combined for k in high_keywords):
        return "high"

    low_keywords = [
        "archive", "documentation", "retrospective", "post-evaluation",
        "optional", "backup copy", "future phase", "survey follow-up",
    ]
    if any(k in combined for k in low_keywords):
        return "low"

    return "medium"


def match_personnel(
    task_skills: list[str],
    task_title: str,
    task_desc: str,
    employees: list[ParsedEmployee],
    lead_history: dict[str, int] | None = None,
) -> tuple[list[str], str]:
    """Bounded Personnel Matching: Selects optimal Lead and Support team with global balancing."""
    if not employees:
        return ([], "No department employees available for assignment.")

    normalized_task_text = f"{task_title} {task_desc} {' '.join(task_skills)}".lower()

    scored_candidates: list[tuple[float, ParsedEmployee, list[str]]] = []

    for emp in employees:
        score = 0.0
        matched_skills: list[str] = []

        # Check required skills against candidate profile
        for sk in task_skills:
            sk_norm = sk.strip().lower()
            if not sk_norm:
                continue
            # Match in job role
            if sk_norm in emp.role.lower():
                score += 15
                matched_skills.append(sk)
            # Match in profile skills
            elif any(sk_norm in es.lower() for es in emp.skills):
                score += 12
                matched_skills.append(sk)
            # Match in strengths
            elif any(sk_norm in st.lower() for st in emp.strengths):
                score += 10
                matched_skills.append(sk)
            # Match in tags
            elif any(sk_norm in tg.lower() for tg in emp.tags):
                score += 6
                matched_skills.append(sk)

        # General text matching if skills list was sparse
        for st in emp.strengths:
            if st.lower() in normalized_task_text and len(st) > 3:
                score += 5
                matched_skills.append(st)

        # Weakness / risk constraint penalty
        for w in emp.weaknesses:
            if w.lower() in normalized_task_text and len(w) > 3:
                score -= 18

        # Workload damping
        if emp.workload >= 80:
            score -= 12  # Overload penalty
        elif emp.workload >= 60:
            score -= 5

        # Cross-part leadership balancing penalty (avoids one person dominating across all 8 parts)
        if lead_history and emp.id in lead_history:
            repeat_count = lead_history[emp.id]
            score -= repeat_count * 15

        scored_candidates.append((score, emp, list(set(matched_skills))))

    # Sort descending by score, tie-break by lower workload
    scored_candidates.sort(key=lambda item: (item[0], -item[1].workload), reverse=True)

    top = scored_candidates[0]
    lead = top[1]
    recommended_ids = [lead.id]

    if lead_history is not None:
        lead_history[lead.id] = lead_history.get(lead.id, 0) + 1

    # Decide if task needs support members (multi-disciplinary, workshop, procurement)
    needs_team = any(
        kw in normalized_task_text
        for kw in ["workshop", "canvass", "procure", "validation", "consultation", "seminar", "audit"]
    ) or len(task_skills) >= 3

    if needs_team and len(scored_candidates) > 1:
        support = scored_candidates[1][1]
        recommended_ids.append(support.id)
        reason = (
            f"Assigned team: {lead.name} as Lead ({', '.join(top[2]) or 'strong alignment'}) "
            f"supported by {support.name} for collaborative execution. Balanced for capacity."
        )
    else:
        reason = (
            f"Assigned solo to {lead.name} (Role: {lead.role or 'Specialist'} | "
            f"Fit: {', '.join(top[2]) or 'Qualified'} | Workload: {lead.workload}%)."
        )

    return (recommended_ids, reason)


# ─── Top-Level Enrichment Pipeline ─────────────────────────────────────

def enrich_task_with_laya(
    task: dict[str, Any],
    context_title: str,
    employees: list[ParsedEmployee],
    budget_schedule: str = "",
    lead_history: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Apply Laya System-1 Decisions to a single task extracted by DeepSeek R1."""
    title = str(task.get("title") or "").strip()
    desc = str(task.get("description") or "").strip()
    skills = [str(s) for s in task.get("requiredSkills") or []]
    subtasks = [str(s) for s in task.get("subtasks") or []]
    duration = str(task.get("estimatedDuration") or "2 weeks").strip()

    # 1. Routing Decision
    routing = classify_workflow_routing(title, desc, skills, context_title)

    # 2. Clearance Decision
    budget_lines = task.get("budgetLines") if isinstance(task.get("budgetLines"), list) else None
    clearance = classify_clearance(title, desc, budget_lines)

    # 3. Priority Decision
    priority = task.get("priority") or classify_priority(title, desc, skills, subtasks)
    if priority not in ("high", "medium", "low"):
        priority = "medium"

    # 4. Personnel Decision (with global workload balancing)
    assigned_ids, staff_reason = match_personnel(skills, title, desc, employees, lead_history=lead_history)

    # 5. Build Rich Audit Reasoning
    confidence_pct = int(routing["confidence"] * 100)
    audit_reason = (
        f"[Laya Decision · {confidence_pct}% conf · {routing['department']} · {clearance['badge']}] "
        f"{staff_reason} {clearance['reason']}"
    )

    # 6. Budget Decision Fallback
    budget_decision = task.get("budgetDecision") or "missing"
    if budget_decision not in ("funded", "no_cost", "missing"):
        budget_decision = "missing"

    return {
        "title": title,
        "description": desc,
        "estimatedDuration": duration,
        "requiredSkills": skills,
        "priority": priority,
        "recommendedEmployeeIds": assigned_ids,
        "recommendationReasoning": audit_reason,
        "budgetDecision": budget_decision,
        "budgetNoCostReason": task.get("budgetNoCostReason") or "",
        "budgetLines": task.get("budgetLines") or [],
        "subtasks": subtasks if subtasks else ["Plan and prepare", "Execute deliverables", "Review and finalize"],
    }
