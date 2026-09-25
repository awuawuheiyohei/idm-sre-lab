"""
WebAuthn / FIDO2 core (Week 7-8 MVP, simplified implementation)

Real WebAuthn requires:
- CBOR encoding (RFC 8949)
- COSE ECDSA/RSA signatures
- base64url no-padding
- attestation object parsing

Simplified (PEP 668 compatible):
- HMAC-SHA256 challenge-response (production swap to py_webauthn + CBOR + COSE)
- challenge: base64url no-padding
- "signature" = HMAC over (challenge || credential_id || counter)

All DB ops use db_connection() context manager to avoid SQLite WAL lock.
"""
import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone, timedelta

from ..db import get_conn, db_connection


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


CHALLENGE_TTL = 300


def generate_challenge() -> str:
    return b64url_encode(secrets.token_bytes(32))


def save_challenge(challenge: str, user_id: str | None, purpose: str):
    expires = (datetime.now(timezone.utc) + timedelta(seconds=CHALLENGE_TTL)).isoformat()
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO webauthn_challenges (challenge, user_id, purpose, expires_at) VALUES (?, ?, ?, ?)",
            (challenge, user_id, purpose, expires)
        )
        conn.commit()


def consume_challenge(challenge: str, expected_purpose: str) -> dict | None:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM webauthn_challenges WHERE challenge=? AND consumed=0",
            (challenge,)
        ).fetchone()
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
        expires = datetime.fromisoformat(d["expires_at"])
        if datetime.now(timezone.utc) > expires:
            return None
        if d["purpose"] != expected_purpose:
            return None
        conn.execute("UPDATE webauthn_challenges SET consumed=1 WHERE challenge=?", (challenge,))
        conn.commit()
        return d


DEMO_HMAC_SECRET = b"webauthn-demo-secret-key-2026"


def sign_challenge_response(challenge: str, credential_id: str, counter: int) -> str:
    msg = f"{challenge}|{credential_id}|{counter}".encode("utf-8")
    sig = hmac.new(DEMO_HMAC_SECRET, msg, hashlib.sha256).digest()
    return b64url_encode(sig)


def verify_challenge_response(challenge: str, credential_id: str, counter: int,
                               client_signature: str) -> bool:
    expected = sign_challenge_response(challenge, credential_id, counter)
    try:
        return hmac.compare_digest(b64url_decode(expected), b64url_decode(client_signature))
    except Exception:
        return False


def save_credential(credential_id: str, user_id: str, public_key: str,
                     counter: int = 0, aaguid: str = None,
                     transports: list = None, friendly_name: str = None) -> None:
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO webauthn_credentials (credential_id, user_id, public_key, counter, aaguid, transports, friendly_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (credential_id, user_id, public_key, counter, aaguid,
             json.dumps(transports or []), friendly_name)
        )
        conn.commit()


def get_credential(credential_id: str) -> dict | None:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM webauthn_credentials WHERE credential_id=?",
            (credential_id,)
        ).fetchone()
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
    try:
        d["transports"] = json.loads(d["transports"])
    except Exception:
        d["transports"] = []
    return d


def list_credentials_for_user(user_id: str) -> list:
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM webauthn_credentials WHERE user_id=? ORDER BY created_at",
            (user_id,)
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def increment_credential_counter(credential_id: str) -> int:
    with db_connection() as conn:
        conn.execute(
            "UPDATE webauthn_credentials SET counter = counter + 1, last_used_at = datetime('now') WHERE credential_id=?",
            (credential_id,)
        )
        conn.commit()
        row = conn.execute(
            "SELECT counter FROM webauthn_credentials WHERE credential_id=?",
            (credential_id,)
        ).fetchone()
    return row["counter"] if row else 0


def delete_credential(credential_id: str, user_id: str) -> bool:
    with db_connection() as conn:
        cur = conn.execute(
            "DELETE FROM webauthn_credentials WHERE credential_id=? AND user_id=?",
            (credential_id, user_id)
        )
        conn.commit()
    return cur.rowcount > 0


def _log_audit(action: str, entity_id: str, actor: str = None, details: dict = None):
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO webauthn_audit (actor, action, credential_id, details) VALUES (?, ?, ?, ?)",
            (actor, action, entity_id, json.dumps(details or {}))
        )
        conn.commit()