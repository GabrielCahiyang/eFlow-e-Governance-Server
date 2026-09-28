"""Regression tests for the server-side PDF proposal gate."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from proposal_validation import validate_proposal_document


VALID_PROPOSAL = """
PROJECT PROPOSAL
I. Project Title: Local Economic Development Roadmap
II. Proponents: City Planning Office and LEDIPO
III. Background and Rationale
The city requires a coordinated investment plan to improve local employment and growth.
IV. Purpose and Objectives
The project will assess priority industries, identify investments, and prepare a roadmap.
V. Scope and Methodology
Part 1: Inception and stakeholder consultation. Part 2: Economic diagnostic and workshops.
The consultant will deliver a situation analysis, implementation plan, and final report.
VI. Schedule
Month 1 inception, Month 2 analysis, Month 3 validation, Month 4 final delivery.
VII. Proposed Budget
Total project cost: PHP 2,156,500.00. Funding Source: City Planning Office.
VIII. Monitoring and Evaluation
Performance indicators and milestones will be reviewed monthly.
Submitted by: Project Officer. Recommended for Approval: City Administrator. Approved by: City Mayor.
""" + (" Supporting project implementation detail." * 80)


class TestProposalValidation(unittest.TestCase):
    def test_accepts_complete_government_proposal(self):
        result = validate_proposal_document(VALID_PROPOSAL)
        self.assertTrue(result.is_proposal)
        self.assertGreaterEqual(result.score, 60)
        self.assertIn("budget", result.matched_sections)

    def test_rejects_random_readable_pdf_text(self):
        random_document = (
            "A collection of recipes and travel notes. "
            "The first chapter describes bread, parks, weather, and family stories. " * 30
        )
        result = validate_proposal_document(random_document)
        self.assertFalse(result.is_proposal)
        self.assertIn("project/proposal identity", result.missing_sections)

    def test_rejects_short_file_with_proposal_word_only(self):
        result = validate_proposal_document("Project proposal for a new idea.")
        self.assertFalse(result.is_proposal)
        self.assertLess(result.word_count, 120)


if __name__ == "__main__":
    unittest.main(verbosity=2)
