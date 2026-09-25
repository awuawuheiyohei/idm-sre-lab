"""
IdM SRE Lab - SAML 2.0 MVP tests
- SP + IdP metadata XML 结构
- SP-initiated AuthnRequest → IdP login → SAML Response → ACS verify
- Session 创建 + cookie
- SLO 流程
"""
import base64
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
# Metadata XML
# ============================================
def test_sp_metadata(client):
    r = client.get("/saml/metadata")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/samlmetadata+xml")
    xml = r.text
    assert "EntityDescriptor" in xml
    assert "SPSSODescriptor" in xml
    assert "AssertionConsumerService" in xml
    assert "SingleLogoutService" in xml
    assert "tripbiz-booking.local" in xml


def test_idp_metadata(client):
    r = client.get("/saml/idp-metadata")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/samlmetadata+xml")
    xml = r.text
    assert "EntityDescriptor" in xml
    assert "IDPSSODescriptor" in xml
    assert "SingleSignOnService" in xml
    assert "idm-sre-lab.local" in xml


# ============================================
# SP-initiated Login
# ============================================
def test_sp_login_redirects_to_idp(client):
    r = client.get("/saml/login?RelayState=/dashboard", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("/saml/idp/sso?")
    assert "SAMLRequest=" in loc
    assert "RelayState=/dashboard" in loc


def test_idp_sso_get_returns_form(client):
    # 先拿一个 SAMLRequest
    r = client.get("/saml/login?RelayState=/test", follow_redirects=False)
    saml_req = r.headers["location"].split("SAMLRequest=", 1)[1].split("&")[0]
    # 用 SAMLRequest 去 IdP
    r2 = client.get(f"/saml/idp/sso?SAMLRequest={saml_req}&RelayState=/test")
    assert r2.status_code == 200
    assert "Mock SAML IdP" in r2.text
    assert "engineer01" in r2.text


def test_idp_login_invalid(client):
    r = client.get("/saml/login", follow_redirects=False)
    saml_req = r.headers["location"].split("SAMLRequest=", 1)[1].split("&")[0]
    r2 = client.post("/saml/idp/sso",
                     data={"SAMLRequest": saml_req, "RelayState": "/x",
                           "username": "engineer01", "password": "WRONG"})
    assert r2.status_code == 401


# ============================================
# 完整 SSO 流程
# ============================================
def test_full_sso_flow(client):
    # 1. SP login → SAMLRequest
    r = client.get("/saml/login?RelayState=/dashboard", follow_redirects=False)
    assert r.status_code == 302
    saml_req = r.headers["location"].split("SAMLRequest=", 1)[1].split("&")[0]

    # 2. IdP 颁发 SAMLResponse
    r2 = client.post("/saml/idp/sso",
                     data={"SAMLRequest": saml_req, "RelayState": "/dashboard",
                           "username": "engineer01", "password": "Engineer@2026"},
                     follow_redirects=False)
    assert r2.status_code == 302
    saml_resp = r2.headers["location"].split("SAMLResponse=", 1)[1].split("&")[0]
    assert saml_resp  # 非空

    # 3. ACS 验证 + 建 session
    r3 = client.get(f"/saml/acs?SAMLResponse={saml_resp}&RelayState=/dashboard",
                    follow_redirects=False)
    assert r3.status_code == 302
    assert r3.headers["location"] == "/dashboard"
    assert "saml_session" in r3.cookies

    # 4. Userinfo with cookie
    r4 = client.get("/saml/userinfo")
    assert r4.status_code == 200
    d = r4.json()
    assert d["name_id"] == "engineer01@tripbiz.com"
    assert d["user_id"] == "USER-001"
    assert d["attributes"]["email"] == "engineer01@tripbiz.com"
    assert d["attributes"]["role"] == "employee"
    assert d["attributes"]["business_unit"] == "platform"


def test_full_sso_with_admin(client):
    """admin 用户完整流程"""
    r = client.get("/saml/login", follow_redirects=False)
    saml_req = r.headers["location"].split("SAMLRequest=", 1)[1].split("&")[0]
    r2 = client.post("/saml/idp/sso",
                     data={"SAMLRequest": saml_req, "RelayState": "/",
                           "username": "admin01", "password": "Admin@2026"},
                     follow_redirects=False)
    assert r2.status_code == 302
    saml_resp = r2.headers["location"].split("SAMLResponse=", 1)[1].split("&")[0]
    r3 = client.get(f"/saml/acs?SAMLResponse={saml_resp}", follow_redirects=False)
    assert r3.status_code == 302
    r4 = client.get("/saml/userinfo")
    assert r4.json()["attributes"]["role"] == "it_admin"


# ============================================
# SAML Response 验证
# ============================================
def test_saml_response_invalid(client):
    """篡改的 SAMLResponse 应该 fail"""
    r = client.get("/saml/acs?SAMLResponse=INVALID_BASE64&RelayState=/x",
                    follow_redirects=False)
    assert r.status_code == 400


def test_saml_response_signature_mismatch(client):
    """篡改后的 SAMLResponse signature 应该 fail"""
    # 先拿一个 valid response
    r = client.get("/saml/login", follow_redirects=False)
    saml_req = r.headers["location"].split("SAMLRequest=", 1)[1].split("&")[0]
    r2 = client.post("/saml/idp/sso",
                     data={"SAMLRequest": saml_req, "RelayState": "/x",
                           "username": "engineer01", "password": "Engineer@2026"},
                     follow_redirects=False)
    saml_resp = r2.headers["location"].split("SAMLResponse=", 1)[1].split("&")[0]
    # 篡改一个字符（base64 末尾的 x → y）
    tampered = saml_resp[:-1] + ("y" if saml_resp[-1] != "y" else "z")
    r3 = client.get(f"/saml/acs?SAMLResponse={tampered}", follow_redirects=False)
    # HMAC 应该失败 → 400
    assert r3.status_code == 400


# ============================================
# Session + SLO
# ============================================
def test_userinfo_without_cookie(client):
    r = client.get("/saml/userinfo")
    assert r.status_code == 401


def test_sessions_list(client):
    r = client.get("/saml/login", follow_redirects=False)
    saml_req = r.headers["location"].split("SAMLRequest=", 1)[1].split("&")[0]
    r2 = client.post("/saml/idp/sso",
                     data={"SAMLRequest": saml_req, "RelayState": "/",
                           "username": "engineer01", "password": "Engineer@2026"},
                     follow_redirects=False)
    saml_resp = r2.headers["location"].split("SAMLResponse=", 1)[1].split("&")[0]
    client.get(f"/saml/acs?SAMLResponse={saml_resp}")
    r3 = client.get("/saml/sessions")
    assert r3.status_code == 200
    assert len(r3.json()["active_sessions"]) >= 1


def test_slo_logout(client):
    r = client.get("/saml/login", follow_redirects=False)
    saml_req = r.headers["location"].split("SAMLRequest=", 1)[1].split("&")[0]
    r2 = client.post("/saml/idp/sso",
                     data={"SAMLRequest": saml_req, "RelayState": "/",
                           "username": "engineer01", "password": "Engineer@2026"},
                     follow_redirects=False)
    saml_resp = r2.headers["location"].split("SAMLResponse=", 1)[1].split("&")[0]
    client.get(f"/saml/acs?SAMLResponse={saml_resp}")
    # SLO
    r3 = client.post("/saml/slo")
    assert r3.status_code == 200
    assert r3.json()["status"] == "logged_out"
    # SLO 后 userinfo 401
    r4 = client.get("/saml/userinfo")
    assert r4.status_code == 401


# ============================================
# SAML Audit
# ============================================
def test_saml_audit_records_flow(client):
    r = client.get("/saml/login", follow_redirects=False)
    saml_req = r.headers["location"].split("SAMLRequest=", 1)[1].split("&")[0]
    r2 = client.post("/saml/idp/sso",
                     data={"SAMLRequest": saml_req, "RelayState": "/",
                           "username": "engineer01", "password": "Engineer@2026"},
                     follow_redirects=False)
    saml_resp = r2.headers["location"].split("SAMLResponse=", 1)[1].split("&")[0]
    client.get(f"/saml/acs?SAMLResponse={saml_resp}")
    client.post("/saml/slo")
    r = client.get("/saml/audit?limit=20")
    items = r.json()["items"]
    actions = {x["action"] for x in items}
    assert "authn_request" in actions
    assert "assertion_issued" in actions
    assert "sso_completed" in actions
    assert "slo_completed" in actions


# ============================================
# Module-level unit tests（saml_core）
# ============================================
def test_sign_verify_xml_roundtrip(client):
    """简化 HMAC 签名往返 OK"""
    from app.saml.saml_core import sign_xml, verify_signature
    xml_bytes = b"<root><user>engineer01</user></root>"
    sig = sign_xml(xml_bytes, b"secret-123")
    assert verify_signature(xml_bytes, sig, b"secret-123")
    # 错的 secret 应该失败
    assert not verify_signature(xml_bytes, sig, b"wrong-secret")
    # 错的 XML 应该失败
    assert not verify_signature(b"<root/>", sig, b"secret-123")


def test_build_metadata_xml_structure(client):
    """metadata XML 应该包含 SPSSODescriptor / IDPSSODescriptor"""
    from app.saml.saml_core import build_sp_metadata, build_idp_metadata
    sp_xml = build_sp_metadata("SP-001", "http://127.0.0.1:5050")
    assert 'SPSSODescriptor' in sp_xml
    assert 'AssertionConsumerService' in sp_xml
    assert 'tripbiz-booking.local' in sp_xml

    idp_xml = build_idp_metadata("IDP-001")
    assert 'IDPSSODescriptor' in idp_xml
    assert 'SingleSignOnService' in idp_xml
    assert 'idm-sre-lab.local' in idp_xml


def test_build_authn_request_includes_issuer(client):
    from app.saml.saml_core import build_authn_request
    plain_b64, request_id = build_authn_request("SP-001", "IDP-001", "/dashboard")
    xml = base64.b64decode(plain_b64).decode("utf-8")
    assert 'AuthnRequest' in xml
    assert 'tripbiz-booking.local' in xml
    assert 'AssertionConsumerServiceURL' in xml
    assert 'ForceAuthn' in xml  # 默认 false
    assert request_id.startswith("_")