"""
GenAI Alert endpoints (Week 23-24):
- POST /ai-alerts/interpret — 解读 alert（调 LLM）
- GET /ai-alerts/log — 历史 alert 解释
- GET /ai-alerts/log/{id} — 单条 alert 解释
- GET /ai-alerts/prompt — 看 raw prompt（debug）
"""
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request

from .interpreter import (
    interpret_alert, list_ai_alerts, get_ai_alert, _build_user_prompt, SYSTEM_PROMPT,
)
from ..incidents.runbook import get_runbook_by_alert

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


@router.post("/ai-alerts/interpret")
async def interpret(request: Request):
    """调 LLM 解读 alert（自动关联 + 存 log）"""
    body = await _parse_form(request)
    alert_name = body.get("alert_name", "")
    if not alert_name:
        raise HTTPException(400, "Missing alert_name")

    metrics_str = body.get("metrics", "{}")
    try:
        metrics = __import__("json").loads(metrics_str) if isinstance(metrics_str, str) else metrics_str
    except Exception:
        metrics = {}
    severity = body.get("severity", "warning")
    triggered_at = body.get("triggered_at")
    duration_minutes = float(body.get("duration_minutes", "1.0"))

    # 关联 runbook
    runbook = get_runbook_by_alert(alert_name)

    try:
        interpretation = interpret_alert(
            alert_name=alert_name,
            metrics=metrics,
            runbook=runbook,
            severity=severity,
            triggered_at=triggered_at,
            duration_minutes=duration_minutes,
        )
    except Exception as e:
        raise HTTPException(500, f"LLM interpretation failed: {e}")

    return {
        "alert_name": alert_name,
        "severity": severity,
        "runbook_id": runbook["id"] if runbook else None,
        "interpretation": interpretation,
    }


@router.get("/ai-alerts/log")
async def log_list(alert_name: str = None, limit: int = 20):
    items = list_ai_alerts(alert_name=alert_name, limit=limit)
    return {"count": len(items), "items": items}


@router.get("/ai-alerts/log/{alert_log_id}")
async def log_one(alert_log_id: int):
    d = get_ai_alert(alert_log_id)
    if not d:
        raise HTTPException(404, f"Alert log not found: {alert_log_id}")
    return d


@router.get("/ai-alerts/prompt")
async def show_prompt():
    """看 system + user prompt 模板（debug 用）"""
    return {
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": "见 app/ai_alert/interpreter.py:_build_user_prompt",
        "model": "MiniMax-M3 (默认)",
        "constraints": [
                "ONLY use provided metrics (no invention)",
                "≤ 500 tokens output",
                "5 fixed sections (Summary/Hypotheses/Runbook/Verification/Mitigation)",
                "_strip_thinking 处理",
                "LLM 仅作建议（不 auto-execute）",
            ],
    }