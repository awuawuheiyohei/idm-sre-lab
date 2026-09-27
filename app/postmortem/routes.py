"""
Post-Mortem endpoints (Week 27-28):
- GET /pm-documents — list PM documents
- POST /pm-documents — create PM document
- GET /pm-documents/{id} — get PM document
- PATCH /pm-documents/{id} — update status (DRAFT → REVIEW → PUBLISHED)
- GET /pm-template — show postmortem template
"""
import json
from urllib.parse import parse_qs
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from .manager import create_pm, update_pm_status, get_pm, list_pms

router = APIRouter()

TEMPLATE_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "postmortem-template.md"


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


@router.get("/pm-template")
async def show_template():
    """Post-Mortem 模板（read-only）"""
    if not TEMPLATE_PATH.exists():
        raise HTTPException(404, "Postmortem template not found")
    return {
        "format": "markdown",
        "version": "v1.0",
        "content": TEMPLATE_PATH.read_text(encoding="utf-8"),
    }


@router.get("/pm-documents")
async def list_pm(status: str = None, severity: str = None, limit: int = 20):
    items = list_pms(status=status, severity=severity, limit=limit)
    return {"count": len(items), "items": items}


@router.post("/pm-documents")
async def create(request: Request):
    """创建 PM 文档（DRAFT 状态）"""
    body = await _parse_form(request)
    title = body.get("title", "")
    severity = body.get("severity", "SEV-3")
    if not title:
        raise HTTPException(400, "Missing title")
    if severity not in ("SEV-1", "SEV-2", "SEV-3"):
        raise HTTPException(400, "Invalid severity")

    incident_id = body.get("incident_id")
    summary = body.get("summary")
    root_cause = body.get("root_cause")
    impact = body.get("impact")
    what_went_well = body.get("what_went_well")
    what_went_wrong = body.get("what_went_wrong")
    blameless = body.get("blameless", "true").lower() not in ("false", "0", "")

    # timeline / action_items 可以是 JSON 字符串
    timeline_str = body.get("timeline", "[]")
    action_items_str = body.get("action_items", "[]")
    try:
        timeline = json.loads(timeline_str) if isinstance(timeline_str, str) else timeline_str
    except Exception:
        timeline = []
    try:
        action_items = json.loads(action_items_str) if isinstance(action_items_str, str) else action_items_str
    except Exception:
        action_items = []

    pm_id = create_pm(
        incident_id=incident_id, title=title, severity=severity,
        summary=summary, timeline=timeline, root_cause=root_cause,
        impact=impact, what_went_well=what_went_well,
        what_went_wrong=what_went_wrong, action_items=action_items,
        blameless=blameless,
    )
    return {"pm_id": pm_id, "status": "DRAFT"}


@router.get("/pm-documents/{pm_id}")
async def get_one(pm_id: str):
    d = get_pm(pm_id)
    if not d:
        raise HTTPException(404, f"PM not found: {pm_id}")
    return d


@router.patch("/pm-documents/{pm_id}")
async def update(pm_id: str, request: Request):
    """更新 status（DRAFT → REVIEW → PUBLISHED）"""
    body = await _parse_form(request)
    status = body.get("status", "")
    if not status:
        raise HTTPException(400, "Missing status")
    try:
        d = update_pm_status(pm_id, status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not d:
        raise HTTPException(404, f"PM not found: {pm_id}")
    return d