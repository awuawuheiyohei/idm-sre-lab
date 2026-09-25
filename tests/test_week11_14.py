"""
IdM SRE Lab - Week 11-14 (Token Management + Observability) tests
- Token Introspection (RFC 7662)
- Metrics exposition (Prometheus format)
- 4 Golden Signals dashboard
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


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
        assert r.status_code == 200, r.text
        yield c


def _get_access_token(client, username="engineer01", password="Engineer@2026",
                       scope="openid profile email"):
    """helper: login + exchange → access_token"""
    r = client.post("/oauth/authorize", data={
        "username": username, "password": password,
        "client_id": "tripbiz-booking-app",
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "scope": scope,
    }, follow_redirects=False)
    code = r.headers["location"].split("code=", 1)[1].split("&")[0]
    r2 = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
    })
    return r2.json()["access_token"]


# ============================================
# Token Introspection (RFC 7662)
# ============================================
def test_introspect_active_token(client):
    token = _get_access_token(client)
    r = client.post("/oauth/introspect", data={
        "token": token,
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["active"] is True
    assert d["client_id"] == "tripbiz-booking-app"
    assert d["sub"] == "USER-001"
    assert d["token_type"] == "access"
    assert d["aud"] == "tripbiz-booking-app"
    assert "exp" in d and "iat" in d
    assert "scope" in d


def test_introspect_invalid_token(client):
    r = client.post("/oauth/introspect", data={
        "token": "INVALID_TOKEN",
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
    })
    assert r.status_code == 200
    assert r.json() == {"active": False}


def test_introspect_no_client_auth(client):
    token = _get_access_token(client)
    r = client.post("/oauth/introspect", data={"token": token})
    assert r.status_code == 401


def test_introspect_wrong_client_secret(client):
    token = _get_access_token(client)
    r = client.post("/oauth/introspect", data={
        "token": token,
        "client_id": "tripbiz-booking-app",
        "client_secret": "WRONG_SECRET",
    })
    assert r.status_code == 401


def test_introspect_revoked_token(client):
    """revoke 后 introspect 应该 active=false"""
    token = _get_access_token(client)
    # revoke
    basic = __import__("base64").b64encode(b"tripbiz-booking-app:tripbiz-booking-app-secret-2026").decode()
    r = client.post("/oauth/revoke",
                    data={"token": token},
                    headers={"Authorization": f"Basic {basic}"})
    assert r.status_code == 200
    # introspect
    r2 = client.post("/oauth/introspect", data={
        "token": token,
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
    })
    assert r2.json() == {"active": False}


# ============================================
# Observability - Prometheus metrics
# ============================================
def test_metrics_endpoint(client):
    """Generate some traffic, then check Prometheus format"""
    # 清空 metrics（之前测试可能留）
    from app.observability.metrics import reset_metrics
    reset_metrics()
    # 触发流量
    for _ in range(3):
        client.get("/health")
    client.get("/.well-known/openid-configuration")
    client.get("/.well-known/jwks.json")

    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    text = r.text
    # Prometheus format 检查
    assert "# HELP idm_requests_total" in text
    assert "# TYPE idm_requests_total counter" in text
    assert "# HELP idm_request_duration_seconds" in text
    assert "# TYPE idm_request_duration_seconds histogram" in text
    # 至少一个 endpoint 的 metrics
    assert 'endpoint="/health"' in text
    assert 'endpoint="/.well-known/openid-configuration"' in text


def test_metrics_response_time_header(client):
    """每个 response 应有 X-Response-Time-Ms header"""
    r = client.get("/health")
    assert "X-Response-Time-Ms" in r.headers
    # 应该是数字
    ms = float(r.headers["X-Response-Time-Ms"])
    assert ms >= 0
    assert ms < 1000  # 不应该超过 1s


def test_metrics_count_4xx(client):
    """4xx errors 应该被 metrics 捕获"""
    from app.observability.metrics import reset_metrics, _error_count, _request_count
    reset_metrics()
    # 触发 404
    client.get("/oauth/userinfo")
    r = client.get("/metrics")
    # 应该有 401 记录
    assert 'status="401"' in r.text


def test_signals_json(client):
    from app.observability.metrics import reset_metrics
    reset_metrics()
    # 触发一些流量
    client.get("/health")
    client.get("/health")
    client.get("/.well-known/jwks.json")

    r = client.get("/observability/signals")
    assert r.status_code == 200
    d = r.json()
    assert d["total_requests"] >= 3
    assert "traffic" in d
    assert "latency_ms" in d
    assert "saturation" in d
    assert "by_status" in d
    assert "error_rate_pct" in d
    # /health 至少 2 次
    assert d["traffic"].get("/health", 0) >= 2
    # /health 的 latency 有 p50/p95/p99
    assert "p50" in d["latency_ms"].get("/health", {})


def test_signals_zero_traffic(client):
    """0 流量时 signals 不应该崩"""
    from app.observability.metrics import reset_metrics
    reset_metrics()
    r = client.get("/observability/signals")
    assert r.status_code == 200
    d = r.json()
    assert d["total_requests"] == 0
    assert d["error_rate_pct"] == 0


def test_dashboard_html(client):
    """dashboard 渲染 HTML 含 4 大黄金信号"""
    from app.observability.metrics import reset_metrics
    reset_metrics()
    client.get("/health")
    r = client.get("/observability/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    html = r.text
    # 4 Golden Signals
    assert "Traffic" in html
    assert "Errors" in html
    assert "Saturation" in html
    assert "Active Users" in html
    # Prometheus exposition link
    assert "/metrics" in html
    # Per-endpoint table
    assert "/health" in html


# ============================================
# In-flight tracking
# ============================================
def test_in_flight_metric_resets(client):
    """in-flight gauge 应该返回 0（请求结束 incr/decr 配对）"""
    from app.observability.metrics import reset_metrics, _in_flight
    reset_metrics()
    client.get("/health")
    # 现在 in-flight 应该是 0（如果 middleware 正常工作）
    assert _in_flight.get("/health", 0) == 0


# ============================================
# Module-level unit tests（metrics.py）
# ============================================
def test_metrics_record_request_basic():
    from app.observability.metrics import record_request, _request_count, _latency_count
    from app.observability.metrics import reset_metrics
    reset_metrics()
    record_request("/test", "GET", 200, 0.05)
    record_request("/test", "GET", 500, 0.2)
    assert _request_count[("/test", "GET", 200)] == 1
    assert _request_count[("/test", "GET", 500)] == 1
    assert _latency_count["/test"] == 2


def test_golden_signals_error_rate():
    from app.observability.metrics import (
        record_request, golden_signals_summary, reset_metrics,
    )
    reset_metrics()
    # 9 个 200 + 1 个 500
    for _ in range(9):
        record_request("/x", "GET", 200, 0.01)
    record_request("/x", "GET", 500, 0.1)
    s = golden_signals_summary()
    assert s["total_requests"] == 10
    assert s["total_errors"] == 1
    assert s["error_rate_pct"] == 10.0


def test_golden_signals_latency_p50_p95_p99():
    from app.observability.metrics import record_request, golden_signals_summary, reset_metrics
    reset_metrics()
    # 99 个 fast + 1 个 slow
    for _ in range(99):
        record_request("/y", "GET", 200, 0.001)
    record_request("/y", "GET", 200, 5.0)
    s = golden_signals_summary()
    p95 = s["latency_ms"]["/y"]["p95"]
    assert p95 >= 5.0  # p95 应该看到 5s 那个慢请求


def test_prometheus_format_compatible():
    """Prometheus text 格式校验"""
    from app.observability.metrics import (
        record_request, render_prometheus, reset_metrics,
    )
    reset_metrics()
    record_request("/api/test", "POST", 200, 0.05)
    text = render_prometheus()
    lines = text.split("\n")
    # 每行应该是 metric_name{labels} value 或 # HELP/TYPE 或 空白
    for line in lines:
        if not line or line.startswith("#"):
            continue
        # metric_name{labels} value
        # 或 metric_name value
        assert "{" in line or " " in line, f"Invalid line: {line}"