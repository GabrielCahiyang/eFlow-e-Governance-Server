"""Proposal validation endpoints used before AI decomposition."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from proposal_validation import validate_proposal_document


router = APIRouter(prefix="/api/proposals", tags=["proposals"])


class ValidateProposalRequest(BaseModel):
    document_text: str = Field(min_length=1, max_length=500_000)
    file_name: str = Field(default="", max_length=255)


@router.post("/validate")
async def validate_proposal(body: ValidateProposalRequest) -> dict:
    result = validate_proposal_document(body.document_text).to_dict()
    result["file_name"] = body.file_name
    return result
