"""
SLO endpoints (Week 17-18):
- GET /slo — list all 4 core SLOs with definitions
- GET /slo/{id}/status — current SLO status
- GET /slo/report — full SLO report
"""
from fastapi import APIRouter, Query, HTTPException

from .calculator import SLO_DEFINITIONS, compute_slo_status, generate_slo_report
from ..observability.metrics import golden_signals_summary

router = APIRouter()


@router.get("/slo")
async def list_slos():
    """所有 4 个核心 SLO 定义"""
    return {"count": len(SLO_DEFINITIONS), "slos": SLO_DEFINITIONS}


@router.get("/slo/report")
async def slo_report(elapsed_days: float = Query(15.0, ge=0),
                      window_days: float = Query(30.0, ge=1)):
    """完整 SLO 报告"""
    summary = golden_signals_summary()
    total = summary["total_requests"]
    errors = summary["total_errors"]
    return generate_slo_report(
        elapsed_days=elapsed_days,
        window_days=window_days,
        total_requests=total,
        errors=errors,
    )


@router.get("/slo/{slo_id}/status")
async def slo_status(slo_id: str,
                      elapsed_days: float = Query(15.0, ge=0),
                      window_days: float = Query(30.0, ge=1)):
    """单个 SLO 当前状态"""
    summary = golden_signals_summary()
    total = summary["total_requests"]
    errors = summary["total_errors"]
    try:
        return compute_slo_status(
            slo_id, total_requests=total, errors=errors,
            elapsed_days=elapsed_days, window_days=window_days,
        )
    except ValueError:
        raise HTTPException(404, f"Unknown SLO: {slo_id}")