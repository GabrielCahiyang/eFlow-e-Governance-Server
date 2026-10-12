"""FastAPI router for Polygon Blockchain ledger endpoints.

Mounted under /controlpanelEflow/api/blockchain/ by main.py.

Endpoints:
  POST /anchor-proposal                — Anchor proposal genesis on Polygon
  POST /anchor-event                   — Anchor a milestone/clearance event
  GET  /verify/{doc_hash}              — Verify a hash on-chain by tx_hash
  GET  /certificate/{proposal_id}      — Get chain-of-custody certificate
"""

import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from service_monitor import observed_executor

logger = logging.getLogger("eflow.routers.blockchain")

# A single wallet executor prevents nonce races, including after a caller
# disconnects while an already-submitted transaction is waiting for a receipt.
_wallet_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eflow-wallet")
_wallet_slots = asyncio.Semaphore(4)

async def wallet_call(function, *args, metadata=None):
    details = dict(metadata or {})
    ledger = getattr(function, "__self__", None)
    if ledger is not None:
        details["simulated"] = ledger.simulation
    return await observed_executor(_wallet_executor, _wallet_slots, "blockchain", function.__name__,
                                   partial(function, *args), metadata=details)

router = APIRouter(prefix="/api/blockchain", tags=["blockchain"])


# ── Request / Response Models ─────────────────────────────────────────────────


class AnchorProposalRequest(BaseModel):
    proposal_id: str
    proposal_data: Dict[str, Any]


class AnchorEventRequest(BaseModel):
    proposal_id: str
    event_type: str          # e.g. "bac_clearance", "cash_advance", "revision_commit", "approval"
    event_data: Dict[str, Any]


class AnchorReceiptDict(BaseModel):
    proposal_id: str
    event_type: str
    document_hash: str
    tx_hash: str
    block_number: Optional[int]
    chain_id: int
    explorer_url: str
    anchored_at: float


class CertificateRequest(BaseModel):
    proposal_id: str
    receipts: List[Dict[str, Any]]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/anchor-proposal")
async def anchor_proposal(body: AnchorProposalRequest) -> JSONResponse:
    """
    Anchor a proposal genesis event on Polygon Amoy.

    This should be called when a proposal is first published / committed.
    The full proposal_data (tasks, budget, team, metadata) is hashed with
    SHA-256 and the hash is stored in a 0-MATIC calldata transaction.

    Returns an AnchorReceipt with tx_hash, block_number, and explorer URL.
    """
    try:
        from polygon_service import get_ledger
        from dataclasses import asdict

        ledger = get_ledger()
        payload = {"id": body.proposal_id, **body.proposal_data}
        receipt = await wallet_call(ledger.anchor_genesis, payload,
                                    metadata={"proposal_id": body.proposal_id, "event_type": "genesis"})

        return JSONResponse(content=asdict(receipt))

    except Exception as exc:
        logger.exception(f"[Blockchain] anchor_proposal failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Blockchain anchoring error: {str(exc)}")


@router.post("/anchor-event")
async def anchor_event(body: AnchorEventRequest) -> JSONResponse:
    """
    Anchor a governance milestone event on Polygon Amoy.

    Use this for:
    - BAC resolution clearances
    - Cash advance / disbursement approvals
    - Revision commit records
    - Approval decision records

    Returns an AnchorReceipt.
    """
    try:
        from polygon_service import get_ledger
        from dataclasses import asdict

        ledger = get_ledger()
        milestone_data = {"type": body.event_type, **body.event_data}
        receipt = await wallet_call(ledger.anchor_milestone, body.proposal_id, milestone_data,
                                    metadata={"proposal_id": body.proposal_id, "event_type": body.event_type})

        return JSONResponse(content=asdict(receipt))

    except Exception as exc:
        logger.exception(f"[Blockchain] anchor_event failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Blockchain event anchoring error: {str(exc)}")


@router.post("/anchor-archival")
async def anchor_archival(body: AnchorProposalRequest) -> JSONResponse:
    """
    Anchor the final archival seal on Polygon when a proposal is archived.

    The archival_manifest (body.proposal_data) should include the full final
    state: all tasks, approvals, settlements, and a hash of the genesis tx.

    Returns an AnchorReceipt with the archival seal.
    """
    try:
        from polygon_service import get_ledger
        from dataclasses import asdict

        ledger = get_ledger()
        receipt = await wallet_call(ledger.anchor_archival_seal, body.proposal_id, body.proposal_data,
                                    metadata={"proposal_id": body.proposal_id, "event_type": "archival_seal"})

        return JSONResponse(content=asdict(receipt))

    except Exception as exc:
        logger.exception(f"[Blockchain] anchor_archival failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Blockchain archival seal error: {str(exc)}")


@router.get("/verify/{doc_hash}")
async def verify_on_chain(
    doc_hash: str,
    tx_hash: str = Query(..., description="Polygon transaction hash to verify against"),
) -> JSONResponse:
    """
    Verify a document hash exists in the calldata of the given Polygon transaction.

    Returns:
      - valid: bool — True if hash found in tx calldata
      - block_number: int — block number where tx was mined
      - simulated: bool — True if running without a live private key
      - message: str — human-readable verification result
    """
    if not doc_hash.startswith("0x") or len(doc_hash) != 66:
        raise HTTPException(
            status_code=400,
            detail="doc_hash must be a 0x-prefixed SHA-256 hex string (66 chars)",
        )

    try:
        from polygon_service import get_ledger

        ledger = get_ledger()
        result = await wallet_call(ledger.verify_on_chain, doc_hash, tx_hash,
                                   metadata={"document_hash": doc_hash, "tx_hash": tx_hash})

        return JSONResponse(content=result)

    except Exception as exc:
        logger.exception(f"[Blockchain] verify_on_chain failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Verification error: {str(exc)}")


@router.post("/certificate/{proposal_id}")
async def get_certificate(
    proposal_id: str,
    body: CertificateRequest,
) -> JSONResponse:
    """
    Generate a chain-of-custody certificate for a proposal.

    Accepts a list of stored AnchorReceipt dicts (from Supabase) and returns
    a structured certificate showing genesis, milestones, and archival seal.

    This is used by the eFlow client to render the "Polygon Verified" badge
    and print-ready certificate modal.
    """
    try:
        from polygon_service import get_ledger

        ledger = get_ledger()
        certificate = await wallet_call(ledger.get_proposal_certificate, proposal_id, body.receipts,
                                        metadata={"proposal_id": proposal_id})

        return JSONResponse(content=certificate)

    except Exception as exc:
        logger.exception(f"[Blockchain] get_certificate failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Certificate generation error: {str(exc)}")
