"""
Incident simulator (Week 21-22 MVP)
- 3 类 mock incident 触发器
- 每个 incident 自动推荐 runbook
- state machine: ACTIVE → INVESTIGATING → MITIGATED → RESOLVED
"""
import json
import time
import threading
import random
from datetime import datetime, timezone

from ..db import db_connection
from ..observability.metrics import record_request


# ============================================
# Incident types + severity mapping
# ============================================
INCIDENT_TYPES = {
    "latency_spike": {
        "severity": "SEV-2",
        "title": "Latency spike injection",
        "description": "Inject 800ms latency on /oauth/token for N seconds",
        "recommended_runbook": "high_latency",
    },
    "auth_fail": {
        "severity": "SEV-1",
        "title": "Authentication failure storm",
        "description": "Force all /oauth/token requests to return 401 for N seconds",
        "recommended_runbook": "token_failure_spike",
    },
    "memory_leak": {
        "severity": "SEV-1",
        "title": "Memory leak / OOM risk",
        "description": "Grow in-memory buffer to simulate leak (via _log_buffer)",
        "recommended_runbook": "memory_leak",
    },
}

_active_simulators = {}  # incident_id -> Thread


# ============================================
# Simulators（mock）
# ============================================
def _simulate_latency_spike(incident_id: str, duration_seconds: int):
    """注入高延迟"""
    start = time.time()
    while time.time() - start < duration_seconds:
        record_request("/oauth/token", "POST", 200, 0.8)
        time.sleep(0.2)


def _simulate_auth_fail(incident_id: str, duration_seconds: int):
    """强制 auth 失败"""
    start = time.time()
    while time.time() - start < duration_seconds:
        record_request("/oauth/token", "POST", 401, 0.01)
        time.sleep(0.1)


def _simulate_memory_leak(incident_id: str, duration_seconds: int):
    """增长 log buffer（模拟 leak）"""
    from ..logs.structured_logging import _log_buffer, _buffer_lock
    start = time.time()
    while time.time() - start < duration_seconds:
        # 加 100 条 log 进 buffer
        with _buffer_lock:
            for _ in range(100):
                _log_buffer.append(json.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "level": "WARNING",
                    "logger": "memory_leak_sim",
                    "message": f"leak chunk from {incident_id}",
                }))
        time.sleep(0.5)


SIMULATORS = {
    "latency_spike": _simulate_latency_spike,
    "auth_fail": _simulate_auth_fail,
    "memory_leak": _simulate_memory_leak,
}


# ============================================
# DB CRUD
# ============================================
def create_incident(incident_type: str, severity: str = None, title: str = None,
                    description: str = None, runbook_ref: str = None) -> str:
    """创建 incident（status=ACTIVE）"""
    info = INCIDENT_TYPES.get(incident_type, {})
    sev = severity or info.get("severity", "SEV-3")
    ti = title or info.get("title", incident_type)
    desc = description or info.get("description", "")
    rb = runbook_ref or info.get("recommended_runbook", "")

    inc_id = "INC-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + str(random.randint(1000, 9999))
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO incidents
               (incident_id, incident_type, severity, title, description,
                status, runbook_ref)
               VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?)""",
            (inc_id, incident_type, sev, ti, desc, rb)
        )
        conn.commit()
    return inc_id


def update_incident_status(inc_id: str, status: str, mitigation: str = None,
                            lessons_learned: str = None) -> dict | None:
    """更新 incident 状态（ACTIVE → INVESTIGATING → MITIGATED → RESOLVED）"""
    if status not in ("ACTIVE", "INVESTIGATING", "MITIGATED", "RESOLVED", "POSTMORTEM"):
        raise ValueError(f"Invalid status: {status}")
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM incidents WHERE incident_id=?",
                          (inc_id,)).fetchone()
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
        now = datetime.now(timezone.utc).isoformat()
        resolved_at = now if status in ("RESOLVED", "POSTMORTEM") else None
        conn.execute(
            """UPDATE incidents SET status=?, mitigation=?,
               lessons_learned=?, resolved_at=? WHERE incident_id=?""",
            (status, mitigation or d.get("mitigation"),
             lessons_learned or d.get("lessons_learned"),
             resolved_at or d.get("resolved_at"), inc_id)
        )
        conn.commit()
    return get_incident(inc_id)


def get_incident(inc_id: str) -> dict | None:
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM incidents WHERE incident_id=?",
                          (inc_id,)).fetchone()
        return {k: row[k] for k in row.keys()} if row else None


def list_incidents(status: str = None, limit: int = 20) -> list:
    sql = "SELECT * FROM incidents WHERE 1=1"
    params = []
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY triggered_at DESC LIMIT ?"
    params.append(limit)
    with db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def list_active_incidents() -> list:
    """SEV-1/2 active incidents（on-call dashboard）"""
    return list_incidents(status="ACTIVE", limit=50)


# ============================================
# Lifecycle
# ============================================
def start_simulator(incident_type: str, duration_seconds: int) -> str:
    """创建 + 启动 incident simulator（async）"""
    inc_id = create_incident(incident_type)
    sim = SIMULATORS.get(incident_type)
    if not sim:
        raise ValueError(f"Unknown incident type: {incident_type}")

    def _runner():
        try:
            sim(inc_id, duration_seconds)
        except Exception as e:
            update_incident_status(inc_id, "INVESTIGATING",
                                    mitigation=f"simulator crashed: {e}")

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    _active_simulators[inc_id] = thread
    # duration 后自动 RESOLVED（auto-close）
    def _auto_close():
        time.sleep(duration_seconds + 1)
        try:
            update_incident_status(inc_id, "RESOLVED",
                                    lessons_learned="Auto-closed after duration")
        except Exception:
            pass
    threading.Thread(target=_auto_close, daemon=True).start()
    return inc_id