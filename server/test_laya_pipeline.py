"""Unit tests for laya_service and proposal_pipeline."""

import unittest
from laya_service import (
    classify_clearance,
    classify_priority,
    classify_workflow_routing,
    enrich_task_with_laya,
    match_personnel,
    parse_employees_block,
    ParsedEmployee,
)
from proposal_pipeline import (
    build_r1_wbs_prompt,
    extract_json_payload,
    is_proposal_decomposition_prompt,
    parse_section_prompt,
)


class TestLayaPipeline(unittest.TestCase):
    def setUp(self):
        self.sample_employees_text = """- ID: emp-it-1 | Name: Crisostomo Ibarra | Role: Senior Systems Administrator
  Workload: 35% | Skills: Networking, Server Administration, Cybersecurity
  Strengths: Network architecture, Linux, Database optimization
  Weakness/risk constraints: Public speaking, Event facilitation
  Manager notes: Highly technical lead for infrastructure.
  Tags: IT, Lead, Technical
- ID: emp-proc-1 | Name: Maria Clara | Role: Procurement Specialist
  Workload: 20% | Skills: Public Procurement, Supply Chain, Logistics
  Strengths: RA 9184 compliance, Canvassing, Supplier negotiations
  Weakness/risk constraints: Software programming
  Manager notes: Excellent documentation for BAC.
  Tags: Procurement, BAC, Finance"""

    def test_parse_employees_block(self):
        employees = parse_employees_block(self.sample_employees_text)
        self.assertEqual(len(employees), 2)

        emp1 = employees[0]
        self.assertEqual(emp1.id, "emp-it-1")
        self.assertEqual(emp1.name, "Crisostomo Ibarra")
        self.assertEqual(emp1.role, "Senior Systems Administrator")
        self.assertEqual(emp1.workload, 35)
        self.assertIn("Networking", emp1.skills)
        self.assertIn("Linux", emp1.strengths)
        self.assertIn("Public speaking", emp1.weaknesses)

        emp2 = employees[1]
        self.assertEqual(emp2.id, "emp-proc-1")
        self.assertEqual(emp2.name, "Maria Clara")
        self.assertEqual(emp2.workload, 20)

    def test_classify_workflow_routing(self):
        it_task = {
            "title": "Configure municipal rack servers and firewall VLANs",
            "desc": "Set up server network interface and security rules.",
            "skills": ["Networking", "Security"],
        }
        routing_it = classify_workflow_routing(
            it_task["title"], it_task["desc"], it_task["skills"]
        )
        self.assertEqual(
            routing_it["department"], "Information Technology & Digital Services"
        )
        self.assertEqual(routing_it["workflow"], "it_technical_deployment")
        self.assertGreaterEqual(routing_it["confidence"], 0.70)

        proc_task = {
            "title": "Canvass suppliers and prepare purchase request for hardware",
            "desc": "Issue RFQ to qualified bidders according to procurement rules.",
            "skills": ["Procurement", "Supply Management"],
        }
        routing_proc = classify_workflow_routing(
            proc_task["title"], proc_task["desc"], proc_task["skills"]
        )
        self.assertEqual(
            routing_proc["department"], "General Services Office / Procurement"
        )
        self.assertEqual(routing_proc["workflow"], "procurement_standard")

    def test_classify_clearance(self):
        # BAC Clearance on high-value procurement
        bac_res = classify_clearance(
            "Procure servers and network equipment",
            "High-availability server rack purchase",
            budget_lines=[{"amount": 120_000}],
        )
        self.assertTrue(bac_res["requiresBAC"])
        self.assertEqual(bac_res["approvalTier"], "tier_2_bac_mayoral")
        self.assertIn("BAC", bac_res["badge"])

        # Cash Advance on travel/transit
        ca_res = classify_clearance(
            "Conduct field survey in rural barangays",
            "Travel and meal allowance for survey team",
            budget_lines=[{"amount": 15_000}],
        )
        self.assertTrue(ca_res["requiresCashAdvance"])
        self.assertEqual(ca_res["approvalTier"], "cash_advance")

    def test_match_personnel(self):
        employees = parse_employees_block(self.sample_employees_text)
        assigned_ids, reason = match_personnel(
            ["Networking", "Linux"],
            "Configure enterprise server",
            "Setup Linux operating system and VLAN",
            employees,
        )
        self.assertEqual(assigned_ids[0], "emp-it-1")
        self.assertIn("Crisostomo Ibarra", reason)

    def test_enrich_task_with_laya(self):
        employees = parse_employees_block(self.sample_employees_text)
        raw_task = {
            "title": "Procure and configure servers",
            "description": "Purchase high performance servers and configure network.",
            "estimatedDuration": "3 weeks",
            "requiredSkills": ["Procurement", "Networking"],
            "subtasks": ["Step 1", "Step 2"],
        }
        enriched = enrich_task_with_laya(raw_task, "Part 1", employees)
        self.assertIn("priority", enriched)
        self.assertIn("recommendedEmployeeIds", enriched)
        self.assertIn("recommendationReasoning", enriched)
        self.assertIn("[Laya Decision", enriched["recommendationReasoning"])

    def test_is_proposal_decomposition_prompt(self):
        messages = [
            {
                "role": "user",
                "content": 'Break down ONE section of a government project proposal into actionable tasks.\n\nSection title: "Part 1"\n\nAvailable team:\n...',
            }
        ]
        self.assertTrue(is_proposal_decomposition_prompt(messages))

        normal_chat = [{"role": "user", "content": "What is the capital of the Philippines?"}]
        self.assertFalse(is_proposal_decomposition_prompt(normal_chat))

    def test_extract_json_payload(self):
        raw = '<think>\nHere is my thinking process...\n</think>\n{\n  "tasks": [\n    {"title": "Test"}\n  ]\n}'
        payload = extract_json_payload(raw)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["tasks"][0]["title"], "Test")


if __name__ == "__main__":
    unittest.main()
