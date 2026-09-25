"""
IdM SRE Lab - Week 7-10 (WebAuthn + Devices) tests
- WebAuthn: challenge-response (HMAC) + credential lifecycle
- Devices: REGISTERED → ACTIVE → COMPLIANT → RETIRED → LOST
"""
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
# WebAuthn - Registration
# ============================================
def test_webauthn_register_begin(client):
    r = client.post("/webauthn/register/begin", data={"username": "engineer01"})
    assert r.status_code == 200
    d = r.json()
    assert "challenge" in d
    assert len(d["challenge"]) > 20
    assert d["rp"]["id"] == "idm-sre-lab.local"
    assert d["user"]["name"] == "engineer01"
    assert d["existing_credentials_count"] == 0


def test_webauthn_register_begin_unknown_user(client):
    r = client.post("/webauthn/register/begin", data={"username": "nobody"})
    assert r.status_code == 404


def test_webauthn_register_finish(client):
    # Begin
    r = client.post("/webauthn/register/begin", data={"username": "engineer01"})
    challenge = r.json()["challenge"]
    cred_id = "cred_test_001"

    r2 = client.post("/webauthn/register/finish", data={
        "username": "engineer01",
        "challenge": challenge,
        "credential_id": cred_id,
        "friendly_name": "YubiKey 5C",
    })
    assert r2.status_code == 200
    assert r2.json()["status"] == "registered"
    assert r2.json()["credential_id"] == cred_id


def test_webauthn_register_finish_invalid_challenge(client):
    r = client.post("/webauthn/register/finish", data={
        "username": "engineer01",
        "challenge": "BOGUS_CHALLENGE",
        "credential_id": "cred_test_002",
    })
    assert r.status_code == 400


# ============================================
# WebAuthn - Authentication
# ============================================
def test_webauthn_full_flow(client):
    # Register
    r = client.post("/webauthn/register/begin", data={"username": "engineer01"})
    challenge = r.json()["challenge"]
    cred_id = "cred_auth_test"
    client.post("/webauthn/register/finish", data={
        "username": "engineer01",
        "challenge": challenge,
        "credential_id": cred_id,
    })

    # Authenticate begin
    r2 = client.post("/webauthn/authenticate/begin", data={"username": "engineer01"})
    assert r2.status_code == 200
    auth_chal = r2.json()["challenge"]
    assert r2.json()["registered_credentials_count"] == 1

    # Compute signature (client side)
    from app.webauthn.webauthn_core import sign_challenge_response
    sig = sign_challenge_response(auth_chal, cred_id, 1)

    # Authenticate finish
    r3 = client.post("/webauthn/authenticate/finish", data={
        "username": "engineer01",
        "challenge": auth_chal,
        "credential_id": cred_id,
        "counter": "1",
        "signature": sig,
    })
    assert r3.status_code == 200
    d = r3.json()
    assert d["status"] == "authenticated"
    assert d["new_counter"] == 1
    assert "webauthn_session" in r3.cookies


def test_webauthn_auth_no_credentials(client):
    """User without credentials should fail at authenticate_begin"""
    # admin 没有注册 credential
    r = client.post("/webauthn/authenticate/begin", data={"username": "admin01"})
    assert r.status_code == 400


def test_webauthn_signature_mismatch(client):
    r = client.post("/webauthn/register/begin", data={"username": "engineer01"})
    challenge = r.json()["challenge"]
    cred_id = "cred_sig_test"
    client.post("/webauthn/register/finish", data={
        "username": "engineer01", "challenge": challenge, "credential_id": cred_id,
    })
    r2 = client.post("/webauthn/authenticate/begin", data={"username": "engineer01"})
    auth_chal = r2.json()["challenge"]
    # 错误签名
    r3 = client.post("/webauthn/authenticate/finish", data={
        "username": "engineer01",
        "challenge": auth_chal,
        "credential_id": cred_id,
        "counter": "1",
        "signature": "A" * 32,
    })
    assert r3.status_code == 400


