"""Polygon Blockchain Governance Ledger for eFlow.

Anchors municipal proposal lifecycle events on Polygon Amoy Testnet using
calldata-only transactions (no smart contract required).

Anchoring strategy:
  - Compute SHA-256 hash of the payload document.
  - Send a 0-MATIC transaction to self with the hash in the `data` field.
  - Record the resulting transaction hash + block number in Supabase.
  - Verification: recompute hash and confirm it matches the on-chain calldata.

Environment variables required in .env:
  POLYGON_PRIVATE_KEY  — hex private key (with or without 0x prefix)
  POLYGON_RPC_URL      — default: https://rpc-amoy.polygon.technology
  POLYGON_CHAIN_ID     — default: 80002
  POLYGON_MODE         — auto (default), live, or simulation
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger("eflow.polygon")

POLYGON_RPC_URL: str = os.getenv(
    "POLYGON_RPC_URL", "https://rpc-amoy.polygon.technology"
)
POLYGON_CHAIN_ID: int = int(os.getenv("POLYGON_CHAIN_ID", "80002"))
POLYGON_PRIVATE_KEY: str = os.getenv("POLYGON_PRIVATE_KEY", "")
POLYGON_MODE: str = os.getenv("POLYGON_MODE", "auto").strip().lower()

_SIMULATION_MODES = {"simulation", "simulate", "mock", "offline", "test"}
_LIVE_MODES = {"live", "amoy", "onchain", "on-chain"}


def _resolve_simulation_mode(explicit: Optional[bool] = None) -> bool:
    """Resolve mock/live behavior without silently downgrading an explicit live run."""
    if explicit is not None:
        return explicit
    if POLYGON_MODE in _SIMULATION_MODES:
        return True
    if POLYGON_MODE in _LIVE_MODES:
        return False
    if POLYGON_MODE not in {"", "auto"}:
        raise ValueError(
            "POLYGON_MODE must be one of: auto, live, or simulation."
        )
    return not POLYGON_PRIVATE_KEY.strip()


@dataclass
class AnchorReceipt:
    proposal_id: str
    event_type: str          # "genesis" | "milestone" | "archival_seal"
    document_hash: str       # 0x-prefixed SHA-256 hex
    tx_hash: str             # Polygon transaction hash (or "SIMULATION:..." if no key)
    block_number: Optional[int]
    chain_id: int
    explorer_url: str
    anchored_at: float       # Unix timestamp


def _sha256_hex(payload: Any) -> str:
    """Return 0x-prefixed SHA-256 hash of the canonical JSON representation."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"0x{digest}"


def _get_web3():
    """Return a Web3 instance connected to the configured RPC."""
    from web3 import Web3  # imported lazily — only if web3 package is installed

    w3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))
    return w3


