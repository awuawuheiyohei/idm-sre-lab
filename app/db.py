"""DB helper + RSA key generation"""
import sqlite3
import json
import base64
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone

import bcrypt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "idm.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


@contextmanager
def db_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
    finally:
        conn.close()


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(verbose=False):
    conn = get_conn()
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()
    conn.close()
    if verbose:
        print(f"[+] DB at {DB_PATH}")


def row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()} if row else {}


def rows_to_dicts(rows) -> list:
    return [row_to_dict(r) for r in rows]


def write_audit(conn, actor, action, client_id=None, user_id=None, details=None):
    conn.execute(
        """INSERT INTO oauth_audit (actor, action, client_id, user_id, details)
           VALUES (?, ?, ?, ?, ?)""",
        (actor, action, client_id, user_id, json.dumps(details or {}, ensure_ascii=False))
    )
    conn.commit()


# ============================================
# RSA Key Generation（用于 RS256 JWT）
# ============================================
def _b64url_uint(n: int) -> str:
    """将整数编码为 base64url-no-padding"""
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def generate_rsa_keypair(kid: str) -> tuple[str, dict]:
    """生成 2048-bit RSA keypair，返回 (PEM private, JWK public dict)"""
    key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    pub = key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64url_uint(pub.n),
        "e": _b64url_uint(pub.e),
    }
    return private_pem, jwk


def ensure_signing_key(kid: str = "key-2026-09") -> str:
    """确保至少有一个 active RSA key，返回 kid"""
    conn = get_conn()
    row = conn.execute("SELECT kid FROM rsa_keys WHERE active=1 LIMIT 1").fetchone()
    if row:
        return row["kid"]
    pem, jwk = generate_rsa_keypair(kid)
    conn.execute(
        "INSERT INTO rsa_keys (kid, private_pem, public_jwk) VALUES (?, ?, ?)",
        (kid, pem, json.dumps(jwk))
    )
    conn.commit()
    return kid


def get_signing_key(kid: str) -> tuple[object, dict] | None:
    """返回 (private_key_object, public_jwk_dict) — caller 用 priv.public_key() 来 verify"""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    conn = get_conn()
    row = conn.execute("SELECT * FROM rsa_keys WHERE kid=?", (kid,)).fetchone()
    if not row:
        return None
    priv = load_pem_private_key(row["private_pem"].encode("utf-8"), password=None)
    return priv, json.loads(row["public_jwk"])


def get_active_jwks() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT public_jwk FROM rsa_keys WHERE active=1").fetchall()
    return [json.loads(r["public_jwk"]) for r in rows]


# ============================================
# bcrypt 密码哈希
# ============================================
def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ============================================
# OAuth Server Config
# ============================================
def get_oauth_config() -> dict:
    """返回 OAuth2 server config（用于 /.well-known/openid-configuration）"""
    conn = get_conn()
    base_url = "http://127.0.0.1:5050"  # dev 默认
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "userinfo_endpoint": f"{base_url}/oauth/userinfo",
        "jwks_uri": f"{base_url}/.well-known/jwks.json",
        "revocation_endpoint": f"{base_url}/oauth/revoke",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "profile", "email"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256", "plain"],
    }