"""PyGAD Multi-Objective Genetic Algorithm Optimizer for eFlow Proposals.

Solves the Resource-Constrained Project Scheduling Problem (RCPSP),
Pareto-optimal personnel assignment, and budget knapsack optimization
for municipal governance proposals.

Profiles supported:
- 'balanced'   : Harmonizes skill suitability, workload variance, and risk
- 'fast_track' : Prioritizes minimal makespan and parallel critical-path execution
- 'low_risk'   : Heavily penalizes employee weaknesses and burnout thresholds
"""

import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("eflow.pygad")


def _as_number(value: Any, default: float = 0.0) -> float:
    """Parse model-produced numeric values, including Philippine-formatted money."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else default

    normalized = str(value).strip().replace(",", "")
    # DeepSeek may emit values such as "PHP 105,000.00" or "₱105,000.00".
    normalized = re.sub(r"[^0-9.\-]", "", normalized)
    if not normalized or normalized in {"-", ".", "-."}:
        return default
    try:
        number = float(normalized)
    except ValueError:
        return default
    return number if math.isfinite(number) else default


@dataclass
class OptimizationProfile:
    name: str
    weight_skill: float
    weight_workload: float
    weight_risk: float
    weight_schedule: float
    weight_budget: float


PROFILES: Dict[str, OptimizationProfile] = {
    "balanced": OptimizationProfile(
        name="balanced",
        weight_skill=0.35,
        weight_workload=0.25,
        weight_risk=0.20,
        weight_schedule=0.15,
        weight_budget=0.05,
    ),
    "fast_track": OptimizationProfile(
        name="fast_track",
        weight_skill=0.30,
        weight_workload=0.10,
        weight_risk=0.10,
        weight_schedule=0.45,
        weight_budget=0.05,
    ),
    "low_risk": OptimizationProfile(
        name="low_risk",
        weight_skill=0.25,
        weight_workload=0.30,
        weight_risk=0.35,
        weight_schedule=0.05,
        weight_budget=0.05,
    ),
}


def _calculate_skill_overlap(
    task_skills: List[str],
    task_title: str,
    emp_skills: List[str],
    emp_strengths: List[str],
) -> float:
    """Computes a 0.0 - 100.0 score of employee skill alignment with task requirements."""
    emp_tokens = {
        s.lower().strip()
        for s in (emp_skills + emp_strengths)
        if s and isinstance(s, str)
    }
    
    score = 40.0  # Baseline baseline match
    
    # Direct skill keyword matches
    for req in task_skills:
        req_norm = req.lower().strip()
        if any(req_norm in et or et in req_norm for et in emp_tokens):
            score += 20.0
            
    # Title keyword context match
    title_words = set(re_split(task_title.lower()))
    for token in emp_tokens:
        token_words = set(re_split(token))
        if token_words & title_words:
            score += 10.0
            
    return min(100.0, score)


def re_split(text: str) -> List[str]:
    import re
    return [w for w in re.split(r"[\s\-_,./()]+", text) if len(w) > 2]


def _calculate_weakness_penalty(
    task_desc: str,
    emp_weaknesses: List[str],
) -> float:
    """Computes penalty (0.0 - 100.0) if employee weakness intersects task demands."""
    if not emp_weaknesses:
        return 0.0
    desc_words = set(re_split(task_desc.lower()))
    penalty = 0.0
    for w in emp_weaknesses:
        w_words = set(re_split(w.lower()))
        if w_words & desc_words:
            penalty += 25.0
    return min(100.0, penalty)


class ProposalOptimizer:
    """Genetic Algorithm Optimizer for eFlow Proposal Workflows."""

    def __init__(
        self,
        tasks: List[Dict[str, Any]],
        employees: List[Dict[str, Any]],
        profile: str = "balanced",
        budget_cap: Optional[float] = None,
    ):
        self.raw_tasks = tasks
        self.employees = employees
        self.profile = PROFILES.get(profile, PROFILES["balanced"])
        self.num_tasks = len(tasks)
        self.num_employees = len(employees)
        self.budget_cap = budget_cap

        # Precompute task dependencies and durations
        self.durations = []
        self.estimated_hours = []
        self.dependencies: List[List[int]] = []
        self.base_budgets = []

        for idx, t in enumerate(tasks):
            # Parse duration in days (default 3)
            dur_str = str(t.get("estimatedDuration") or t.get("duration_days") or "3")
            from duration_parser import duration_days
            dur = duration_days(dur_str)
            self.durations.append(max(1, dur))
            
            # Hours
            hrs = t.get("estimated_hours") or (dur * 8)
            self.estimated_hours.append(_as_number(hrs, float(dur * 8)))
            
            # Dependencies: parent_index or dependencies list
            deps = t.get("dependencies") or []
            if not deps and "parent_index" in t and t["parent_index"] is not None:
                deps = [t["parent_index"]]
            # Filter valid predecessors
            valid_deps = [d for d in deps if isinstance(d, int) and 0 <= d < idx]
            self.dependencies.append(valid_deps)
            
            # Budget
            blines = t.get("budgetLines") or []
            b_amt = (
                sum(_as_number(b.get("amount")) for b in blines)
                if blines
                else _as_number(t.get("budget"))
            )
            self.base_budgets.append(b_amt)

    def _fitness_function(self, ga_instance: Any, solution: np.ndarray, solution_idx: int) -> float:
        """Multi-objective fitness evaluation.
        
        Chromosome layout:
        [0 .. N-1]     : Employee index assigned as lead for task i (integer 0..M-1)
        [N .. 2N-1]    : Scheduling priority rank for task i (integer 1..100)
        [2N .. 3N-1]   : Budget allocation modifier percentage (integer 80..120)
        """
        N = self.num_tasks
        M = self.num_employees

        if M == 0 or N == 0:
            return 100.0

        emp_assignments = [int(solution[i]) % M for i in range(N)]
        sched_priorities = [int(solution[N + i]) for i in range(N)]
        budget_factors = [int(solution[2 * N + i]) / 100.0 for i in range(N)]

        # 1. Skill Match Score (Higher is better)
        skill_scores = []
        for i in range(N):
            emp = self.employees[emp_assignments[i]]
            req_skills = self.raw_tasks[i].get("requiredSkills") or []
            title = self.raw_tasks[i].get("title", "")
            emp_skills = emp.get("skills", [])
            emp_strengths = emp.get("strengths", [])
            score = _calculate_skill_overlap(req_skills, title, emp_skills, emp_strengths)
            skill_scores.append(score)
        mean_skill = float(np.mean(skill_scores)) if skill_scores else 50.0

        # 2. Workload Variance (Lower is better)
        emp_hours = [_as_number(emp.get("workload")) for emp in self.employees]
        for i in range(N):
            emp_idx = emp_assignments[i]
            emp_hours[emp_idx] += self.estimated_hours[i]
        
        workload_std = float(np.std(emp_hours))
        # Normalize workload penalty: 0 std -> 0 penalty; 40+ std -> 100 penalty
        workload_score = max(0.0, 100.0 - min(100.0, workload_std * 2.5))

        # 3. Risk & Weakness Penalties (Lower is better)
        risk_penalties = []
        lead_counts = [0] * M
        for i in range(N):
            emp_idx = emp_assignments[i]
            lead_counts[emp_idx] += 1
            emp = self.employees[emp_idx]
            desc = (self.raw_tasks[i].get("description") or "") + " " + (self.raw_tasks[i].get("title") or "")
            weakness_pen = _calculate_weakness_penalty(desc, emp.get("weaknesses", []))
            
            # Burnout risk penalty if total hours > 60
            burnout_pen = 30.0 if emp_hours[emp_idx] > 60 else 0.0
            risk_penalties.append(weakness_pen + burnout_pen)
        
        # Consecutive lead monopoly penalty
        monopoly_penalty = sum(max(0, count - max(2, int(N / max(1, M) * 1.5))) * 20.0 for count in lead_counts)
        mean_risk = float(np.mean(risk_penalties)) if risk_penalties else 0.0
        risk_score = max(0.0, 100.0 - min(100.0, mean_risk + (monopoly_penalty / max(1, N))))

        # 4. RCPSP Scheduling Makespan (Shorter is better, dependency valid)
        # Topological forward schedule with resource conflict resolution
        task_end_days = [0] * N
        emp_available_day = [0] * M

        # Process in topological order respecting dependencies and priority
        # Since tasks are naturally roughly ordered, we simulate forward days
        for i in range(N):
            # Must start after all predecessors finish
            dep_finish = max([task_end_days[p] for p in self.dependencies[i]], default=0)
            emp_idx = emp_assignments[i]
            res_avail = emp_available_day[emp_idx]
            start_day = max(dep_finish, res_avail)
            end_day = start_day + self.durations[i]
            task_end_days[i] = end_day
            emp_available_day[emp_idx] = end_day

        makespan = max(task_end_days) if task_end_days else 1
        # Target makespan baseline is sum(durations) / 2
        ideal_makespan = max(1, sum(self.durations) / max(1, min(M, 3)))
        schedule_ratio = makespan / ideal_makespan
        # Score: 100 if at ideal or below, decreasing as makespan increases
        schedule_score = max(0.0, 100.0 - max(0.0, (schedule_ratio - 1.0) * 50.0))

        # 5. Budget Knapsack Compliance
        total_budget = sum(self.base_budgets[i] * budget_factors[i] for i in range(N))
        budget_score = 100.0
        if self.budget_cap and self.budget_cap > 0:
            if total_budget > self.budget_cap:
                overage = (total_budget - self.budget_cap) / self.budget_cap
                budget_score = max(0.0, 100.0 - (overage * 200.0))

        # Weighted aggregate fitness
        fitness = (
            self.profile.weight_skill * mean_skill
            + self.profile.weight_workload * workload_score
            + self.profile.weight_risk * risk_score
            + self.profile.weight_schedule * schedule_score
            + self.profile.weight_budget * budget_score
        )

        return float(fitness)

    def optimize(
        self,
        num_generations: int = 40,
        sol_per_pop: int = 24,
        num_parents_mating: int = 8,
    ) -> Dict[str, Any]:
        """Runs the PyGAD genetic algorithm and returns optimized assignments and schedule."""
        import pygad

        start_time = time.time()
        N = self.num_tasks
        M = self.num_employees

        if N == 0 or M == 0:
            return {
                "tasks": self.raw_tasks,
                "fitness_score": 100.0,
                "generation_history": [100.0],
                "duration_ms": int((time.time() - start_time) * 1000),
                "profile_used": self.profile.name,
                "metrics": {
                    "skill_match_score": 100.0,
                    "workload_variance": 0.0,
                    "risk_score": 100.0,
                    "makespan_days": 1,
                },
            }

        num_genes = 3 * N
        gene_space = []
        # Employee indices: 0 .. M-1
        for _ in range(N):
            gene_space.append(list(range(M)))
        # Scheduling priority: 1 .. 100
        for _ in range(N):
            gene_space.append(list(range(1, 101)))
        # Source proposal budgets are immutable during decomposition. Keep the
        # budget gene at 100 so PyGAD evaluates compliance without rewriting
        # figures extracted from the approved source document.
        for _ in range(N):
            gene_space.append([100])

        generation_history: List[float] = []

        def on_gen(ga: Any):
            best_fit = float(ga.best_solution()[1])
            generation_history.append(round(best_fit, 2))

        ga_instance = pygad.GA(
            num_generations=num_generations,
            num_parents_mating=num_parents_mating,
            fitness_func=self._fitness_function,
            sol_per_pop=sol_per_pop,
            num_genes=num_genes,
            gene_space=gene_space,
            gene_type=int,
            mutation_percent_genes=12,
            mutation_type="random",
            crossover_type="single_point",
            on_generation=on_gen,
            suppress_warnings=True,
        )

        ga_instance.run()

        best_sol, best_fit, _ = ga_instance.best_solution()

        # Decode best solution
        emp_assignments = [int(best_sol[i]) % M for i in range(N)]
        sched_priorities = [int(best_sol[N + i]) for i in range(N)]
        budget_factors = [int(best_sol[2 * N + i]) / 100.0 for i in range(N)]

        # Simulate final schedule with best chromosome
        task_end_days = [0] * N
        task_start_days = [0] * N
        emp_available_day = [0] * M
        emp_workload_tally = [_as_number(emp.get("workload")) for emp in self.employees]

        optimized_tasks = []
        for i in range(N):
            orig_task = dict(self.raw_tasks[i])
            emp_idx = emp_assignments[i]
            assigned_emp = self.employees[emp_idx]
            emp_id = str(assigned_emp.get("id", f"emp_{emp_idx}"))
            emp_name = str(assigned_emp.get("name", f"Employee {emp_idx}"))

            dep_finish = max([task_end_days[p] for p in self.dependencies[i]], default=0)
            res_avail = emp_available_day[emp_idx]
            start_day = max(dep_finish, res_avail)
            end_day = start_day + self.durations[i]

            task_start_days[i] = start_day
            task_end_days[i] = end_day
            emp_available_day[emp_idx] = end_day
            emp_workload_tally[emp_idx] += self.estimated_hours[i]

            # Keep valid LAYA support recommendations first, then fill any
            # remaining support slots using skill fit and projected workload.
            existing_ids = [
                str(item) for item in orig_task.get("recommendedEmployeeIds", [])
                if str(item) != emp_id
            ]
            valid_employee_ids = {
                str(employee.get("id")) for employee in self.employees
            }
            support_candidates = [
                item for item in existing_ids if item in valid_employee_ids
            ]
            ranked_support = sorted(
                (k for k in range(M) if k != emp_idx),
                key=lambda k: (
                    -_calculate_skill_overlap(
                        orig_task.get("requiredSkills") or [],
                        orig_task.get("title", ""),
                        self.employees[k].get("skills", []),
                        self.employees[k].get("strengths", []),
                    ),
                    emp_workload_tally[k],
                ),
            )
            for candidate_idx in ranked_support:
                candidate_id = str(self.employees[candidate_idx].get("id"))
                if candidate_id not in support_candidates:
                    support_candidates.append(candidate_id)
                if len(support_candidates) >= 2:
                    break
            support_candidates = support_candidates[:2]
            orig_task["recommendedEmployeeIds"] = [emp_id, *support_candidates]

            # Construct structured team composition compatible with EflowWeb schema
            orig_task["teamComposition"] = {
                "mode": "team" if support_candidates else "solo",
                "selectedCount": 1 + len(support_candidates),
                "eligibleCount": M,
                "rationale": (
                    f"GA Optimized ({self.profile.name}): {emp_name} assigned as technical lead "
                    f"based on Pareto fitness {round(best_fit, 1)}."
                ),
                "memberReasons": [
                    {
                        "employeeId": emp_id,
                        "employeeName": emp_name,
                        "role": "lead",
                        "contribution": "Lead implementer matching required technical domain skills.",
                    }
                ]
                + [
                    {
                        "employeeId": sid,
                        "employeeName": next(
                            (e.get("name", "") for e in self.employees if str(e.get("id")) == sid),
                            "Support Member",
                        ),
                        "role": "support",
                        "contribution": "Cross-functional support and load balancing.",
                    }
                    for sid in support_candidates
                ],
            }

            # Update schedule and budget
            orig_task["estimatedDuration"] = f"{self.durations[i]} days"
            orig_task["optimizationMetadata"] = {
                "scheduledStartDay": start_day,
                "scheduledEndDay": end_day,
                "durationDays": self.durations[i],
                "budgetMultiplier": 1.0,
                "profile": self.profile.name,
                "pipelineStages": ["deepseek-r1:8b", "laya", "pygad"],
            }

            laya_reason = str(orig_task.get("recommendationReasoning") or "").strip()
            pygad_reason = (
                f"PyGAD selected {emp_name} as lead using the {self.profile.name} "
                f"profile at fitness {round(best_fit, 1)} and scheduled this task "
                f"for day {start_day} through day {end_day}."
            )
            orig_task["recommendationReasoning"] = " ".join(
                item for item in [laya_reason, pygad_reason] if item
            )
            orig_task["recommendationSource"] = "pygad"
            orig_task["burnoutWarning"] = bool(emp_workload_tally[emp_idx] > 55)

            optimized_tasks.append(orig_task)

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"[PyGAD] Completed optimization in {duration_ms}ms over {len(generation_history)} generations. "
            f"Best fitness: {round(best_fit, 2)}"
        )

        return {
            "tasks": optimized_tasks,
            "fitness_score": round(float(best_fit), 2),
            "generation_history": generation_history,
            "duration_ms": duration_ms,
            "profile_used": self.profile.name,
            "metrics": {
                "skill_match_score": round(float(np.mean([
                    _calculate_skill_overlap(
                        t.get("requiredSkills") or [],
                        t.get("title", ""),
                        self.employees[emp_assignments[i]].get("skills", []),
                        self.employees[emp_assignments[i]].get("strengths", []),
                    )
                    for i, t in enumerate(self.raw_tasks)
                ])), 1),
                "workload_variance": round(float(np.var(emp_workload_tally)), 2),
                "makespan_days": max(task_end_days) if task_end_days else 1,
                "total_budget": round(sum(
                    self.base_budgets[i] * budget_factors[i] for i in range(N)
                ), 2),
            },
        }


def run_proposal_optimization(
    tasks: List[Dict[str, Any]],
    employees: List[Dict[str, Any]],
    profile: str = "balanced",
    budget_cap: Optional[float] = None,
    num_generations: int = 40,
) -> Dict[str, Any]:
    """Convenience entry point for optimizing proposal task assignments."""
    optimizer = ProposalOptimizer(
        tasks=tasks,
        employees=employees,
        profile=profile,
        budget_cap=budget_cap,
    )
    return optimizer.optimize(num_generations=num_generations)
