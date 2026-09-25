"""
Incident Response endpoints (Week 21-22):
- GET /runbooks — 10 个常见事故 runbook
- GET /runbooks/{id} — 单个 runbook 详情
- GET /runbooks/recommend — 基于当前 metrics 推荐 runbook
- POST /incidents/simulate — 触发 mock incident
- GET /incidents — 列出 incidents
- GET /incidents/{id} — 单个 incident
- PATCH /incidents/{id} — 更新 status / mitigation / lessons_learned
- GET /incidents/active — 当前 active（on-call dashboard）
"""
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request

from ..db import get_conn
from ..observability.metrics import golden_signals_summary
from .runbook import list_runbooks, get_runbook_by_id, recommend_runbook
from .simulator import (
    INCIDENT_TYPES, SIMULATORS,
    create_incident, update_incident_status, get_incident,
    list_incidents, list_active_incidents, start_simulator,
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


# ============================================
# Runbooks
# ============================================
@router.get("/runbooks")
async def list_rb():
    """10 个常见事故 runbook"""
    return {"count": len(list_runbooks()), "runbooks": list_runbooks()}


# Static paths MUST be declared BEFORE /{rb_id} catch-all
@router.get("/runbooks/recommend")
async def recommend_rb():
    """基于当前实时 metrics 推荐 runbook"""
    summary = golden_signals_summary()
    rb = recommend_runbook(summary)
    if not rb:
        return {"recommended": None, "message": "All metrics within SLO"}
    return {"recommended": rb}


@router.get("/runbooks/{rb_id}")
async def get_rb(rb_id: str):
    rb = get_runbook_by_id(rb_id)
    if not rb:
        raise HTTPException(404, f"Runbook not found: {rb_id}")
    return rb


# ============================================
# Incidents
# ============================================
@router.get("/incidents/types")
async def list_incident_types():
    """可用的 incident 类型"""
    return {"count": len(INCIDENT_TYPES), "types": INCIDENT_TYPES}


@router.post("/incidents/simulate")
async def simulate(request: Request):
    """触发 mock incident（async）"""
    body = await _parse_form(request)
    inc_type = body.get("incident_type", "")
    duration = int(body.get("duration_seconds", "10"))
    if inc_type not in SIMULATORS:
        raise HTTPException(400, f"Unknown incident_type. Must be one of {list(SIMULATORS)}")
    if duration < 1 or duration > 120:
        raise HTTPException(400, "duration_seconds must be 1-120")
    inc_id = start_simulator(inc_type, duration)
    return {"incident_id": inc_id, "status": "ACTIVE",
            "incident_type": inc_type, "duration_seconds": duration}


@router.post("/incidents")
async def create(request: Request):
    """手工创建 incident（不触发 simulator）"""
    body = await _parse_form(request)
    inc_type = body.get("incident_type", "")
    sev = body.get("severity", "SEV-3")
    title = body.get("title", "")
    description = body.get("description", "")
    if not inc_type or not title:
        raise HTTPException(400, "Missing incident_type or title")
    inc_id = create_incident(inc_type, severity=sev, title=title,
                              description=description)
    return {"incident_id": inc_id, "status": "ACTIVE"}


@router.patch("/incidents/{inc_id}")
async def update(inc_id: str, request: Request):
    """更新 incident status / mitigation / lessons_learned"""
    body = await _parse_form(request)
    status = body.get("status", "")
    mitigation = body.get("mitigation", "")
    lessons = body.get("lessons_learned", "")
    if not status:
        raise HTTPException(400, "Missing status")
    try:
        d = update_incident_status(inc_id, status,
                                     mitigation=mitigation or None,
                                     lessons_learned=lessons or None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not d:
        raise HTTPException(404, f"Incident not found: {inc_id}")
    return d


@router.get("/incidents/active")
async def active_incidents():
    """当前 active incidents（on-call dashboard）"""
    items = list_active_incidents()
    return {"count": len(items), "items": items}


@router.get("/incidents/{inc_id}")
async def get_one(inc_id: str):
    d = get_incident(inc_id)
    if not d:
        raise HTTPException(404, f"Incident not found: {inc_id}")
    return d


@router.get("/incidents")
async def list_all(status: str = None, limit: int = 20):
    items = list_incidents(status=status, limit=limit)
    return {"count": len(items), "items": items}