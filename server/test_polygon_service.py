"""Unit tests for polygon_service.py (Polygon Governance Ledger).

These tests run in SIMULATION mode (no POLYGON_PRIVATE_KEY required).
All blockchain calls fall back to deterministic simulation so the suite
runs offline and in CI without a funded wallet.

Run with:
  python -m pytest server/test_polygon_service.py -v
or:
  python server/test_polygon_service.py
"""

import sys
import os
import unittest
import time

# Explicit simulation must win even if a developer has a wallet in .env.
os.environ["POLYGON_MODE"] = "simulation"

sys.path.insert(0, os.path.dirname(__file__))

from polygon_service import (
    PolygonGovernanceLedger,
    _sha256_hex,
    get_ledger,
)


SAMPLE_PROPOSAL = {
    "id": "prop-test-001",
    "title": "LEDIPO Infrastructure Upgrade 2025",
    "department": "LEDIPO",
    "tasks": [
        {"title": "Network setup", "budget": 25000},
        {"title": "Software procurement", "budget": 15000},
    ],
    "total_budget": 40000,
    "published_by": "emp-001",
    "published_at": "2025-01-15T08:00:00+08:00",
}

SAMPLE_MILESTONE = {
    "type": "bac_clearance",
    "resolution_number": "BAC-2025-001",
    "amount": 25000.0,
    "cleared_by": "emp-003",
    "cleared_at": "2025-01-20T10:00:00+08:00",
}

SAMPLE_ARCHIVAL_MANIFEST = {
    "final_status": "completed",
    "total_disbursed": 38500.0,
    "total_returned": 1500.0,
    "archived_by": "emp-head-001",
    "archived_at": "2025-06-30T17:00:00+08:00",
    "genesis_tx_hash": "SIMULATION:abc123",
    "task_completion_hashes": ["0xabc...", "0xdef...", "0x123..."],
}


class TestSha256Hash(unittest.TestCase):
    def test_returns_0x_prefixed(self):
        h = _sha256_hex({"test": "data"})
        self.assertTrue(h.startswith("0x"))

    def test_length_66_chars(self):
        h = _sha256_hex({"proposal_id": "test-001"})
        self.assertEqual(len(h), 66)

    def test_deterministic(self):
        payload = {"id": "prop-001", "title": "Test Proposal"}
        h1 = _sha256_hex(payload)
        h2 = _sha256_hex(payload)
        self.assertEqual(h1, h2)

    def test_different_payloads_different_hash(self):
        h1 = _sha256_hex({"budget": 10000})
        h2 = _sha256_hex({"budget": 10001})  # 1 peso difference should change hash
        self.assertNotEqual(h1, h2)


class TestAnchorGenesis(unittest.TestCase):
    def setUp(self):
        self.ledger = PolygonGovernanceLedger()

    def test_anchor_genesis_returns_receipt(self):
        receipt = self.ledger.anchor_genesis(SAMPLE_PROPOSAL)
        self.assertEqual(receipt.proposal_id, "prop-test-001")
        self.assertEqual(receipt.event_type, "genesis")
        self.assertTrue(receipt.document_hash.startswith("0x"))
        self.assertEqual(len(receipt.document_hash), 66)

    def test_anchor_genesis_simulation_tx(self):
        receipt = self.ledger.anchor_genesis(SAMPLE_PROPOSAL)
        self.assertTrue(receipt.tx_hash.startswith("SIMULATION:"))

    def test_anchor_genesis_chain_id(self):
        receipt = self.ledger.anchor_genesis(SAMPLE_PROPOSAL)
        self.assertEqual(receipt.chain_id, 80002)  # Polygon Amoy

    def test_anchor_genesis_explorer_url(self):
        receipt = self.ledger.anchor_genesis(SAMPLE_PROPOSAL)
        self.assertIn("amoy.polygonscan.com", receipt.explorer_url)

    def test_anchor_genesis_timestamped(self):
        before = time.time()
        receipt = self.ledger.anchor_genesis(SAMPLE_PROPOSAL)
        after = time.time()
        self.assertGreaterEqual(receipt.anchored_at, before)
        self.assertLessEqual(receipt.anchored_at, after)

    def test_explicit_simulation_ignores_configured_wallet(self):
        ledger = get_ledger(simulation=True)
        receipt = ledger.anchor_genesis(SAMPLE_PROPOSAL)
        self.assertTrue(receipt.tx_hash.startswith("SIMULATION:"))


