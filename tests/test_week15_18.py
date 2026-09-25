"""
IdM SRE Lab - Week 15-18 (Logs + Alerts + SLI/SLO) tests
- Structured JSON logging + query
- Alert rules engine
- 4 SLOs + burn rate calculation
"""
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.logs.structured_logging import (
    JSONLogFormatter, setup_logging, query_logs, get_log_stats, _log_buffer
)
from app.logs.alerts import (
    ALERT_RULES, evaluate_alerts, list_all_alerts, reset_alert_state,
)
from app.slo.calculator import (
    SLO_DEFINITIONS, compute_slo_status, generate_slo_report,
)


# ============================================
# JSON Log Formatter
# ============================================
def test_json_log_formatter_basic():
    """JSON formatter 输出 JSON 一行"""
    logger = logging.getLogger("test_json_formatter")
    logger.setLevel(logging.DEBUG)
    formatter = JSONLogFormatter()
    record = logger.makeRecord(
        "test_json_formatter", logging.INFO, "(test)", 1, "hello %s", ("world",), None
    )
    output = formatter.format(record)
    import json
    d = json.loads(output)
    assert d["level"] == "INFO"
    assert d["logger"] == "test_json_formatter"
    assert d["message"] == "hello world"
    assert "ts" in d


# ============================================
# Query logs
# ============================================
def test_query_logs_filters_by_level():
    """query_logs 按 level 过滤"""
    from app.logs.structured_logging import _buffer_lock
    with _buffer_lock:
        _log_buffer.clear()
    test_logger = logging.getLogger("test_query_level")
    test_logger.setLevel(logging.DEBUG)
    test_logger.info("info message")
    test_logger.warning("warn message")
    test_logger.error("error message")

    all_logs = query_logs(limit=100, since_seconds=60)
    assert len(all_logs) >= 3

    info_logs = query_logs(level="INFO", limit=100, since_seconds=60)
    for log in info_logs:
        assert log["level"] == "INFO"

    error_logs = query_logs(level="ERROR", limit=100, since_seconds=60)
    for log in error_logs:
        assert log["level"] == "ERROR"


def test_query_logs_filters_by_logger():
    from app.logs.structured_logging import _buffer_lock
    with _buffer_lock:
        _log_buffer.clear()
    logging.getLogger("logger_a").info("from A")
    logging.getLogger("logger_b").info("from B")
    a_logs = query_logs(logger="logger_a", limit=100, since_seconds=60)
    for log in a_logs:
        assert log["logger"] == "logger_a"


def test_get_log_stats():
    from app.logs.structured_logging import _buffer_lock
    with _buffer_lock:
        _log_buffer.clear()
    logging.getLogger("stats_test").info("info 1")
    logging.getLogger("stats_test").info("info 2")
    logging.getLogger("stats_test").warning("warn 1")
    stats = get_log_stats(since_seconds=60)
    assert stats["total_entries"] >= 3
    assert stats["by_level"].get("INFO", 0) >= 2
    assert stats["by_level"].get("WARNING", 0) >= 1
    assert "stats_test" in stats["by_logger"]


# ============================================
# Alert Rules
# ============================================
def test_alert_high_error_rate():
    reset_alert_state()
    metrics = {"total_requests": 100, "errors": 10, "error_rate_pct": 10.0,
               "uptime_minutes": 60, "latency_ms": {}}
    firing = evaluate_alerts(metrics)
    names = {a["name"] for a in firing}
    assert "HighErrorRate" in names


def test_alert_low_error_rate_no_firing():
    reset_alert_state()
    metrics = {"total_requests": 100, "errors": 1, "error_rate_pct": 1.0,
               "uptime_minutes": 60, "latency_ms": {}}
    firing = evaluate_alerts(metrics)
    names = {a["name"] for a in firing}
    assert "HighErrorRate" not in names


def test_alert_high_latency():
    reset_alert_state()
    metrics = {"total_requests": 100, "errors": 0, "error_rate_pct": 0,
               "uptime_minutes": 60, "latency_ms": {
                   "/oauth/token": {"p95": 1500}
               }}
    firing = evaluate_alerts(metrics)
    names = {a["name"] for a in firing}
    assert "HighLatencyP95" in names


def test_alert_low_traffic_warmup():
    """uptime < 5min 时不应 fire LowTraffic"""
    reset_alert_state()
    metrics = {"total_requests": 0, "errors": 0, "error_rate_pct": 0,
               "uptime_minutes": 1, "latency_ms": {}}
    firing = evaluate_alerts(metrics)
    names = {a["name"] for a in firing}
    assert "LowTraffic" not in names


def test_alert_low_traffic_post_warmup():
    reset_alert_state()
    metrics = {"total_requests": 0, "errors": 0, "error_rate_pct": 0,
               "uptime_minutes": 30, "latency_ms": {}}
    firing = evaluate_alerts(metrics, uptime_minutes=30)
    names = {a["name"] for a in firing}
    assert "LowTraffic" in names


