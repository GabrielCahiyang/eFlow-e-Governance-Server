"""Deterministic document gate for proposal decomposition.

The browser sends extracted PDF text here before any LLM prompt is created.
This keeps unrelated readable PDFs out of the generative pipeline and gives the
user concrete missing-section feedback instead of relying on JSON parse errors.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ProposalValidationResult:
    is_proposal: bool
    score: int
    word_count: int
    matched_sections: list[str]
    missing_sections: list[str]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SECTION_RULES: dict[str, tuple[int, tuple[str, ...]]] = {
    "identity": (
        16,
        (
            r"\bproject\s+proposal\b",
            r"\bproposal\s+title\b",
            r"\bproject\s+title\b",
            r"\bproject\s+description\b",
            r"\bterms\s+of\s+reference\b",
        ),
    ),
    "rationale": (
        10,
        (
            r"\bbackground\s+(?:and|&)\s+rationale\b",
            r"\brationale\b",
            r"\bproblem\s+statement\b",
            r"\bjustification\b",
        ),
    ),
    "objectives": (
        12,
        (
            r"\bpurpose\s+(?:and|&)\s+objectives\b",
            r"\bproject\s+objectives?\b",
            r"\bspecific\s+objectives?\b",
            r"\bobjectives?\s*[:\n]",
        ),
    ),
    "delivery_scope": (
        14,
        (
            r"\bscope\s+(?:and|&)\s+methodology\b",
            r"\bmethodology\b",
            r"\bwork\s*plan\b",
            r"\bdeliverables?\b",
            r"\bimplementation\s+plan\b",
        ),
    ),
    "schedule": (
        10,
        (
            r"\bschedule\b",
            r"\btimeline\b",
            r"\bmonth\s+\d+\b",
            r"\bimplementation\s+period\b",
        ),
    ),
    "budget": (
        14,
        (
            r"\bproposed\s+budget\b",
            r"\bproject\s+costs?\b",
            r"\btotal\s+project\s+cost\b",
            r"\bfunding\s+source\b",
            r"(?:₱|php|p)\s*\d[\d,]*(?:\.\d{2})?",
        ),
    ),
    "responsibility": (
        8,
        (
            r"\bproponents?\b",
            r"\bimplementing\s+(?:office|agency|unit)\b",
            r"\bresponsible\s+(?:office|person|unit)\b",
            r"\bproject\s+team\b",
        ),
    ),
    "monitoring": (
        8,
        (
            r"\bmonitoring\s+(?:and|&)\s+evaluation\b",
            r"\bperformance\s+indicators?\b",
            r"\bmonitoring\s+plan\b",
        ),
    ),
    "approval": (
        8,
        (
            r"\bapproved\s+by\b",
            r"\brecommended\s+for\s+approval\b",
            r"\bsubmitted\s+by\b",
            r"\bauthorized\s+by\b",
        ),
    ),
    "action_structure": (
        10,
        (
            r"\baction\s+details\b",
            r"\bpart\s+\d+\s*:",
            r"\bactivities?\b",
            r"\bmilestones?\b",
        ),
    ),
}

_REQUIRED_LABELS = {
    "identity": "project/proposal identity",
    "objectives": "objectives",
    "delivery_scope": "scope, methodology, or deliverables",
    "schedule": "schedule or timeline",
    "budget": "budget or funding source",
}


def validate_proposal_document(document_text: str) -> ProposalValidationResult:
    """Score extracted PDF text and reject documents lacking proposal evidence."""
    normalized = re.sub(r"\s+", " ", document_text or " ").strip().lower()
    word_count = len(re.findall(r"\b[\w'-]+\b", normalized))
    matched: list[str] = []
    score = 0

    for section, (weight, patterns) in _SECTION_RULES.items():
        if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns):
            matched.append(section)
            score += weight

    if word_count >= 500:
        score += 8
    elif word_count >= 180:
        score += 4

    score = min(100, score)
    required_present = {
        "identity",
        "objectives",
        "delivery_scope",
    }.issubset(matched)
    planning_evidence = "schedule" in matched or "budget" in matched
    is_proposal = (
        word_count >= 120
        and score >= 60
        and required_present
        and planning_evidence
        and len(matched) >= 5
    )

    missing = [
        label for key, label in _REQUIRED_LABELS.items() if key not in matched
    ]
    if is_proposal:
        message = "Proposal document validated for AI decomposition."
    else:
        detail = ", ".join(missing) if missing else "enough proposal-specific evidence"
        message = (
            "This PDF does not appear to be a complete project proposal. "
            f"Missing or unclear: {detail}."
        )

    return ProposalValidationResult(
        is_proposal=is_proposal,
        score=score,
        word_count=word_count,
        matched_sections=matched,
        missing_sections=missing,
        message=message,
    )