class TestAnchorMilestone(unittest.TestCase):
    def setUp(self):
        self.ledger = PolygonGovernanceLedger()

    def test_anchor_milestone_returns_receipt(self):
        receipt = self.ledger.anchor_milestone("prop-test-001", SAMPLE_MILESTONE)
        self.assertEqual(receipt.proposal_id, "prop-test-001")
        self.assertEqual(receipt.event_type, "milestone")
        self.assertTrue(receipt.document_hash.startswith("0x"))

    def test_different_milestones_different_hashes(self):
        r1 = self.ledger.anchor_milestone("prop-001", {"type": "bac_clearance", "amount": 10000})
        r2 = self.ledger.anchor_milestone("prop-001", {"type": "cash_advance", "amount": 5000})
        self.assertNotEqual(r1.document_hash, r2.document_hash)


class TestAnchorArchival(unittest.TestCase):
    def setUp(self):
        self.ledger = PolygonGovernanceLedger()

    def test_archival_seal_returns_receipt(self):
        receipt = self.ledger.anchor_archival_seal("prop-test-001", SAMPLE_ARCHIVAL_MANIFEST)
        self.assertEqual(receipt.proposal_id, "prop-test-001")
        self.assertEqual(receipt.event_type, "archival_seal")

    def test_archival_seal_hash_is_valid_sha256(self):
        # Each seal stamps time.time() so two consecutive calls produce different hashes.
        # What we assert is that each hash is a well-formed 0x-prefixed SHA-256 hex string.
        r1 = self.ledger.anchor_archival_seal("prop-test-001", SAMPLE_ARCHIVAL_MANIFEST)
        self.assertTrue(r1.document_hash.startswith("0x"))
        self.assertEqual(len(r1.document_hash), 66)


class TestVerifyOnChain(unittest.TestCase):
    def setUp(self):
        self.ledger = PolygonGovernanceLedger()

    def test_simulation_verify_matching_tx(self):
        receipt = self.ledger.anchor_genesis(SAMPLE_PROPOSAL)
        result = self.ledger.verify_on_chain(receipt.document_hash, receipt.tx_hash)
        self.assertTrue(result["valid"])
        self.assertTrue(result["simulated"])

    def test_simulation_verify_mismatched_hash(self):
        receipt = self.ledger.anchor_genesis(SAMPLE_PROPOSAL)
        wrong_hash = "0x" + "a" * 64
        result = self.ledger.verify_on_chain(wrong_hash, receipt.tx_hash)
        self.assertFalse(result["valid"])


class TestCertificate(unittest.TestCase):
    def setUp(self):
        self.ledger = PolygonGovernanceLedger()

    def test_certificate_with_all_event_types(self):
        from dataclasses import asdict
        genesis = asdict(self.ledger.anchor_genesis(SAMPLE_PROPOSAL))
        milestone = asdict(self.ledger.anchor_milestone("prop-test-001", SAMPLE_MILESTONE))
        seal = asdict(self.ledger.anchor_archival_seal("prop-test-001", SAMPLE_ARCHIVAL_MANIFEST))

        cert = self.ledger.get_proposal_certificate(
            "prop-test-001", [genesis, milestone, seal]
        )

        self.assertEqual(cert["proposal_id"], "prop-test-001")
        self.assertEqual(cert["total_anchors"], 3)
        self.assertEqual(cert["integrity_status"], "SEALED")
        self.assertIsNotNone(cert["genesis"])
        self.assertIsNotNone(cert["archival_seal"])
        self.assertEqual(len(cert["milestones"]), 1)

    def test_certificate_active_without_seal(self):
        from dataclasses import asdict
        genesis = asdict(self.ledger.anchor_genesis(SAMPLE_PROPOSAL))
        cert = self.ledger.get_proposal_certificate("prop-test-001", [genesis])
        self.assertEqual(cert["integrity_status"], "ACTIVE")

    def test_certificate_unanchored_empty(self):
        cert = self.ledger.get_proposal_certificate("prop-test-001", [])
        self.assertEqual(cert["integrity_status"], "UNANCHORED")
        self.assertEqual(cert["total_anchors"], 0)


class TestSingleton(unittest.TestCase):
    def test_get_ledger_returns_same_instance(self):
        l1 = get_ledger()
        l2 = get_ledger()
        self.assertIs(l1, l2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
