"""Proposal validation endpoints used before AI decomposition."""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Literal
import re

from proposal_validation import validate_proposal_document


router = APIRouter(prefix="/api/proposals", tags=["proposals"])


class ValidateProposalRequest(BaseModel):
    document_text: str = Field(min_length=1, max_length=500_000)
    file_name: str = Field(default="", max_length=255)
    mode: Literal["proposal", "workspace"] = "proposal"


@router.post("/validate")
async def validate_proposal(body: ValidateProposalRequest) -> dict:
    if body.mode == "workspace":
        words = len(body.document_text.split())
        relevant = bool(re.search(r"\b(project|program|proposal|implementation|work\s*plan|objectives?|deliverables?|activities|tasks)\b", body.document_text, re.I))
        accepted = words >= 20 and relevant
        return {"is_proposal": accepted, "word_count": words, "file_name": body.file_name,
                "message": "Project document is ready for review." if accepted else "Use a project document or a brief describing objectives and work (at least 20 words)."}
    result = validate_proposal_document(body.document_text).to_dict()
    result["file_name"] = body.file_name
    return result
