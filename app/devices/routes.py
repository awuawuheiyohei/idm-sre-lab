"""
Devices Provisioning endpoints（Week 9-10：克诺尔 BU 场景）：
- POST /devices — 注册新设备
- GET /devices — 列表（user_id / status / business_unit / device_type 过滤）
- GET /devices/{id} — 查询
- POST /devices/{id}/activate — REGISTERED → ACTIVE
- POST /devices/{id}/retire — → RETIRED
- POST /devices/{id}/mark-lost — → LOST
- POST /devices/{id}/compliance — 更新合规状态
- POST /devices/{id}/check-in — 更新 last_check_in
- GET /devices/portfolio/stats — BU 设备画像
- GET /devices/audit — 设备生命周期事件
"""
from urllib.parse import parse_qs
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Query

from ..db import get_conn
from .device_core import (
    register_device, activate_device, retire_device, mark_lost,
    update_compliance, check_in_device,
    get_device, list_devices, device_portfolio_stats,
    rows_to_dicts,
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
# Register device
# ============================================
@router.post("/devices")
async def register(request: Request):
    body = await _parse_form(request)
    required = ["device_name", "user_id", "device_type", "os", "serial_number"]
    for f in required:
        if not body.get(f):
            raise HTTPException(400, f"Missing required field: {f}")

    try:
        device = register_device(
            device_name=body["device_name"],
            user_id=body["user_id"],
            device_type=body["device_type"],
            os=body["os"],
            serial_number=body["serial_number"],
            manufacturer=body.get("manufacturer"),
            model=body.get("model"),
            business_unit=body.get("business_unit", "platform"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"status": "registered", "device": device}


# ============================================
# List devices
# ============================================
@router.get("/devices")
async def list_dev(
    user_id: str = Query(None),
    status: str = Query(None),
    business_unit: str = Query(None),
    device_type: str = Query(None),
):
    items = list_devices(user_id=user_id, status=status,
                          business_unit=business_unit, device_type=device_type)
    return {"count": len(items), "items": items}


# ============================================
# Portfolio stats
# ============================================
@router.get("/devices/portfolio/stats")
async def portfolio():
    return device_portfolio_stats()


# ============================================
# Get device
# ============================================
@router.get("/devices/{device_id}")
async def get_one_device(device_id: str):
    d = get_device(device_id)
    if not d:
        raise HTTPException(404, f"Device not found: {device_id}")
    return d


# ============================================
# Lifecycle transitions
# ============================================
@router.post("/devices/{device_id}/activate")
async def activate(device_id: str):
    try:
        d = activate_device(device_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "activated", "device": d}


@router.post("/devices/{device_id}/retire")
async def retire(device_id: str, request: Request):
    body = await _parse_form(request)
    reason = body.get("reason", "manual_retire")
    try:
        d = retire_device(device_id, reason=reason)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "retired", "device": d}


@router.post("/devices/{device_id}/mark-lost")
async def mark_lost_endpoint(device_id: str):
    try:
        d = mark_lost(device_id)
    except Exception:
        raise HTTPException(400, "Failed to mark lost")
    return {"status": "marked_lost", "device": d}


@router.post("/devices/{device_id}/compliance")
async def compliance(device_id: str, request: Request):
    body = await _parse_form(request)
    state = body.get("compliance_state", "")
    if not state:
        raise HTTPException(400, "Missing compliance_state")
    try:
        d = update_compliance(device_id, state)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "compliance_updated", "device": d}


@router.post("/devices/{device_id}/check-in")
async def check_in(device_id: str):
    d = check_in_device(device_id)
    if not d:
        raise HTTPException(404, f"Device not found: {device_id}")
    return {"status": "checked_in", "last_check_in": d["last_check_in"]}


# ============================================
# Audit (path declared BEFORE /devices/{device_id} to avoid conflict)
# ============================================
@router.get("/devices-audit")
async def audit(limit: int = Query(50, ge=1, le=500)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM device_audit ORDER BY occurred_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return {"count": len(rows), "items": rows_to_dicts(rows)}