def _send_anchor_tx(
    document_hash: str,
    *,
    simulation: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Send a 0-MATIC calldata transaction to Polygon anchoring the document hash.
    Returns dict with tx_hash, block_number, and simulation flag.
    """
    simulation_enabled = _resolve_simulation_mode(simulation)
    private_key = POLYGON_PRIVATE_KEY.strip()
    if simulation_enabled:
        logger.warning(
            "[Polygon] Running in simulation mode - no transaction will be sent."
        )
        sim_tx = f"SIMULATION:{document_hash[:16]}{int(time.time())}"
        return {
            "tx_hash": sim_tx,
            "block_number": None,
            "simulated": True,
        }

    if not private_key:
        raise RuntimeError(
            "POLYGON_MODE is live but POLYGON_PRIVATE_KEY is not configured."
        )

    if not private_key.startswith("0x"):
        private_key = f"0x{private_key}"

    try:
        from web3 import Web3

        w3 = _get_web3()
        if not w3.is_connected():
            raise RuntimeError(f"Cannot connect to Polygon RPC: {POLYGON_RPC_URL}")

        account = w3.eth.account.from_key(private_key)
        sender = account.address

        # Encode document hash as calldata bytes (UTF-8 of the hex string)
        data_bytes = document_hash.encode("utf-8")

        nonce = w3.eth.get_transaction_count(sender, "pending")
        gas_price = w3.eth.gas_price

        tx = {
            "nonce": nonce,
            "to": sender,          # self-send — no contract needed
            "value": 0,
            "gas": 30_000,         # calldata anchoring is cheap
            "gasPrice": gas_price,
            "data": data_bytes,
            "chainId": POLYGON_CHAIN_ID,
        }

        signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        tx_hash_hex = tx_hash.hex()
        if not tx_hash_hex.startswith("0x"):
            tx_hash_hex = f"0x{tx_hash_hex}"

        # Wait for one confirmation (max 30s)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        block_number = receipt.get("blockNumber")

        logger.info(
            f"[Polygon] Anchored {document_hash[:20]}... "
            f"tx={tx_hash_hex} block={block_number}"
        )

        return {
            "tx_hash": tx_hash_hex,
            "block_number": block_number,
            "simulated": False,
        }

    except Exception as exc:
        logger.error(f"[Polygon] Transaction failed: {exc}")
        raise RuntimeError(f"Polygon anchoring failed: {exc}") from exc


def _make_explorer_url(tx_hash: str, simulated: bool) -> str:
    if simulated:
        return "https://amoy.polygonscan.com (simulation - no live tx)"
    return f"https://amoy.polygonscan.com/tx/{tx_hash}"


class PolygonGovernanceLedger:
    """Immutable event ledger for eFlow proposal lifecycle on Polygon Amoy."""

    def __init__(self, simulation: Optional[bool] = None):
        self.simulation = _resolve_simulation_mode(simulation)

    # ── Genesis: anchor the complete proposal at publication time ─────────

    def anchor_genesis(self, proposal_data: Dict[str, Any]) -> AnchorReceipt:
        """
        Anchors the initial proposal on-chain when it is first published.

        Payload includes: proposal metadata, WBS task list, team assignments,
        budget lines, and publication timestamp.
        """
        proposal_id = str(proposal_data.get("id") or proposal_data.get("proposal_id") or "unknown")
        payload = {
            "event": "genesis",
            "proposal_id": proposal_id,
            "data": proposal_data,
            "anchored_at": time.time(),
        }
        doc_hash = _sha256_hex(payload)
        result = _send_anchor_tx(doc_hash, simulation=self.simulation)

        receipt = AnchorReceipt(
            proposal_id=proposal_id,
            event_type="genesis",
            document_hash=doc_hash,
            tx_hash=result["tx_hash"],
            block_number=result.get("block_number"),
            chain_id=POLYGON_CHAIN_ID,
            explorer_url=_make_explorer_url(result["tx_hash"], result.get("simulated", False)),
            anchored_at=payload["anchored_at"],
        )
        logger.info(f"[Polygon] Genesis anchored for proposal {proposal_id}: {doc_hash}")
        return receipt

    # ── Milestone / BAC Clearance / Cash Disbursement events ─────────────

    def anchor_milestone(
        self,
        proposal_id: str,
        milestone_data: Dict[str, Any],
    ) -> AnchorReceipt:
        """
        Anchors a governance milestone on-chain.

        Milestone types:
        - BAC resolution clearance
        - Cash advance / disbursement
        - Approval decision records
        - Revision commit records
        """
        payload = {
            "event": "milestone",
            "proposal_id": proposal_id,
            "milestone": milestone_data,
            "anchored_at": time.time(),
        }
        doc_hash = _sha256_hex(payload)
        result = _send_anchor_tx(doc_hash, simulation=self.simulation)

        receipt = AnchorReceipt(
            proposal_id=proposal_id,
            event_type="milestone",
            document_hash=doc_hash,
            tx_hash=result["tx_hash"],
            block_number=result.get("block_number"),
            chain_id=POLYGON_CHAIN_ID,
            explorer_url=_make_explorer_url(result["tx_hash"], result.get("simulated", False)),
            anchored_at=payload["anchored_at"],
        )
        logger.info(
            f"[Polygon] Milestone anchored for proposal {proposal_id}: "
            f"{milestone_data.get('type', 'unknown')} → {doc_hash}"
        )
        return receipt

    # ── Archival Seal: full proposal closure with tamper-evident manifest ─

    def anchor_archival_seal(
        self,
        proposal_id: str,
        archival_manifest: Dict[str, Any],
    ) -> AnchorReceipt:
        """
        Anchors the complete archival manifest when a proposal is archived.

        The manifest should include:
        - Final task list with completion state
        - All budget settlement records
        - All approval/revision history hashes
        - Archive timestamp and archiving officer ID
        - SHA-256 of the original genesis transaction
        """
        payload = {
            "event": "archival_seal",
            "proposal_id": proposal_id,
            "manifest": archival_manifest,
            "sealed_at": time.time(),
        }
        doc_hash = _sha256_hex(payload)
        result = _send_anchor_tx(doc_hash, simulation=self.simulation)

        receipt = AnchorReceipt(
            proposal_id=proposal_id,
            event_type="archival_seal",
            document_hash=doc_hash,
            tx_hash=result["tx_hash"],
            block_number=result.get("block_number"),
            chain_id=POLYGON_CHAIN_ID,
            explorer_url=_make_explorer_url(result["tx_hash"], result.get("simulated", False)),
            anchored_at=payload["sealed_at"],
        )
        logger.info(f"[Polygon] Archival seal anchored for proposal {proposal_id}: {doc_hash}")
        return receipt

    # ── Verification: check a document hash against Polygon ──────────────

    def verify_on_chain(self, document_hash: str, tx_hash: str) -> Dict[str, Any]:
        """
        Verify that a document_hash appears in the calldata of the given tx_hash.
        Returns verification status and block details.
        """
        if self.simulation:
            # Simulation mode: verify deterministically from hash prefix
            is_sim = tx_hash.startswith("SIMULATION:")
            expected_prefix = f"SIMULATION:{document_hash[:16]}"
            valid = is_sim and tx_hash.startswith(expected_prefix)
            return {
                "valid": valid,
                "document_hash": document_hash,
                "tx_hash": tx_hash,
                "block_number": None,
                "simulated": True,
                "message": "Simulation mode (no on-chain transaction)",
            }

        try:
            from web3 import Web3

            w3 = _get_web3()
            tx = w3.eth.get_transaction(tx_hash)
            calldata_hex = tx.get("input", "0x")

            # Decode the calldata bytes back to string
            try:
                if isinstance(calldata_hex, (bytes, bytearray)):
                    calldata_str = calldata_hex.decode("utf-8", errors="replace")
                else:
                    calldata_str = bytes.fromhex(
                        str(calldata_hex).replace("0x", "")
                    ).decode("utf-8", errors="replace")
            except Exception:
                calldata_str = str(calldata_hex)

            valid = document_hash in calldata_str
            block_number = int(tx.get("blockNumber") or 0)

            return {
                "valid": valid,
                "document_hash": document_hash,
                "tx_hash": tx_hash,
                "block_number": block_number,
                "simulated": False,
                "explorer_url": _make_explorer_url(tx_hash, False),
                "message": "Hash verified on-chain" if valid else "Hash NOT found in transaction calldata — possible tampering",
            }
        except Exception as exc:
            logger.error(f"[Polygon] Verification failed: {exc}")
            return {
                "valid": False,
                "document_hash": document_hash,
                "tx_hash": tx_hash,
                "block_number": None,
                "simulated": False,
                "error": str(exc),
                "message": f"Verification error: {exc}",
            }

    # ── Certificate: full chain-of-custody record for a proposal ─────────

    def get_proposal_certificate(
        self,
        proposal_id: str,
        receipts: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Generates a printable chain-of-custody certificate for a proposal.
        Receipts should be the stored AnchorReceipt dicts from the database.
        """
        genesis = next((r for r in receipts if r.get("event_type") == "genesis"), None)
        seal = next((r for r in receipts if r.get("event_type") == "archival_seal"), None)
        milestones = [r for r in receipts if r.get("event_type") == "milestone"]

        return {
            "proposal_id": proposal_id,
            "chain": "Polygon Amoy Testnet",
            "chain_id": POLYGON_CHAIN_ID,
            "total_anchors": len(receipts),
            "genesis": genesis,
            "milestones": milestones,
            "archival_seal": seal,
            "integrity_status": (
                "SEALED" if seal else "ACTIVE" if genesis else "UNANCHORED"
            ),
            "certificate_generated_at": time.time(),
        }


# Module-level singleton
_ledgers: Dict[bool, PolygonGovernanceLedger] = {}


def get_ledger(*, simulation: Optional[bool] = None) -> PolygonGovernanceLedger:
    """Return the shared ledger for the requested mode.

    Pass ``simulation=True`` for local demos and tests even when a wallet key
    exists in .env. Production callers can keep using ``get_ledger()`` and set
    POLYGON_MODE=live.
    """
    resolved_mode = _resolve_simulation_mode(simulation)
    if resolved_mode not in _ledgers:
        _ledgers[resolved_mode] = PolygonGovernanceLedger(
            simulation=resolved_mode,
        )
    return _ledgers[resolved_mode]
