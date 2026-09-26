"""Unit tests for pygad_optimizer.py (PyGAD RCPSP Optimizer).

Run with:
  python -m pytest server/test_pygad_optimizer.py -v
or:
  python server/test_pygad_optimizer.py
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from pygad_optimizer import (
    ProposalOptimizer,
    run_proposal_optimization,
    _calculate_skill_overlap,
    _calculate_weakness_penalty,
    PROFILES,
)


SAMPLE_EMPLOYEES = [
    {
        "id": "emp-001",
        "name": "Alice Reyes",
        "role": "IT Officer",
        "workload": 10,
        "skills": ["software development", "database", "network"],
        "strengths": ["problem solving", "system analysis"],
        "weaknesses": ["public speaking"],
    },
    {
        "id": "emp-002",
        "name": "Bob Santos",
        "role": "Planning Officer",
        "workload": 15,
        "skills": ["project planning", "scheduling", "budget management"],
        "strengths": ["coordination", "documentation"],
        "weaknesses": ["coding"],
    },
    {
        "id": "emp-003",
        "name": "Carol Lim",
        "role": "Finance Officer",
        "workload": 8,
        "skills": ["financial analysis", "budget monitoring", "reporting"],
        "strengths": ["accuracy", "compliance"],
        "weaknesses": ["technical systems"],
    },
]

SAMPLE_TASKS = [
    {
        "title": "Set up network infrastructure",
        "description": "Configure VLAN, switches, and server rack for the new office.",
        "estimatedDuration": "5 days",
        "requiredSkills": ["network", "hardware", "server"],
        "priority": "high",
        "budgetLines": [{"expenseClass": "Capital", "category": "Equipment", "particular": "Network switch", "amount": 25000.0}],
        "dependencies": [],
    },
    {
        "title": "Develop procurement plan",
        "description": "Prepare bidding documents and BAC resolution for equipment purchase.",
        "estimatedDuration": "3 days",
        "requiredSkills": ["project planning", "documentation", "budget"],
        "priority": "medium",
        "budgetLines": [{"expenseClass": "MOOE", "category": "Professional Services", "particular": "Consultant fee", "amount": 10000.0}],
        "dependencies": [],
    },
    {
        "title": "Financial liquidation report",
        "description": "Prepare financial liquidation and settlement for all disbursements.",
        "estimatedDuration": "2 days",
        "requiredSkills": ["financial analysis", "reporting", "compliance"],
        "priority": "high",
        "budgetLines": [],
        "dependencies": [0, 1],
    },
]


class TestSkillOverlap(unittest.TestCase):
    def test_high_match(self):
        score = _calculate_skill_overlap(
            ["network", "server"], "network infrastructure",
            ["network", "server", "database"], ["system analysis"]
        )
        self.assertGreaterEqual(score, 70.0)

    def test_low_match(self):
        score = _calculate_skill_overlap(
            ["financial analysis", "compliance"], "liquidation report",
            ["software development", "coding"], []
        )
        self.assertLess(score, 70.0)

    def test_score_bounded(self):
        score = _calculate_skill_overlap(
            ["network", "server", "vlan", "firewall", "database", "cloud"],
            "network infrastructure setup",
            ["network", "server", "vlan", "firewall", "database", "cloud", "it", "digital"],
            ["problem solving", "system analysis"],
        )
        self.assertLessEqual(score, 100.0)
        self.assertGreaterEqual(score, 0.0)


class TestWeaknessPenalty(unittest.TestCase):
    def test_no_overlap(self):
        penalty = _calculate_weakness_penalty("financial liquidation report", ["coding", "software"])
        self.assertEqual(penalty, 0.0)

    def test_overlap_penalized(self):
        penalty = _calculate_weakness_penalty(
            "technical systems configuration and coding",
            ["coding", "technical systems"]
        )
        self.assertGreater(penalty, 0.0)

    def test_penalty_bounded(self):
        penalty = _calculate_weakness_penalty(
            "coding software network firewall database technical systems",
            ["coding", "software", "network", "database", "technical"],
        )
        self.assertLessEqual(penalty, 100.0)


class TestProposalOptimizerInit(unittest.TestCase):
    def test_init_parses_durations(self):
        opt = ProposalOptimizer(SAMPLE_TASKS, SAMPLE_EMPLOYEES, "balanced")
        self.assertEqual(opt.durations, [5, 3, 2])
        self.assertEqual(len(opt.dependencies[2]), 2)   # task 3 depends on 0 and 1

    def test_profiles_exist(self):
        for name in ["balanced", "fast_track", "low_risk"]:
            self.assertIn(name, PROFILES)

    def test_invalid_profile_defaults_balanced(self):
        opt = ProposalOptimizer(SAMPLE_TASKS, SAMPLE_EMPLOYEES, "nonexistent")
        self.assertEqual(opt.profile.name, "balanced")


class TestOptimizationRun(unittest.TestCase):
    def test_basic_run_returns_result(self):
        result = run_proposal_optimization(
            tasks=SAMPLE_TASKS,
            employees=SAMPLE_EMPLOYEES,
            profile="balanced",
            num_generations=10,
        )
        self.assertIn("tasks", result)
        self.assertIn("fitness_score", result)
        self.assertIn("generation_history", result)
        self.assertIn("duration_ms", result)
        self.assertIn("metrics", result)
        self.assertEqual(len(result["tasks"]), len(SAMPLE_TASKS))

    def test_all_profiles_run(self):
        for profile in ["balanced", "fast_track", "low_risk"]:
            result = run_proposal_optimization(
                tasks=SAMPLE_TASKS,
                employees=SAMPLE_EMPLOYEES,
                profile=profile,
                num_generations=10,
            )
            self.assertEqual(result["profile_used"], profile)
            self.assertGreater(result["fitness_score"], 0.0)

    def test_tasks_get_assigned_employee(self):
        result = run_proposal_optimization(
            tasks=SAMPLE_TASKS,
            employees=SAMPLE_EMPLOYEES,
            profile="balanced",
            num_generations=10,
        )
        for task in result["tasks"]:
            self.assertIn("recommendedEmployeeIds", task)
            self.assertEqual(len(task["recommendedEmployeeIds"]), 1)
            self.assertIn("teamComposition", task)
            self.assertIn("optimizationMetadata", task)

    def test_fitness_bounded(self):
        result = run_proposal_optimization(
            tasks=SAMPLE_TASKS,
            employees=SAMPLE_EMPLOYEES,
            profile="balanced",
            num_generations=15,
        )
        self.assertLessEqual(result["fitness_score"], 100.0)
        self.assertGreaterEqual(result["fitness_score"], 0.0)

    def test_empty_tasks_returns_safe_result(self):
        result = run_proposal_optimization(
            tasks=[],
            employees=SAMPLE_EMPLOYEES,
            profile="balanced",
            num_generations=10,
        )
        self.assertEqual(result["tasks"], [])
        self.assertEqual(result["fitness_score"], 100.0)

    def test_budget_cap_enforced_metadata(self):
        result = run_proposal_optimization(
            tasks=SAMPLE_TASKS,
            employees=SAMPLE_EMPLOYEES,
            profile="low_risk",
            budget_cap=50000.0,
            num_generations=10,
        )
        # Result should still produce valid tasks regardless of cap
        self.assertEqual(len(result["tasks"]), 3)

    def test_generation_history_length(self):
        result = run_proposal_optimization(
            tasks=SAMPLE_TASKS,
            employees=SAMPLE_EMPLOYEES,
            profile="balanced",
            num_generations=20,
        )
        # One entry per generation
        self.assertEqual(len(result["generation_history"]), 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