def test_webauthn_replay_counter(client):
    r = client.post("/webauthn/register/begin", data={"username": "engineer01"})
    challenge = r.json()["challenge"]
    cred_id = "cred_replay"
    client.post("/webauthn/register/finish", data={
        "username": "engineer01", "challenge": challenge, "credential_id": cred_id,
    })
    # 第一次 auth（counter=1）
    r2 = client.post("/webauthn/authenticate/begin", data={"username": "engineer01"})
    auth_chal = r2.json()["challenge"]
    from app.webauthn.webauthn_core import sign_challenge_response
    sig = sign_challenge_response(auth_chal, cred_id, 1)
    r3 = client.post("/webauthn/authenticate/finish", data={
        "username": "engineer01", "challenge": auth_chal,
        "credential_id": cred_id, "counter": "1", "signature": sig,
    })
    assert r3.status_code == 200

    # Replay: 用同样的 counter=1 重放（应该 fail）
    r4 = client.post("/webauthn/authenticate/begin", data={"username": "engineer01"})
    auth_chal2 = r4.json()["challenge"]
    sig2 = sign_challenge_response(auth_chal2, cred_id, 1)
    r5 = client.post("/webauthn/authenticate/finish", data={
        "username": "engineer01", "challenge": auth_chal2,
        "credential_id": cred_id, "counter": "1", "signature": sig2,
    })
    assert r5.status_code == 400


def test_webauthn_list_credentials(client):
    r = client.post("/webauthn/register/begin", data={"username": "engineer01"})
    challenge = r.json()["challenge"]
    client.post("/webauthn/register/finish", data={
        "username": "engineer01", "challenge": challenge,
        "credential_id": "cred_list_1",
    })
    r2 = client.get("/webauthn/credentials/engineer01")
    assert r2.status_code == 200
    assert r2.json()["count"] == 1


