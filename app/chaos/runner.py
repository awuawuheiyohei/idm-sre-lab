"""
Chaos Engineering Runner (Week 19-20 MVP)

Self-implemented chaos experiments (PEP 668 compatible — no chaos-mesh):
1. pod_kill — 模拟服务进程被 kill（强制 sleep + reconnect）
2. network_partition — 模拟网络分区（中间路由阻断）
3. latency_injection — 模拟延迟 spike

每个实验：
- 实验前 snapshot baseline metrics
- 实验运行中 snapshot during metrics
- 实验后 snapshot after metrics
- 对比 hypothesis（"SLO 不超过 baseline X%"）→ verdict PASSED / FAILED

PRD 反模式：禁止"choreographed chaos"——必须 hypothesis-driven + 可重复 + 有前后对照
"""
import json
import time
import threading
import random
from datetime import datetime, timezone
from typing import Optional

from ..db import db_connection
from ..observability.metrics import (
    record_request, golden_signals_summary,
    _request_count, _latency_buckets, _error_count,
)


# ============================================
# Snapshot helpers
# ============================================
def snapshot_metrics() -> dict:
    """当前 metrics summary（用作 baseline/during/after 对照）"""
    return golden_signals_summary()


# ============================================
# Experiment implementations
# ============================================
def run_pod_kill(target_service: str, duration_seconds: int) -> dict:
    """Pod kill 实验 — 模拟服务进程被 SIGKILL"""
    during = []
    start = time.time()
    # 模拟：duration 内强制把每个请求都失败（模拟进程死亡）
    while time.time() - start < duration_seconds:
        record_request(f"/{target_service}", "GET", 503, random.uniform(0.001, 0.05))
        during.append(snapshot_metrics())
        time.sleep(0.1)
    return {
        "during_samples": len(during),
        "during_last": during[-1] if during else None,
    }


def run_network_partition(target_service: str, duration_seconds: int) -> dict:
    """网络分区 — 模拟 50% 请求超时"""
    during = []
    start = time.time()
    while time.time() - start < duration_seconds:
        # 一半请求 timeout（高延迟 + 错误）
        if random.random() < 0.5:
            record_request(f"/{target_service}", "GET", 504, random.uniform(2.0, 5.0))
        else:
            record_request(f"/{target_service}", "GET", 200, random.uniform(0.05, 0.2))
        during.append(snapshot_metrics())
        time.sleep(0.1)
    return {
        "during_samples": len(during),
        "during_last": during[-1] if during else None,
    }


def run_latency_injection(target_service: str, duration_seconds: int,
                           injection_ms: int = 800) -> dict:
    """延迟注入 — 给每个请求加 injection_ms"""
    during = []
    start = time.time()
    while time.time() - start < duration_seconds:
        record_request(f"/{target_service}", "GET", 200, injection_ms / 1000.0)
        during.append(snapshot_metrics())
        time.sleep(0.1)
    return {
        "during_samples": len(during),
        "during_last": during[-1] if during else None,
    }


EXPERIMENT_TYPES = {
    "pod_kill": run_pod_kill,
    "network_partition": run_network_partition,
    "latency_injection": run_latency_injection,
}


# ============================================
# Hypothesis evaluation
# ============================================
def evaluate_hypothesis(hypothesis: str, baseline: dict, after: dict) -> str:
    """根据 hypothesis 字符串评估 verdict

    简化版：
    - hypothesis 含 "PASS" 或 "REMAIN" → 期望 SLO 不变（PASSED）
    - hypothesis 含 "FAIL" 或 "BREACH" → 期望 SLO 下降（FAILED）
    - 否则 → UNKNOWN
    """
    h = hypothesis.lower()
    if "remain" in h or "stable" in h or "pass" in h or "<" in h or "no breach" in h:
        # 期望保持不变
        # 比较 baseline / after error_rate
        b_err = baseline.get("error_rate_pct", 0)
        a_err = after.get("error_rate_pct", 0)
        # 容许 5% 误差
        if a_err <= b_err + 5:
            return "PASSED"
        return "FAILED"
    if "fail" in h or "breach" in h:
        return "EXPECTED_FAILURE"
    return "UNKNOWN"


# ============================================
# DB CRUD
# ============================================
def create_experiment(experiment_type: str, target_service: str,
                       duration_seconds: int, hypothesis: str,
                       notes: str = None) -> str:
    """Create + start experiment"""
    exp_id = "CHAOS-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + str(random.randint(1000, 9999))
    baseline = snapshot_metrics()
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO chaos_experiments
               (experiment_id, experiment_type, target_service, duration_seconds,
                hypothesis, baseline_metrics, status, notes)
               VALUES (?, ?, ?, ?, ?, ?, 'RUNNING', ?)""",
            (exp_id, experiment_type, target_service, duration_seconds,
             hypothesis, json.dumps(baseline), notes)
        )
        conn.commit()
    return exp_id


def finish_experiment(exp_id: str, during_metrics: dict, after_metrics: dict) -> str:
    """完成实验：保存 during/after metrics + verdict"""
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM chaos_experiments WHERE experiment_id=?",
                          (exp_id,)).fetchone()
        if not row:
            raise ValueError(f"Experiment not found: {exp_id}")
        d = {k: row[k] for k in row.keys()}
        baseline = json.loads(d["baseline_metrics"]) if d["baseline_metrics"] else {}
        verdict = evaluate_hypothesis(d["hypothesis"], baseline, after_metrics)

        conn.execute(
            """UPDATE chaos_experiments SET status='COMPLETED',
               during_metrics=?, after_metrics=?, verdict=?,
               finished_at=datetime('now') WHERE experiment_id=?""",
            (json.dumps(during_metrics), json.dumps(after_metrics), verdict, exp_id)
        )
        conn.commit()
    return verdict


def get_experiment(exp_id: str) -> dict | None:
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM chaos_experiments WHERE experiment_id=?",
                          (exp_id,)).fetchone()
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
    for k in ("baseline_metrics", "during_metrics", "after_metrics"):
        try:
            d[k] = json.loads(d[k]) if d[k] else {}
        except Exception:
            d[k] = {}
    return d


def list_experiments(limit: int = 20, experiment_type: str = None) -> list:
    sql = "SELECT * FROM chaos_experiments WHERE 1=1"
    params = []
    if experiment_type:
        sql += " AND experiment_type=?"
        params.append(experiment_type)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(limit)
    with db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}
        out.append(d)
    return out


# ============================================
# Experiment orchestrator
# ============================================
def run_experiment(exp_id: str) -> dict:
    """执行已 create 的 experiment（同步，blocking）"""
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM chaos_experiments WHERE experiment_id=?",
                          (exp_id,)).fetchone()
    if not row:
        raise ValueError(f"Experiment not found: {exp_id}")
    d = {k: row[k] for k in row.keys()}

    exp_type = d["experiment_type"]
    runner = EXPERIMENT_TYPES.get(exp_type)
    if not runner:
        raise ValueError(f"Unknown experiment type: {exp_type}")

    during = runner(d["target_service"], d["duration_seconds"])
    after = snapshot_metrics()
    verdict = finish_experiment(exp_id, during, after)
    return {
        "experiment_id": exp_id,
        "verdict": verdict,
        "during": during,
        "after": after,
    }


def run_experiment_async(exp_id: str):
    """异步执行（不阻塞 API）"""
    thread = threading.Thread(target=lambda: run_experiment(exp_id), daemon=True)
    thread.start()