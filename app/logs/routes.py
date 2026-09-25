"""
Logging + Alerting endpoints (Week 15-16):
- GET /logs — query structured JSON logs (level/logger filter)
- GET /logs/stats — log level distribution
- GET /alerts — current firing alerts (Prometheus rule evaluation)
- GET /alerts/all — all rules with state
"""
from fastapi import APIRouter, Query

from .structured_logging import query_logs, get_log_stats
from .alerts import evaluate_alerts, list_all_alerts
from ..observability.metrics import golden_signals_summary

router = APIRouter()


@router.get("/logs")
async def list_logs(level: str = Query(None, description="Filter by level: INFO/WARNING/ERROR"),
                    logger: str = Query(None, description="Filter by logger name"),
                    limit: int = Query(100, ge=1, le=1000),
                    since_seconds: int = Query(3600, ge=60, le=86400)):
    """查询结构化 JSON 日志（Loki 风格）"""
    items = query_logs(level=level, logger=logger, limit=limit, since_seconds=since_seconds)
    return {"count": len(items), "items": items}


@router.get("/logs/stats")
async def logs_stats(since_seconds: int = Query(3600, ge=60, le=86400)):
    """日志 level + logger 分布"""
    return get_log_stats(since_seconds=since_seconds)


@router.get("/alerts")
async def list_alerts(uptime_minutes: float = Query(60.0, ge=0)):
    """当前 firing 的 alerts（基于实时 metrics 评估）"""
    summary = golden_signals_summary()
    firing = evaluate_alerts(summary, uptime_minutes=uptime_minutes)
    return {"count": len(firing), "firing": firing}


@router.get("/alerts/all")
async def list_all_alerts_endpoint(uptime_minutes: float = Query(60.0, ge=0)):
    """所有 alert rules（firing + ok）"""
    summary = golden_signals_summary()
    all_alerts = list_all_alerts(summary, uptime_minutes=uptime_minutes)
    return {
        "count": len(all_alerts),
        "rules": all_alerts,
    }


@router.get("/logs/levels")
async def logs_levels():
    """可用 level 列表（debug 用）"""
    return {"levels": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]}