def test_webauthn_delete_credential(client):
    r = client.post("/webauthn/register/begin", data={"username": "engineer01"})
    challenge = r.json()["challenge"]
    client.post("/webauthn/register/finish", data={
        "username": "engineer01", "challenge": challenge,
        "credential_id": "cred_del",
    })
    r2 = client.request(
        "DELETE",
        "/webauthn/credentials/cred_del",
        data={"username": "engineer01"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "deleted"
    # 确认已删除
    r3 = client.get("/webauthn/credentials/engineer01")
    assert r3.json()["count"] == 0


# ============================================
# Devices Provisioning
# ============================================
def test_device_register(client):
    r = client.post("/devices", data={
        "device_name": "李工 ThinkPad T14",
        "user_id": "USER-001",
        "device_type": "LAPTOP",
        "os": "Windows 11 Pro",
        "serial_number": "PF12345AB",
        "manufacturer": "Lenovo",
        "model": "ThinkPad T14",
        "business_unit": "platform",
    })
    assert r.status_code == 200
    d = r.json()["device"]
    assert d["status"] == "REGISTERED"
    assert d["compliance_state"] == "PENDING"
    assert d["device_id"].startswith("DEV-")


def test_device_register_duplicate_serial(client):
    base = {"device_name": "test", "user_id": "USER-001",
            "device_type": "LAPTOP", "os": "Win", "serial_number": "SN-DUP"}
    client.post("/devices", data=base)
    r = client.post("/devices", data=base)
    assert r.status_code == 400


def test_device_register_unknown_user(client):
    r = client.post("/devices", data={
        "device_name": "test", "user_id": "USER-999",
        "device_type": "LAPTOP", "os": "Win", "serial_number": "SN-X",
    })
    assert r.status_code == 400


def test_device_get(client):
    r = client.post("/devices", data={
        "device_name": "test", "user_id": "USER-001",
        "device_type": "LAPTOP", "os": "Win", "serial_number": "SN-001",
    })
    dev_id = r.json()["device"]["device_id"]
    r2 = client.get(f"/devices/{dev_id}")
    assert r2.status_code == 200
    assert r2.json()["device_id"] == dev_id


def test_device_get_404(client):
    r = client.get("/devices/DEV-DOES-NOT-EXIST")
    assert r.status_code == 404


def test_device_activate_lifecycle(client):
    # Register
    r = client.post("/devices", data={
        "device_name": "test", "user_id": "USER-001",
        "device_type": "LAPTOP", "os": "Win", "serial_number": "SN-ACT",
    })
    dev_id = r.json()["device"]["device_id"]

    # REGISTERED → ACTIVE
    r2 = client.post(f"/devices/{dev_id}/activate")
    assert r2.status_code == 200
    assert r2.json()["device"]["status"] == "ACTIVE"
    assert r2.json()["device"]["compliance_state"] == "COMPLIANT"

    # 再次 activate 应 fail（已 ACTIVE）
    r3 = client.post(f"/devices/{dev_id}/activate")
    assert r3.status_code == 400


def test_device_compliance_update(client):
    r = client.post("/devices", data={
        "device_name": "test", "user_id": "USER-001",
        "device_type": "LAPTOP", "os": "Win", "serial_number": "SN-CMP",
    })
    dev_id = r.json()["device"]["device_id"]
    r2 = client.post(f"/devices/{dev_id}/compliance",
                     data={"compliance_state": "NON_COMPLIANT"})
    assert r2.status_code == 200
    assert r2.json()["device"]["compliance_state"] == "NON_COMPLIANT"


def test_device_compliance_invalid(client):
    r = client.post("/devices", data={
        "device_name": "test", "user_id": "USER-001",
        "device_type": "LAPTOP", "os": "Win", "serial_number": "SN-INV",
    })
    dev_id = r.json()["device"]["device_id"]
    r2 = client.post(f"/devices/{dev_id}/compliance",
                     data={"compliance_state": "INVALID_STATE"})
    assert r2.status_code == 400


def test_device_retire(client):
    r = client.post("/devices", data={
        "device_name": "test", "user_id": "USER-001",
        "device_type": "LAPTOP", "os": "Win", "serial_number": "SN-RT",
    })
    dev_id = r.json()["device"]["device_id"]
    r2 = client.post(f"/devices/{dev_id}/retire", data={"reason": "end_of_life"})
    assert r2.status_code == 200
    assert r2.json()["device"]["status"] == "RETIRED"


def test_device_mark_lost(client):
    r = client.post("/devices", data={
        "device_name": "test", "user_id": "USER-001",
        "device_type": "PHONE", "os": "iOS", "serial_number": "SN-LST",
    })
    dev_id = r.json()["device"]["device_id"]
    r2 = client.post(f"/devices/{dev_id}/mark-lost")
    assert r2.status_code == 200
    assert r2.json()["device"]["status"] == "LOST"


def test_device_check_in(client):
    r = client.post("/devices", data={
        "device_name": "test", "user_id": "USER-001",
        "device_type": "LAPTOP", "os": "Win", "serial_number": "SN-CI",
    })
    dev_id = r.json()["device"]["device_id"]
    r2 = client.post(f"/devices/{dev_id}/check-in")
    assert r2.status_code == 200
    assert r2.json()["last_check_in"] is not None


def test_device_list_filter(client):
    client.post("/devices", data={
        "device_name": "d1", "user_id": "USER-001",
        "device_type": "LAPTOP", "os": "Win", "serial_number": "SN-L1",
        "business_unit": "platform",
    })
    client.post("/devices", data={
        "device_name": "d2", "user_id": "USER-002",
        "device_type": "PHONE", "os": "iOS", "serial_number": "SN-L2",
        "business_unit": "commercial-vehicle",
    })
    r = client.get("/devices")
    assert r.json()["count"] == 2
    r2 = client.get("/devices?user_id=USER-001")
    assert r2.json()["count"] == 1
    r3 = client.get("/devices?business_unit=commercial-vehicle")
    assert r3.json()["count"] == 1


def test_device_portfolio(client):
    client.post("/devices", data={
        "device_name": "d1", "user_id": "USER-001",
        "device_type": "LAPTOP", "os": "Win", "serial_number": "SN-P1",
        "business_unit": "platform",
    })
    client.post("/devices", data={
        "device_name": "d2", "user_id": "USER-002",
        "device_type": "PHONE", "os": "iOS", "serial_number": "SN-P2",
        "business_unit": "commercial-vehicle",
    })
    r = client.get("/devices/portfolio/stats")
    assert r.status_code == 200
    d = r.json()
    assert d["total_devices"] == 2
    assert any(x["status"] == "REGISTERED" for x in d["by_status"])


def test_device_audit(client):
    r = client.post("/devices", data={
        "device_name": "d1", "user_id": "USER-001",
        "device_type": "LAPTOP", "os": "Win", "serial_number": "SN-A1",
    })
    dev_id = r.json()["device"]["device_id"]
    client.post(f"/devices/{dev_id}/activate")
    r2 = client.get("/devices-audit?limit=10")
    assert r2.status_code == 200
    actions = {x["action"] for x in r2.json()["items"]}
    assert "device_registered" in actions
    assert "device_activated" in actions