"""
IdM SRE Lab - OAuth2/OIDC MVP tests
- End-to-end OAuth flow: authorize → token → userinfo
- PKCE S256
- refresh_token rotation
- revoke (RFC 7009)
- audit trail
- discovery + JWKS
"""
import base64
import hashlib
import secrets
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


# ============================================
# Health + Discovery + JWKS
# ============================================
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["service"] == "idm-sre-lab"


def test_discovery(client):
    r = client.get("/.well-known/openid-configuration")
    assert r.status_code == 200
    d = r.json()
    assert "authorization_endpoint" in d
    assert "token_endpoint" in d
    assert "userinfo_endpoint" in d
    assert "jwks_uri" in d
    assert "revocation_endpoint" in d
    assert "RS256" in d["id_token_signing_alg_values_supported"]
    assert "authorization_code" in d["grant_types_supported"]


def test_jwks(client):
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200
    d = r.json()
    assert len(d["keys"]) >= 1
    k = d["keys"][0]
    assert k["kty"] == "RSA"
    assert k["alg"] == "RS256"
    assert k["use"] == "sig"
    assert "n" in k
    assert "e" in k


# ============================================
# Authorize + Login
# ============================================
def test_authorize_get_returns_form(client):
    r = client.get("/oauth/authorize", params={
        "client_id": "tripbiz-booking-app",
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "response_type": "code",
        "scope": "openid profile email",
        "state": "xyz123",
    })
    assert r.status_code == 200
    assert "Sign in" in r.text
    assert "engineer01" in r.text  # demo creds visible


def test_authorize_unknown_client(client):
    r = client.get("/oauth/authorize", params={
        "client_id": "bogus",
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "response_type": "code",
    })
    assert r.status_code == 400


def test_authorize_invalid_redirect(client):
    r = client.get("/oauth/authorize", params={
        "client_id": "tripbiz-booking-app",
        "redirect_uri": "http://evil.com/callback",
        "response_type": "code",
    })
    assert r.status_code == 400


def test_authorize_login_success(client):
    r = client.post("/oauth/authorize", data={
        "username": "engineer01",
        "password": "Engineer@2026",
        "client_id": "tripbiz-booking-app",
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "scope": "openid profile email",
        "state": "xyz123",
    }, follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("http://127.0.0.1:5050/callback?")
    assert "code=" in loc
    assert "state=xyz123" in loc


def test_authorize_login_fail(client):
    r = client.post("/oauth/authorize", data={
        "username": "engineer01",
        "password": "WRONG",
        "client_id": "tripbiz-booking-app",
        "redirect_uri": "http://127.0.0.1:5050/callback",
    })
    assert r.status_code == 401


def test_authorize_response_type_invalid(client):
    r = client.get("/oauth/authorize", params={
        "client_id": "tripbiz-booking-app",
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "response_type": "token",
    })
    assert r.status_code == 400


# ============================================
# Token Exchange
# ============================================
def _login_and_get_code(client, username="engineer01", password="Engineer@2026",
                        scope="openid profile email"):
    r = client.post("/oauth/authorize", data={
        "username": username, "password": password,
        "client_id": "tripbiz-booking-app",
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "scope": scope,
    }, follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    return loc.split("code=", 1)[1].split("&")[0]


def test_token_exchange_authorization_code(client):
    code = _login_and_get_code(client)
    r = client.post("/oauth/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["token_type"] == "Bearer"
    assert d["expires_in"] == 3600
    assert d["scope"] == "openid profile email"
    assert "access_token" in d
    assert "refresh_token" in d
    assert "id_token" in d  # OIDC includes id_token


def test_token_exchange_invalid_code(client):
    r = client.post("/oauth/token", data={
        "grant_type": "authorization_code",
        "code": "BOGUS_CODE",
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
    })
    assert r.status_code == 400


def test_token_exchange_wrong_client_secret(client):
    code = _login_and_get_code(client)
    r = client.post("/oauth/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "client_id": "tripbiz-booking-app",
        "client_secret": "WRONG_SECRET",
    })
    assert r.status_code == 401


def test_token_exchange_code_reuse(client):
    """auth code 只能换一次 token"""
    code = _login_and_get_code(client)
    # 第一次成功
    r1 = client.post("/oauth/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
    })
    assert r1.status_code == 200
    # 第二次失败（consumed）
    r2 = client.post("/oauth/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
    })
    assert r2.status_code == 400


def test_token_exchange_basic_auth(client):
    """Basic auth 替代 client_secret_post"""
    code = _login_and_get_code(client)
    basic = base64.b64encode(b"tripbiz-booking-app:tripbiz-booking-app-secret-2026").decode()
    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://127.0.0.1:5050/callback",
        },
        headers={"Authorization": f"Basic {basic}"},
    )
    assert r.status_code == 200


# ============================================
# Userinfo
# ============================================
def _exchange_code(client, code):
    r = client.post("/oauth/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
    })
    return r.json()


