"""
Device Provisioning core (Week 9-10: Knorr BU scenario)
- Lifecycle: REGISTERED -> ACTIVE -> RETIRED / LOST
- Compliance: PENDING / COMPLIANT / NON_COMPLIANT
- Associate with user + business_unit

All DB ops use db_connection() context manager (avoid SQLite WAL lock).
"""
import secrets
from datetime import datetime, timezone

from ..db import db_connection


def _log_audit(conn, action: str, entity_id: str, actor: str = None,
               user_id: str = None, details: dict = None):
    import json as _json
    conn.execute(
        "INSERT INTO device_audit (actor, action, device_id, user_id, details) VALUES (?, ?, ?, ?, ?)",
        (actor, action, entity_id, user_id, _json.dumps(details or {}))
    )


def generate_device_id() -> str:
    return "DEV-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3)


def register_device(device_name: str, user_id: str, device_type: str, os: str,
                     serial_number: str, manufacturer: str = None, model: str = None,
                     business_unit: str = "platform") -> dict:
    """注册新设备（默认 REGISTERED）"""
    device_id = generate_device_id()
    with db_connection() as conn:
        user_row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user_row:
            raise ValueError(f"User not found: {user_id}")
        sn_row = conn.execute("SELECT device_id FROM devices WHERE serial_number=?",
                              (serial_number,)).fetchone()
        if sn_row:
            raise ValueError(f"Serial already registered: {sn_row['device_id']}")
        conn.execute(
            "INSERT INTO devices (device_id, device_name, user_id, device_type, os, serial_number, manufacturer, model, status, compliance_state, business_unit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'REGISTERED', 'PENDING', ?)",
            (device_id, device_name, user_id, device_type, os, serial_number,
             manufacturer, model, business_unit)
        )
        _log_audit(conn, action="device_registered", entity_id=device_id,
                   actor=user_id, user_id=user_id,
                   details={"device_type": device_type, "os": os, "serial_number": serial_number})
        conn.commit()
    return get_device(device_id)


def activate_device(device_id: str) -> dict:
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if not row:
            raise ValueError(f"Device not found: {device_id}")
        if row["status"] not in ("REGISTERED",):
            raise ValueError(f"Cannot activate from status {row['status']}")
        conn.execute(
            "UPDATE devices SET status='ACTIVE', activated_at=datetime('now'), compliance_state='COMPLIANT' WHERE device_id=?",
            (device_id,)
        )
        _log_audit(conn, action="device_activated", entity_id=device_id,
                   user_id=row["user_id"], details={})
        conn.commit()
    return get_device(device_id)


def retire_device(device_id: str, reason: str = "manual_retire") -> dict:
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if not row:
            raise ValueError(f"Device not found: {device_id}")
        if row["status"] == "RETIRED":
            return get_device(device_id)
        conn.execute(
            "UPDATE devices SET status='RETIRED', retired_at=datetime('now') WHERE device_id=?",
            (device_id,)
        )
        _log_audit(conn, action="device_retired", entity_id=device_id,
                   user_id=row["user_id"], details={"reason": reason})
        conn.commit()
    return get_device(device_id)


def mark_lost(device_id: str) -> dict:
    with db_connection() as conn:
        conn.execute("UPDATE devices SET status='LOST' WHERE device_id=?", (device_id,))
        _log_audit(conn, action="device_marked_lost", entity_id=device_id, details={})
        conn.commit()
    return get_device(device_id)


def update_compliance(device_id: str, compliance_state: str) -> dict:
    if compliance_state not in ("PENDING", "COMPLIANT", "NON_COMPLIANT"):
        raise ValueError(f"Invalid compliance_state: {compliance_state}")
    with db_connection() as conn:
        conn.execute(
            "UPDATE devices SET compliance_state=?, last_check_in=datetime('now') WHERE device_id=?",
            (compliance_state, device_id)
        )
        conn.commit()
    return get_device(device_id)


def check_in_device(device_id: str) -> dict:
    with db_connection() as conn:
        conn.execute(
            "UPDATE devices SET last_check_in=datetime('now') WHERE device_id=?",
            (device_id,)
        )
        conn.commit()
    return get_device(device_id)


def get_device(device_id: str) -> dict | None:
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        return {k: row[k] for k in row.keys()} if row else None


def list_devices(user_id: str = None, status: str = None,
                 business_unit: str = None, device_type: str = None) -> list:
    sql = "SELECT * FROM devices WHERE 1=1"
    params = []
    if user_id:
        sql += " AND user_id=?"
        params.append(user_id)
    if status:
        sql += " AND status=?"
        params.append(status)
    if business_unit:
        sql += " AND business_unit=?"
        params.append(business_unit)
    if device_type:
        sql += " AND device_type=?"
        params.append(device_type)
    sql += " ORDER BY registered_at DESC"
    with db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def device_portfolio_stats() -> dict:
    with db_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        by_status = rows_to_dicts(conn.execute(
            "SELECT status, COUNT(*) as cnt FROM devices GROUP BY status"
        ).fetchall())
        by_type = rows_to_dicts(conn.execute(
            "SELECT device_type, COUNT(*) as cnt FROM devices GROUP BY device_type"
        ).fetchall())
        by_bu = rows_to_dicts(conn.execute(
            "SELECT business_unit, COUNT(*) as cnt FROM devices GROUP BY business_unit"
        ).fetchall())
        non_compliant = conn.execute(
            "SELECT COUNT(*) FROM devices WHERE compliance_state='NON_COMPLIANT'"
        ).fetchone()[0]
        lost = conn.execute("SELECT COUNT(*) FROM devices WHERE status='LOST'").fetchone()[0]
    return {
        "total_devices": total,
        "by_status": by_status,
        "by_type": by_type,
        "by_business_unit": by_bu,
        "non_compliant_count": non_compliant,
        "lost_count": lost,
    }


def rows_to_dicts(rows) -> list:
    return [{k: r[k] for k in r.keys()} for r in rows]