def test_alert_state_transitions():
    """firing → not firing → resolved 状态记录"""
    reset_alert_state()
    # Fire
    metrics_high = {"total_requests": 100, "errors": 20,
                    "error_rate_pct": 20, "uptime_minutes": 60, "latency_ms": {}}
    firing1 = evaluate_alerts(metrics_high)
    assert any(a["name"] == "HighErrorRate" for a in firing1)

    # Resolve
    metrics_low = {"total_requests": 100, "errors": 0,
                   "error_rate_pct": 0, "uptime_minutes": 60, "latency_ms": {}}
    evaluate_alerts(metrics_low)
    # 不再 firing
    firing2 = evaluate_alerts(metrics_low)
    assert not any(a["name"] == "HighErrorRate" for a in firing2)
    # last_resolved_at 应该有
    all_alerts = list_all_alerts(metrics_low)
    resolved = [a for a in all_alerts if a["name"] == "HighErrorRate"][0]
    assert resolved["state"] == "ok"
    assert resolved.get("last_resolved_at") is not None


def test_list_all_alerts_returns_all_rules():
    """list_all_alerts 总是返回 4 个规则（无论 firing 与否）"""
    reset_alert_state()
    metrics = {"total_requests": 100, "errors": 0, "error_rate_pct": 0,
               "uptime_minutes": 60, "latency_ms": {}}
    all_alerts = list_all_alerts(metrics)
    assert len(all_alerts) == len(ALERT_RULES)


# ============================================
# SLI/SLO 计算
# ============================================
def test_slo_definitions_have_4():
    assert len(SLO_DEFINITIONS) == 4
    slo_ids = [s["id"] for s in SLO_DEFINITIONS]
    assert "availability" in slo_ids
    assert "token_p99_latency" in slo_ids
    assert "saml_p99_latency" in slo_ids
    assert "error_rate" in slo_ids


def test_slo_availability_met():
    """1000/0 = 100% availability 完全达标，remaining 100%"""
    s = compute_slo_status("availability", total_requests=1000, errors=0,
                            elapsed_days=15)
    assert s["objective_met"] is True
    assert s["status"] == "ok"
    assert s["budget_remaining_pct"] == 100.0


def test_slo_availability_meets_exactly():
    """1000/1 = 99.9% = target 边界（恰好达标）"""
    s = compute_slo_status("availability", total_requests=1000, errors=1,
                            elapsed_days=15)
    assert s["objective_met"] is True
    # remaining = 0 但仍然 met
    assert s["budget_remaining_pct"] == 0.0
    assert s["status"] in ("ok", "warning")


def test_slo_availability_violated():
    s = compute_slo_status("availability", total_requests=1000, errors=50,
                            elapsed_days=15)
    assert s["objective_met"] is False
    assert s["status"] in ("warning", "exhausted")


def test_slo_error_rate_exhausted():
    """error_rate > 1% 且 elapsed 比例已超出 budget"""
    s = compute_slo_status("error_rate", total_requests=100, errors=10,
                            elapsed_days=15)
    # 10% error rate > 1% threshold → violated
    assert s["objective_met"] is False


def test_slo_insufficient_data():
    s = compute_slo_status("availability", total_requests=0, errors=0,
                            elapsed_days=15)
    assert s["status"] == "insufficient_data"


def test_slo_unknown_raises():
    with pytest.raises(ValueError):
        compute_slo_status("nonexistent", total_requests=100, errors=0,
                            elapsed_days=15)


def test_generate_slo_report():
    report = generate_slo_report(elapsed_days=15, window_days=30,
                                   total_requests=1000, errors=5)
    assert "report_date" in report
    assert "slos" in report
    assert len(report["slos"]) == 4


# ============================================
# FastAPI endpoints
# ============================================
@pytest.fixture
def client():
    db = ROOT / "data" / "idm.db"
    for ext in ("", "-wal", "-shm"):
        p = Path(str(db) + ext)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    with TestClient(app) as c:
        r = c.post("/admin/seed")
        assert r.status_code == 200
        yield c


def test_endpoint_logs(client):
    r = client.get("/logs?limit=10")
    assert r.status_code == 200
    assert "count" in r.json()
    assert "items" in r.json()


def test_endpoint_logs_stats(client):
    r = client.get("/logs/stats")
    assert r.status_code == 200
    d = r.json()
    assert "total_entries" in d
    assert "by_level" in d


def test_endpoint_logs_levels(client):
    r = client.get("/logs/levels")
    assert r.status_code == 200
    assert "INFO" in r.json()["levels"]


def test_endpoint_alerts(client):
    r = client.get("/alerts")
    assert r.status_code == 200
    d = r.json()
    assert "count" in d
    assert "firing" in d


def test_endpoint_alerts_all(client):
    r = client.get("/alerts/all")
    assert r.status_code == 200
    assert r.json()["count"] == 4  # 4 个规则


def test_endpoint_slo_list(client):
    r = client.get("/slo")
    assert r.status_code == 200
    assert r.json()["count"] == 4


def test_endpoint_slo_report(client):
    r = client.get("/slo/report?elapsed_days=15")
    assert r.status_code == 200
    d = r.json()
    assert len(d["slos"]) == 4


def test_endpoint_slo_status(client):
    r = client.get("/slo/availability/status?elapsed_days=15")
    assert r.status_code == 200
    assert r.json()["id"] == "availability"


def test_endpoint_slo_status_404(client):
    r = client.get("/slo/nonexistent/status")
    assert r.status_code == 404