def test_userinfo_full_scope(client):
    code = _login_and_get_code(client)
    tok = _exchange_code(client, code)
    r = client.get("/oauth/userinfo", headers={
        "Authorization": f"Bearer {tok['access_token']}"
    })
    assert r.status_code == 200
    d = r.json()
    assert d["sub"] == "USER-001"
    assert d["email"] == "engineer01@tripbiz.com"
    assert d["email_verified"] is True
    assert d["preferred_username"] == "engineer01"
    assert d["name"] == "李工 (Engineer)"
    assert d["role"] == "employee"


def test_userinfo_email_only(client):
    code = _login_and_get_code(client, scope="openid email")
    tok = _exchange_code(client, code)
    r = client.get("/oauth/userinfo", headers={
        "Authorization": f"Bearer {tok['access_token']}"
    })
    d = r.json()
    assert d["email"] == "engineer01@tripbiz.com"
    assert "name" not in d  # 没 profile scope


def test_userinfo_no_bearer(client):
    r = client.get("/oauth/userinfo")
    assert r.status_code == 401


def test_userinfo_invalid_bearer(client):
    r = client.get("/oauth/userinfo", headers={"Authorization": "Bearer BOGUS"})
    assert r.status_code == 401


# ============================================
# Refresh Token Rotation
# ============================================
def test_refresh_token_rotation(client):
    code = _login_and_get_code(client)
    tok = _exchange_code(client, code)
    old_refresh = tok["refresh_token"]
    r = client.post("/oauth/token", data={
        "grant_type": "refresh_token",
        "refresh_token": old_refresh,
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["refresh_token"] != old_refresh  # rotated
    # 旧 refresh 已 revoked
    r2 = client.post("/oauth/token", data={
        "grant_type": "refresh_token",
        "refresh_token": old_refresh,
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
    })
    assert r2.status_code == 400


# ============================================
# Revoke (RFC 7009)
# ============================================
def test_revoke_access_token(client):
    code = _login_and_get_code(client)
    tok = _exchange_code(client, code)
    basic = base64.b64encode(b"tripbiz-booking-app:tripbiz-booking-app-secret-2026").decode()
    r = client.post("/oauth/revoke",
                    data={"token": tok["access_token"]},
                    headers={"Authorization": f"Basic {basic}"})
    assert r.status_code == 200
    # revoke 后 userinfo 应该 fail
    r2 = client.get("/oauth/userinfo", headers={
        "Authorization": f"Bearer {tok['access_token']}"
    })
    assert r2.status_code == 401


def test_revoke_unknown_token_returns_200(client):
    """RFC 7009: 即使 token 无效也返回 200（防探测）"""
    basic = base64.b64encode(b"tripbiz-booking-app:tripbiz-booking-app-secret-2026").decode()
    r = client.post("/oauth/revoke",
                    data={"token": "BOGUS_TOKEN"},
                    headers={"Authorization": f"Basic {basic}"})
    assert r.status_code == 200


# ============================================
# PKCE (RFC 7636)
# ============================================
def _make_pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def test_pkce_s256_flow(client):
    verifier, challenge = _make_pkce_pair()
    r = client.post("/oauth/authorize", data={
        "username": "engineer01", "password": "Engineer@2026",
        "client_id": "tripbiz-booking-app",
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "scope": "openid email",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }, follow_redirects=False)
    assert r.status_code == 302
    code = r.headers["location"].split("code=", 1)[1].split("&")[0]
    # 正确 verifier → 成功
    r2 = client.post("/oauth/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
        "code_verifier": verifier,
    })
    assert r2.status_code == 200
    assert "access_token" in r2.json()


def test_pkce_wrong_verifier_rejected(client):
    """错误 verifier → 400"""
    verifier, challenge = _make_pkce_pair()
    r = client.post("/oauth/authorize", data={
        "username": "engineer01", "password": "Engineer@2026",
        "client_id": "tripbiz-booking-app",
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "scope": "openid email",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }, follow_redirects=False)
    assert r.status_code == 302
    code = r.headers["location"].split("code=", 1)[1].split("&")[0]
    # 错误的 verifier → 400
    wrong_verifier, _ = _make_pkce_pair()
    r2 = client.post("/oauth/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "http://127.0.0.1:5050/callback",
        "client_id": "tripbiz-booking-app",
        "client_secret": "tripbiz-booking-app-secret-2026",
        "code_verifier": wrong_verifier,
    })
    assert r2.status_code == 400


# ============================================
# Audit
# ============================================
def test_audit_trail_records_login(client):
    code = _login_and_get_code(client)
    tok = _exchange_code(client, code)
    r = client.get("/oauth/audit?limit=20")
    items = r.json()["items"]
    actions = {x["action"] for x in items}
    assert "login_success" in actions
    assert "auth_code_issued" in actions
    assert "token_issued" in actions


# ============================================
# Static Dashboard (smoke: 404 expected since no static yet)
# ============================================
def test_main_root(client):
    r = client.get("/")
    assert r.status_code == 200
    d = r.json()
    assert d["service"] == "IdM SRE Lab"
    assert d["week"] == "9-10"