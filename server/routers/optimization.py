"""FastAPI router for PyGAD Genetic Algorithm optimization endpoints.

Mounted under /controlpanelEflow/api/optimization/ by main.py.

Endpoints:
  POST /optimize-proposal   — Run RCPSP + multi-objective GA on proposal tasks
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("eflow.routers.optimization")

router = APIRouter(prefix="/api/optimization", tags=["optimization"])


# ── Request / Response Models ─────────────────────────────────────────────────


class EmployeeInput(BaseModel):
    id: str
    name: str
    role: str = ""
    workload: int = 0
    skills: List[str] = Field(default_factory=list)
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)


class BudgetLineInput(BaseModel):
    expenseClass: str = ""
    category: str = ""
    particular: str = ""
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unitCost: Optional[float] = None
    amount: float = 0
    fundSource: Optional[str] = None


class TaskInput(BaseModel):
    title: str
    description: str = ""
    estimatedDuration: Optional[str] = None
    requiredSkills: List[str] = Field(default_factory=list)
    priority: Optional[str] = None
    budgetLines: List[BudgetLineInput] = Field(default_factory=list)
    subtasks: List[str] = Field(default_factory=list)
    dependencies: List[int] = Field(default_factory=list)
    parent_index: Optional[int] = None


class OptimizeProposalRequest(BaseModel):
    tasks: List[TaskInput]
    employees: List[EmployeeInput]
    profile: str = "balanced"   # "balanced" | "fast_track" | "low_risk"
    budget_cap: Optional[float] = None
    num_generations: int = Field(default=40, ge=10, le=200)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/optimize-proposal")
async def optimize_proposal(body: OptimizeProposalRequest) -> JSONResponse:
    """
    Run PyGAD multi-objective Genetic Algorithm optimization on a list of
    proposal tasks with assigned employees.

    Solves:
    - RCPSP (Resource-Constrained Project Scheduling Problem)
    - Skill-match maximization per task
    - Workload variance minimization across employees
    - Weakness / burnout risk minimization
    - Budget knapsack compliance

    Returns optimized task assignments, schedule, fitness score, and metrics.
    """
    if not body.tasks:
        raise HTTPException(status_code=400, detail="tasks list is empty")
    if not body.employees:
        raise HTTPException(status_code=400, detail="employees list is empty")

    valid_profiles = {"balanced", "fast_track", "low_risk"}
    if body.profile not in valid_profiles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid profile '{body.profile}'. Must be one of: {sorted(valid_profiles)}",
        )

    try:
        from pygad_optimizer import run_proposal_optimization

        tasks_dicts = [t.model_dump() for t in body.tasks]
        employees_dicts = [e.model_dump() for e in body.employees]

        result = run_proposal_optimization(
            tasks=tasks_dicts,
            employees=employees_dicts,
            profile=body.profile,
            budget_cap=body.budget_cap,
            num_generations=body.num_generations,
        )

        return JSONResponse(content=result)

    except ImportError as exc:
        logger.error(f"[Optimization] pygad not installed: {exc}")
        raise HTTPException(
            status_code=503,
            detail="PyGAD optimizer is not available. Run: pip install pygad",
        )
    except Exception as exc:
        logger.exception(f"[Optimization] Optimization failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Optimization error: {str(exc)}")
