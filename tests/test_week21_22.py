"""
IdM SRE Lab - Week 21-22 (Incident Response) tests
- 10 runbooks (recommend + get by id + by alert)
- 3 mock incident simulators (latency_spike / auth_fail / memory_leak)
- state machine: ACTIVE → INVESTIGATING → RESOLVED
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.incidents.runbook import (
    RUNBOOKS, get_runbook_by_id, get_runbook_by_alert,
    list_runbooks, recommend_runbook,
)
from app.incidents.simulator import (
    INCIDENT_TYPES, SIMULATORS,
    create_incident, update_incident_status, get_incident,
    list_incidents, list_active_incidents, start_simulator,
)


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


# ============================================
# Runbooks
# ============================================
def test_runbooks_count():
    assert len(RUNBOOKS) == 10


def test_runbook_by_id():
    rb = get_runbook_by_id("high_error_rate")
    assert rb is not None
    assert rb["severity"] == "SEV-1"
    assert len(rb["steps"]) >= 3


def test_runbook_by_alert():
    rb = get_runbook_by_alert("HighErrorRate")
    assert rb is not None
    assert rb["id"] == "high_error_rate"


def test_runbook_by_alert_missing():
    assert get_runbook_by_alert("NonexistentAlert") is None


def test_runbook_by_id_missing():
    assert get_runbook_by_id("nonexistent") is None


def test_recommend_runbook_high_error():
    metrics = {"error_rate_pct": 10, "total_requests": 100}
    rb = recommend_runbook(metrics)
    assert rb is not None
    assert rb["id"] == "high_error_rate"


def test_recommend_runbook_high_latency():
    metrics = {"error_rate_pct": 0, "total_requests": 100,
               "latency_ms": {"/oauth/token": {"p99": 2000}}}
    rb = recommend_runbook(metrics)
    assert rb is not None
    assert rb["id"] == "high_latency"


def test_recommend_runbook_no_traffic():
    metrics = {"error_rate_pct": 0, "total_requests": 0}
    rb = recommend_runbook(metrics)
    assert rb is not None
    assert rb["id"] == "service_discovery_failure"


def test_recommend_runbook_all_ok():
    metrics = {"error_rate_pct": 0, "total_requests": 100,
               "latency_ms": {"/oauth/token": {"p99": 100}}}
    rb = recommend_runbook(metrics)
    assert rb is None


# ============================================
# Incident lifecycle (DB CRUD)
# ============================================
def test_create_incident():
    inc_id = create_incident("latency_spike", title="Custom latency issue")
    assert inc_id.startswith("INC-")
    d = get_incident(inc_id)
    assert d["status"] == "ACTIVE"
    assert d["incident_type"] == "latency_spike"
    assert d["title"] == "Custom latency issue"


def test_update_incident_status_resolve():
    inc_id = create_incident("auth_fail")
    d = update_incident_status(inc_id, "RESOLVED",
                                 mitigation="rotated key",
                                 lessons_learned="need canary deploy")
    assert d["status"] == "RESOLVED"
    assert d["mitigation"] == "rotated key"
    assert d["lessons_learned"] == "need canary deploy"
    assert d["resolved_at"] is not None


def test_update_incident_status_investigating_no_resolved():
    inc_id = create_incident("memory_leak")
    d = update_incident_status(inc_id, "INVESTIGATING",
                                 mitigation="tracemalloc")
    assert d["status"] == "INVESTIGATING"
    assert d["resolved_at"] is None


def test_update_incident_status_invalid():
    inc_id = create_incident("auth_fail")
    with pytest.raises(ValueError):
        update_incident_status(inc_id, "INVALID_STATE")


def test_list_incidents_filter():
    create_incident("auth_fail")
    create_incident("latency_spike")
    items = list_incidents(limit=10)
    assert len(items) >= 2
    items2 = list_incidents(status="ACTIVE", limit=10)
    for it in items2:
        assert it["status"] == "ACTIVE"


def test_list_active_incidents():
    inc1 = create_incident("auth_fail")
    inc2 = create_incident("latency_spike")
    update_incident_status(inc1, "RESOLVED")
    active = list_active_incidents()
    active_ids = {x["incident_id"] for x in active}
    assert inc1 not in active_ids
    assert inc2 in active_ids


# ============================================
# FastAPI endpoints
# ============================================
def test_endpoint_list_runbooks(client):
    r = client.get("/runbooks")
    assert r.status_code == 200
    assert r.json()["count"] == 10


def test_endpoint_get_runbook(client):
    r = client.get("/runbooks/high_error_rate")
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == "high_error_rate"


def test_endpoint_get_runbook_404(client):
    r = client.get("/runbooks/nonexistent")
    assert r.status_code == 404


def test_endpoint_recommend_runbook(client):
    r = client.get("/runbooks/recommend")
    assert r.status_code == 200


def test_endpoint_list_incident_types(client):
    r = client.get("/incidents/types")
    assert r.status_code == 200
    assert r.json()["count"] == 3


def test_endpoint_create_incident(client):
    r = client.post("/incidents", data={
        "incident_type": "auth_fail",
        "severity": "SEV-1",
        "title": "Auth failure storm",
        "description": "Custom incident",
    })
    assert r.status_code == 200
    assert "incident_id" in r.json()


def test_endpoint_create_incident_missing(client):
    r = client.post("/incidents", data={"title": "x"})
    assert r.status_code == 400


def test_endpoint_simulate_incident(client):
    r = client.post("/incidents/simulate", data={
        "incident_type": "auth_fail",
        "duration_seconds": "2",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ACTIVE"
    assert "incident_id" in d


def test_endpoint_simulate_invalid_type(client):
    r = client.post("/incidents/simulate", data={
        "incident_type": "invalid",
        "duration_seconds": "2",
    })
    assert r.status_code == 400


def test_endpoint_simulate_invalid_duration(client):
    r = client.post("/incidents/simulate", data={
        "incident_type": "auth_fail",
        "duration_seconds": "500",
    })
    assert r.status_code == 400


def test_endpoint_get_incident(client):
    r = client.post("/incidents", data={
        "incident_type": "auth_fail", "title": "test"
    })
    inc_id = r.json()["incident_id"]
    r2 = client.get(f"/incidents/{inc_id}")
    assert r2.status_code == 200
    assert r2.json()["incident_id"] == inc_id


def test_endpoint_get_incident_404(client):
    r = client.get("/incidents/INC-MISSING")
    assert r.status_code == 404


def test_endpoint_patch_incident(client):
    r = client.post("/incidents", data={
        "incident_type": "auth_fail", "title": "test"
    })
    inc_id = r.json()["incident_id"]
    r2 = client.patch(f"/incidents/{inc_id}", data={
        "status": "RESOLVED",
        "mitigation": "rolled back",
        "lessons_learned": "need canary",
    })
    assert r2.status_code == 200
    d = r2.json()
    assert d["status"] == "RESOLVED"
    assert d["mitigation"] == "rolled back"


def test_endpoint_patch_incident_invalid_status(client):
    r = client.post("/incidents", data={
        "incident_type": "auth_fail", "title": "test"
    })
    inc_id = r.json()["incident_id"]
    r2 = client.patch(f"/incidents/{inc_id}", data={"status": "INVALID"})
    assert r2.status_code == 400


def test_endpoint_patch_incident_404(client):
    r = client.patch("/incidents/INC-MISSING", data={"status": "RESOLVED"})
    assert r.status_code == 404


def test_endpoint_list_incidents(client):
    client.post("/incidents", data={"incident_type": "auth_fail", "title": "t1"})
    client.post("/incidents", data={"incident_type": "latency_spike", "title": "t2"})
    r = client.get("/incidents")
    assert r.status_code == 200
    assert r.json()["count"] >= 2


def test_endpoint_active_incidents(client):
    inc1 = client.post("/incidents", data={"incident_type": "auth_fail", "title": "t1"}).json()["incident_id"]
    client.post("/incidents", data={"incident_type": "latency_spike", "title": "t2"})
    client.patch(f"/incidents/{inc1}", data={"status": "RESOLVED"})
    r = client.get("/incidents/active")
    assert r.status_code == 200
    items = r.json()["items"]
    for it in items:
        assert it["status"] == "ACTIVE"


def test_simulator_actually_runs(client):
    """验证 simulator 真的产生 metrics（auth_fail → 401 计数增加）"""
    from app.observability.metrics import _error_count, _request_count, reset_metrics
    reset_metrics()
    r = client.post("/incidents/simulate", data={
        "incident_type": "auth_fail",
        "duration_seconds": "2",
    })
    inc_id = r.json()["incident_id"]
    import time
    time.sleep(1)  # 让 simulator 跑 1 秒
    # 应该有 401 计数
    auth_401 = _error_count.get("/oauth/token", {}).get(401, 0)
    assert auth_401 > 0