"""
Chaos Engineering endpoints (Week 19-20):
- POST /chaos/experiments — create new experiment
- POST /chaos/experiments/{id}/run — start experiment (async)
- GET /chaos/experiments/{id} — get experiment status + verdict
- GET /chaos/experiments — list experiments
- GET /chaos/types — list available experiment types
"""
import asyncio
import threading
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request

from ..db import get_conn
from .runner import (
    create_experiment, finish_experiment, run_experiment, run_experiment_async,
    get_experiment, list_experiments, EXPERIMENT_TYPES,
    evaluate_hypothesis, snapshot_metrics,
)

router = APIRouter()


async def _parse_form(request: Request) -> dict:
    body = await request.body()
    if not body:
        return {}
    try:
        return {k: v[0] for k, v in parse_qs(body.decode("utf-8")).items()}
    except Exception:
        try:
            return await request.json()
        except Exception:
            return {}


@router.get("/chaos/types")
async def list_types():
    """可用的 chaos 实验类型"""
    return {
        "count": len(EXPERIMENT_TYPES),
        "types": [
            {"type": "pod_kill", "description": "Kill target service process for N seconds"},
            {"type": "network_partition", "description": "Block 50% traffic + simulate timeout"},
            {"type": "latency_injection", "description": "Inject latency spike into target service"},
        ],
    }


@router.post("/chaos/experiments")
async def create(request: Request):
    """创建 chaos experiment"""
    body = await _parse_form(request)
    exp_type = body.get("experiment_type", "")
    target = body.get("target_service", "")
    duration = int(body.get("duration_seconds", "5"))
    hypothesis = body.get("hypothesis", "service should remain stable")
    notes = body.get("notes", "")

    if exp_type not in EXPERIMENT_TYPES:
        raise HTTPException(400, f"Invalid experiment_type. Must be one of {list(EXPERIMENT_TYPES)}")
    if not target:
        raise HTTPException(400, "Missing target_service")
    if duration < 1 or duration > 60:
        raise HTTPException(400, "duration_seconds must be 1-60")

    exp_id = create_experiment(exp_type, target, duration, hypothesis, notes)
    return {"experiment_id": exp_id, "status": "PENDING"}


@router.post("/chaos/experiments/{exp_id}/run")
async def run(exp_id: str):
    """同步执行 chaos experiment（blocking）"""
    try:
        result = run_experiment(exp_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


@router.get("/chaos/experiments/{exp_id}")
async def get_one(exp_id: str):
    """获取 experiment 详情（含 baseline/during/after metrics + verdict）"""
    d = get_experiment(exp_id)
    if not d:
        raise HTTPException(404, f"Experiment not found: {exp_id}")
    return d


@router.get("/chaos/experiments")
async def list_all(experiment_type: str = None, limit: int = 20):
    """列出所有 chaos experiment"""
    items = list_experiments(limit=limit, experiment_type=experiment_type)
    return {"count": len(items), "items": items}