"""
IdM SRE Lab - Week 19-20 (Chaos Engineering) tests
- 3 实验类型: pod_kill / network_partition / latency_injection
- baseline/during/after metrics + hypothesis verdict
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.chaos.runner import (
    EXPERIMENT_TYPES, evaluate_hypothesis, create_experiment,
    run_experiment, get_experiment, list_experiments,
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
# Module-level: experiment types + hypothesis
# ============================================
def test_experiment_types_count():
    assert len(EXPERIMENT_TYPES) == 3
    assert "pod_kill" in EXPERIMENT_TYPES
    assert "network_partition" in EXPERIMENT_TYPES
    assert "latency_injection" in EXPERIMENT_TYPES


def test_evaluate_hypothesis_pass():
    """hypothesis: 'service should remain stable' + error_rate 不变 → PASSED"""
    baseline = {"error_rate_pct": 1.0}
    after = {"error_rate_pct": 2.0}
    verdict = evaluate_hypothesis("service should remain stable", baseline, after)
    assert verdict == "PASSED"


def test_evaluate_hypothesis_fail():
    """error_rate 大幅上升 → FAILED"""
    baseline = {"error_rate_pct": 1.0}
    after = {"error_rate_pct": 50.0}
    verdict = evaluate_hypothesis("service should remain stable", baseline, after)
    assert verdict == "FAILED"


def test_evaluate_hypothesis_threshold():
    """hypothesis 含 <200ms 阈值 → PASSED if within"""
    baseline = {"error_rate_pct": 1.0}
    after = {"error_rate_pct": 1.5}
    verdict = evaluate_hypothesis("p99 latency <200ms", baseline, after)
    assert verdict == "PASSED"


# ============================================
# DB CRUD
# ============================================
def test_create_experiment(client):
    exp_id = create_experiment(
        "pod_kill", "token-issuer", 2, "service should remain stable", "test note"
    )
    assert exp_id.startswith("CHAOS-")
    d = get_experiment(exp_id)
    assert d["experiment_type"] == "pod_kill"
    assert d["target_service"] == "token-issuer"
    assert d["duration_seconds"] == 2
    assert d["status"] == "RUNNING"
    assert "baseline_metrics" in d
    assert isinstance(d["baseline_metrics"], dict)


def test_list_experiments(client):
    create_experiment("pod_kill", "service_a", 2, "h1")
    create_experiment("latency_injection", "service_b", 2, "h2")
    items = list_experiments(limit=10)
    assert len(items) >= 2


def test_list_experiments_filter_type(client):
    create_experiment("pod_kill", "a", 2, "h1")
    create_experiment("latency_injection", "b", 2, "h2")
    items = list_experiments(experiment_type="pod_kill", limit=10)
    for it in items:
        assert it["experiment_type"] == "pod_kill"


# ============================================
# Experiment runner
# ============================================
def test_run_pod_kill_experiment(client):
    """pod_kill 2s → error_rate 应大幅上升（verdict FAILED if "stable" hypothesis）"""
    exp_id = create_experiment("pod_kill", "test-svc", 2, "service should remain stable")
    result = run_experiment(exp_id)
    assert result["experiment_id"] == exp_id
    assert result["verdict"] == "FAILED"  # baseline 0% → after 100%
    d = get_experiment(exp_id)
    assert d["status"] == "COMPLETED"
    assert d["finished_at"] is not None


def test_run_network_partition_experiment(client):
    """network_partition → 一半请求 timeout (504) → error_rate 上升"""
    exp_id = create_experiment("network_partition", "test-svc", 2, "service should remain stable")
    result = run_experiment(exp_id)
    assert result["verdict"] in ("FAILED", "PASSED")
    d = get_experiment(exp_id)
    assert d["status"] == "COMPLETED"


def test_run_latency_injection_experiment(client):
    """latency_injection → 高延迟（不增加错误，但 p99 上升）"""
    exp_id = create_experiment("latency_injection", "test-svc", 2, "service should remain stable")
    result = run_experiment(exp_id)
    d = get_experiment(exp_id)
    assert d["status"] == "COMPLETED"
    assert d["verdict"] in ("FAILED", "PASSED")


# ============================================
# FastAPI endpoints
# ============================================
def test_endpoint_list_types(client):
    r = client.get("/chaos/types")
    assert r.status_code == 200
    d = r.json()
    assert d["count"] == 3
    assert any(t["type"] == "pod_kill" for t in d["types"])


def test_endpoint_create_experiment(client):
    r = client.post("/chaos/experiments", data={
        "experiment_type": "pod_kill",
        "target_service": "token-issuer",
        "duration_seconds": "2",
        "hypothesis": "service should remain stable",
    })
    assert r.status_code == 200
    assert "experiment_id" in r.json()


def test_endpoint_create_invalid_type(client):
    r = client.post("/chaos/experiments", data={
        "experiment_type": "invalid",
        "target_service": "x",
        "duration_seconds": "2",
    })
    assert r.status_code == 400


def test_endpoint_create_invalid_duration(client):
    r = client.post("/chaos/experiments", data={
        "experiment_type": "pod_kill",
        "target_service": "x",
        "duration_seconds": "100",
    })
    assert r.status_code == 400


def test_endpoint_create_missing_target(client):
    r = client.post("/chaos/experiments", data={
        "experiment_type": "pod_kill",
        "duration_seconds": "2",
    })
    assert r.status_code == 400


def test_endpoint_run_experiment(client):
    r = client.post("/chaos/experiments", data={
        "experiment_type": "pod_kill",
        "target_service": "test",
        "duration_seconds": "2",
        "hypothesis": "service should remain stable",
    })
    exp_id = r.json()["experiment_id"]
    r2 = client.post(f"/chaos/experiments/{exp_id}/run")
    assert r2.status_code == 200
    d = r2.json()
    assert d["verdict"] in ("PASSED", "FAILED", "EXPECTED_FAILURE")


def test_endpoint_get_experiment(client):
    r = client.post("/chaos/experiments", data={
        "experiment_type": "pod_kill",
        "target_service": "test",
        "duration_seconds": "2",
        "hypothesis": "h",
    })
    exp_id = r.json()["experiment_id"]
    client.post(f"/chaos/experiments/{exp_id}/run")
    r2 = client.get(f"/chaos/experiments/{exp_id}")
    assert r2.status_code == 200
    d = r2.json()
    assert d["status"] == "COMPLETED"
    assert "baseline_metrics" in d
    assert "after_metrics" in d


def test_endpoint_get_experiment_404(client):
    r = client.get("/chaos/experiments/CHAOS-DOES-NOT-EXIST")
    assert r.status_code == 404


def test_endpoint_list_all(client):
    client.post("/chaos/experiments", data={
        "experiment_type": "pod_kill", "target_service": "a",
        "duration_seconds": "2", "hypothesis": "h1",
    })
    client.post("/chaos/experiments", data={
        "experiment_type": "latency_injection", "target_service": "b",
        "duration_seconds": "2", "hypothesis": "h2",
    })
    r = client.get("/chaos/experiments")
    assert r.status_code == 200
    assert r.json()["count"] >= 2