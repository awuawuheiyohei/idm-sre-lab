"""JWT 签发 + 验证 + OAuth 流程数据库操作"""
import json
import secrets
import hashlib
import base64
from datetime import datetime, timezone, timedelta

import jwt

from ..db import get_conn, hash_password, verify_password, get_signing_key


ISSUER = "http://127.0.0.1:5050"
ACCESS_TOKEN_TTL = 3600           # 1 小时
REFRESH_TOKEN_TTL = 30 * 86400    # 30 天
AUTH_CODE_TTL = 600               # 10 分钟
ID_TOKEN_TTL = 3600


# ============================================
# OAuth Client 操作
# ============================================
def get_client(client_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM oauth_clients WHERE client_id=?", (client_id,)).fetchone()
    if not row:
        return None
    d = {k: row[k] for k in row.keys()}
    try:
        d["redirect_uris"] = json.loads(d["redirect_uris"])
        d["grant_types"] = json.loads(d["grant_types"])
        d["scopes"] = json.loads(d["scopes"])
    except Exception:
        pass
    return d


def verify_client_secret(client_id: str, client_secret: str) -> bool:
    c = get_client(client_id)
    if not c:
        return False
    return verify_password(client_secret, c["client_secret"])


def redirect_uri_matches(registered: list, requested: str) -> bool:
    return requested in registered


# ============================================
# User 操作
# ============================================
def get_user_by_username(username: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return {k: row[k] for k in row.keys()} if row else None


def get_user_by_id(user_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return {k: row[k] for k in row.keys()} if row else None


def authenticate_user(username: str, password: str) -> dict | None:
    u = get_user_by_username(username)
    if not u:
        return None
    if not verify_password(password, u["password_hash"]):
        return None
    return u


# ============================================
# Authorization Code
# ============================================
def create_authorization_code(client_id: str, user_id: str, redirect_uri: str,
                               scope: str, code_challenge: str = None,
                               code_challenge_method: str = None) -> str:
    code = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=AUTH_CODE_TTL)).isoformat()
    conn = get_conn()
    conn.execute(
        """INSERT INTO authorization_codes
           (code, client_id, user_id, redirect_uri, scope,
            code_challenge, code_challenge_method, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (code, client_id, user_id, redirect_uri, scope,
         code_challenge, code_challenge_method, expires_at)
    )
    conn.commit()
    return code


def consume_authorization_code(code: str, client_id: str, redirect_uri: str,
                                code_verifier: str = None) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM authorization_codes WHERE code=? AND consumed=0",
        (code,)
    ).fetchone()
    if not row:
        return None
    d = {k: row[k] for k in row.keys()}

    # 验证 client + redirect_uri 匹配
    if d["client_id"] != client_id:
        return None
    if d["redirect_uri"] != redirect_uri:
        return None
    # 过期检查
    expires_at = datetime.fromisoformat(d["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        return None

    # PKCE 验证
    if d["code_challenge"]:
        if not code_verifier:
            return None
        method = d.get("code_challenge_method") or "plain"
        if method == "S256":
            computed = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("utf-8")).digest()
            ).rstrip(b"=").decode("ascii")
        else:  # plain
            computed = code_verifier
        if computed != d["code_challenge"]:
            return None

    # 标记 consumed
    conn.execute("UPDATE authorization_codes SET consumed=1 WHERE code=?", (code,))
    conn.commit()
    return d


# ============================================
# JWT 签发（RS256）
# ============================================
def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _sign_jwt(claims: dict, kid: str) -> str:
    priv, _ = get_signing_key(kid)
    return jwt.encode(claims, priv, algorithm="RS256",
                      headers={"kid": kid})


def issue_access_token(client_id: str, user_id: str, scope: str, kid: str = "key-2026-09") -> str:
    jti = secrets.token_urlsafe(16)
    now = _now_ts()
    claims = {
        "iss": ISSUER,
        "sub": user_id,
        "aud": client_id,
        "client_id": client_id,
        "scope": scope,
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
        "jti": jti,
        "token_type": "access",
    }
    token = _sign_jwt(claims, kid)
    expires_at = datetime.fromtimestamp(now + ACCESS_TOKEN_TTL, tz=timezone.utc).isoformat()
    conn = get_conn()
    conn.execute(
        """INSERT INTO tokens (jti, client_id, user_id, token_type, scope, expires_at)
           VALUES (?, ?, ?, 'access', ?, ?)""",
        (jti, client_id, user_id, scope, expires_at)
    )
    conn.commit()
    return token


def issue_refresh_token(client_id: str, user_id: str, scope: str, kid: str = "key-2026-09") -> str:
    jti = secrets.token_urlsafe(16)
    now = _now_ts()
    claims = {
        "iss": ISSUER,
        "sub": user_id,
        "aud": client_id,
        "client_id": client_id,
        "scope": scope,
        "iat": now,
        "exp": now + REFRESH_TOKEN_TTL,
        "jti": jti,
        "token_type": "refresh",
    }
    token = _sign_jwt(claims, kid)
    expires_at = datetime.fromtimestamp(now + REFRESH_TOKEN_TTL, tz=timezone.utc).isoformat()
    conn = get_conn()
    conn.execute(
        """INSERT INTO tokens (jti, client_id, user_id, token_type, scope, expires_at)
           VALUES (?, ?, ?, 'refresh', ?, ?)""",
        (jti, client_id, user_id, scope, expires_at)
    )
    conn.commit()
    return token


def issue_id_token(client_id: str, user_id: str, scope: str, kid: str = "key-2026-09") -> str:
    """OIDC ID token（包含用户 profile claims）"""
    u = get_user_by_id(user_id)
    if not u:
        raise ValueError("User not found")
    now = _now_ts()
    claims = {
        "iss": ISSUER,
        "sub": user_id,
        "aud": client_id,
        "iat": now,
        "exp": now + ID_TOKEN_TTL,
        "auth_time": now,
        "email": u["email"],
        "email_verified": True,
    }
    if "profile" in scope:
        claims["name"] = u["full_name"]
        claims["preferred_username"] = u["username"]
    return _sign_jwt(claims, kid)


def verify_token(token: str, expected_aud: str = None, expected_token_type: str = None) -> dict:
    """验证 JWT + 检查 revocation"""
    conn = get_conn()
    # 先 decode header 拿 kid
    try:
        header = jwt.get_unverified_header(token)
    except Exception as e:
        raise ValueError(f"Invalid JWT header: {e}")
    kid = header.get("kid")
    if not kid:
        raise ValueError("Missing kid in JWT header")
    pem_jwk = get_signing_key(kid)
    if not pem_jwk:
        raise ValueError(f"Unknown kid: {kid}")
    priv = pem_jwk[0]
    pub_key = priv.public_key()
    # audience=None 时跳过 aud 校验（userinfo endpoint 不强制 aud match）
    decode_opts = {"require": ["exp", "iat", "sub", "iss"]}
    if expected_aud is None:
        decode_opts["verify_aud"] = False
    try:
        claims = jwt.decode(token, pub_key, algorithms=["RS256"],
                            audience=expected_aud if expected_aud else None,
                            issuer=ISSUER, options=decode_opts)
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except jwt.InvalidAudienceError:
        raise ValueError("Invalid audience")
    except jwt.InvalidIssuerError:
        raise ValueError("Invalid issuer")
    except Exception as e:
        raise ValueError(f"JWT verify failed: {e}")

    # 检查 revocation
    jti = claims.get("jti")
    row = conn.execute("SELECT revoked FROM tokens WHERE jti=?", (jti,)).fetchone()
    if not row:
        raise ValueError("Token not registered")
    if row["revoked"] == 1:
        raise ValueError("Token revoked")

    # 类型校验
    if expected_token_type and claims.get("token_type") != expected_token_type:
        raise ValueError(f"Wrong token type: {claims.get('token_type')}")

    return claims


def revoke_token(jti: str) -> bool:
    conn = get_conn()
    cur = conn.execute("UPDATE tokens SET revoked=1 WHERE jti=?", (jti,))
    conn.commit()
    return cur.rowcount > 0


def list_active_tokens(user_id: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        """SELECT jti, client_id, token_type, scope, expires_at, created_at
           FROM tokens WHERE user_id=? AND revoked=0 AND expires_at > datetime('now')
           ORDER BY created_at DESC""",
        (user_id,)
    ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


# ============================================
# Audit
# ============================================
def log_event(conn, action: str, actor: str = None, client_id: str = None,
              user_id: str = None, details: dict = None):
    conn.execute(
        """INSERT INTO oauth_audit (actor, action, client_id, user_id, details)
           VALUES (?, ?, ?, ?, ?)""",
        (actor, action, client_id, user_id, json.dumps(details or {}, ensure_ascii=False))
    )
    conn.commit()


# ============================================
# PKCE verifier helper
# ============================================
def validate_pkce_verifier(verifier: str) -> bool:
    """RFC 7636: verifier 43-128 chars, [A-Z][a-z][0-9]-._~"""
    if not 43 <= len(verifier) <= 128:
        return False
    import re
    return bool(re.match(r"^[A-Za-z0-9\-._~]+$", verifier))