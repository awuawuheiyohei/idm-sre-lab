"""
Post-Mortem Document Manager (Week 27-28 MVP)
- CRUD for pm_documents
- 3 真实 PM docs 基于之前 chaos experiments
- blameless culture 默认开启
"""
import json
import secrets
from datetime import datetime, timezone

from ..db import db_connection


def _generate_pm_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    rand = secrets.token_hex(2).upper()
    return f"PM-{ts}-{rand}"


def create_pm(incident_id: str, title: str, severity: str,
              summary: str = None, timeline: list = None,
              root_cause: str = None, impact: str = None,
              what_went_well: str = None, what_went_wrong: str = None,
              action_items: list = None,
              blameless: bool = True) -> str:
    """创建 PM 文档（DRAFT 状态）"""
    pm_id = _generate_pm_id()
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO pm_documents
               (pm_id, incident_id, title, severity, summary, timeline,
                root_cause, impact, what_went_well, what_went_wrong,
                action_items, blameless, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT')""",
            (pm_id, incident_id, title, severity, summary,
             json.dumps(timeline or []),
             root_cause, impact, what_went_well, what_went_wrong,
             json.dumps(action_items or []),
             1 if blameless else 0)
        )
        conn.commit()
    return pm_id


def update_pm_status(pm_id: str, status: str) -> dict | None:
    if status not in ("DRAFT", "REVIEW", "PUBLISHED", "ARCHIVED"):
        raise ValueError(f"Invalid status: {status}")
    published_at = datetime.now(timezone.utc).isoformat() if status == "PUBLISHED" else None
    with db_connection() as conn:
        conn.execute(
            "UPDATE pm_documents SET status=?, published_at=COALESCE(?, published_at) WHERE pm_id=?",
            (status, published_at, pm_id)
        )
        conn.commit()
    return get_pm(pm_id)


def get_pm(pm_id: str) -> dict | None:
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM pm_documents WHERE pm_id=?",
                          (pm_id,)).fetchone()
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
    for k in ("timeline", "action_items"):
        try:
            d[k] = json.loads(d[k]) if d[k] else []
        except Exception:
            d[k] = []
    d["blameless"] = bool(d.get("blameless", 0))
    return d


def list_pms(status: str = None, severity: str = None, limit: int = 20) -> list:
    sql = "SELECT * FROM pm_documents WHERE 1=1"
    params = []
    if status:
        sql += " AND status=?"
        params.append(status)
    if severity:
        sql += " AND severity=?"
        params.append(severity)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}
        for k in ("timeline", "action_items"):
            try:
                d[k] = json.loads(d[k]) if d[k] else []
            except Exception:
                d[k] = []
        out.append(d)
    return out