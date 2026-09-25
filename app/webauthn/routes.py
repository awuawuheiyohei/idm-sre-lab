"""
WebAuthn / FIDO2 endpoints（Week 7-8 MVP）：
- POST /webauthn/register/begin — 颁发 challenge + Relying Party info
- POST /webauthn/register/finish — 验证 challenge + 创建 credential
- POST /webauthn/authenticate/begin — 颁发 challenge
- POST /webauthn/authenticate/finish — 验证 challenge + 建 session
- GET /webauthn/credentials — 当前用户已注册 credential 列表
- DELETE /webauthn/credentials/{id} — 注销 credential
"""
from urllib.parse import parse_qs
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request, Cookie, Response
from fastapi.responses import JSONResponse

from ..db import get_conn
from .webauthn_core import (
    _log_audit,
    b64url_encode, b64url_decode,
    generate_challenge, save_challenge, consume_challenge,
    sign_challenge_response, verify_challenge_response,
    save_credential, get_credential, list_credentials_for_user,
    increment_credential_counter, delete_credential,
)

router = APIRouter()


async def _parse_form(request: Request) -> dict:
    body = await request.body()
    if not body:
        return {}
    try:
        return {k: v[0] for k, v in parse_qs(body.decode("utf-8")).items()}
    except Exception:
        try:
            return await request.json()
        except Exception:
            return {}


# ============================================
# 1. Registration Begin
# ============================================
@router.post("/webauthn/register/begin")
async def register_begin(request: Request):
    """颁发 challenge + RP（relying party）信息"""
    body = await _parse_form(request)
    username = body.get("username", "")
    if not username:
        raise HTTPException(400, "Missing username")

    # 查 user
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        raise HTTPException(404, f"User not found: {username}")
    user = {k: row[k] for k in row.keys()}

    # 已注册 credentials
    existing = list_credentials_for_user(user["user_id"])

    # 颁发新 challenge
    challenge = generate_challenge()
    save_challenge(challenge, user["user_id"], "register")

    return {
        "rp": {"id": "idm-sre-lab.local", "name": "IdM SRE Lab"},
        "user": {
            "id": b64url_encode(user["user_id"].encode()),
            "name": user["username"],
            "displayName": user["full_name"],
        },
        "challenge": challenge,
        "pubKeyCredParams": [
            {"type": "public-key", "alg": -7},   # ES256
            {"type": "public-key", "alg": -257}, # RS256
        ],
        "excludeCredentials": [
            {"id": c["credential_id"], "type": "public-key",
             "transports": c.get("transports", [])}
            for c in existing
        ],
        "timeout": 300000,
        "attestation": "none",
        "existing_credentials_count": len(existing),
    }


# ============================================
# 2. Registration Finish
# ============================================
@router.post("/webauthn/register/finish")
async def register_finish(request: Request):
    """验证 challenge + 创建 credential"""
    body = await _parse_form(request)
    username = body.get("username", "")
    challenge = body.get("challenge", "")
    credential_id = body.get("credential_id", "")
    attestation = body.get("attestation", "{}")
    friendly_name = body.get("friendly_name", "")

    if not username or not challenge or not credential_id:
        raise HTTPException(400, "Missing username / challenge / credential_id")

    # 验证 challenge
    chal = consume_challenge(challenge, "register")
    if not chal:
        raise HTTPException(400, "Invalid or expired challenge")
    user_id = chal["user_id"]

    # 简化：base64 编码 challenge 当作 public_key（生产用 COSE 验证）
    public_key = b64url_encode(credential_id.encode())

    # 存 credential
    save_credential(
        credential_id=credential_id,
        user_id=user_id,
        public_key=public_key,
        counter=0,
        aaguid="00000000-0000-0000-0000-000000000000",
        transports=["usb", "nfc", "internal"],
        friendly_name=friendly_name or None,
    )

    _log_audit(action="webauthn_register", entity_id=credential_id,
                actor=username, details={"user_id": user_id, "friendly_name": friendly_name})

    return {
        "status": "registered",
        "credential_id": credential_id,
        "user_id": user_id,
        "friendly_name": friendly_name,
    }


# ============================================
# 3. Authentication Begin
# ============================================
@router.post("/webauthn/authenticate/begin")
async def authenticate_begin(request: Request):
    """颁发 challenge + 用户已注册的 credential allow list"""
    body = await _parse_form(request)
    username = body.get("username", "")
    if not username:
        raise HTTPException(400, "Missing username")

    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        # 防用户名枚举：但 demo 简化不防
        raise HTTPException(404, f"User not found: {username}")
    user = {k: row[k] for k in row.keys()}

    credentials = list_credentials_for_user(user["user_id"])
    if not credentials:
        raise HTTPException(400, "No credentials registered for this user")

    challenge = generate_challenge()
    save_challenge(challenge, user["user_id"], "authenticate")

    return {
        "challenge": challenge,
        "timeout": 300000,
        "rpId": "idm-sre-lab.local",
        "allowCredentials": [
            {"id": c["credential_id"], "type": "public-key",
             "transports": c.get("transports", [])}
            for c in credentials
        ],
        "userVerification": "discouraged",
        "registered_credentials_count": len(credentials),
    }


# ============================================
# 4. Authentication Finish
# ============================================
@router.post("/webauthn/authenticate/finish")
async def authenticate_finish(request: Request, response: Response):
    """验证 challenge + 验证 client signature + 建 session"""
    body = await _parse_form(request)
    username = body.get("username", "")
    challenge = body.get("challenge", "")
    credential_id = body.get("credential_id", "")
    counter = int(body.get("counter", "0"))
    client_signature = body.get("signature", "")

    if not username or not challenge or not credential_id or not client_signature:
        raise HTTPException(400, "Missing required fields")

    # 验证 challenge
    chal = consume_challenge(challenge, "authenticate")
    if not chal:
        raise HTTPException(400, "Invalid or expired challenge")
    user_id = chal["user_id"]

    # 验证 credential 存在
    cred = get_credential(credential_id)
    if not cred:
        raise HTTPException(400, "Unknown credential_id")
    if cred["user_id"] != user_id:
        raise HTTPException(403, "Credential does not belong to this user")

    # 验证 client signature（HMAC over challenge || credential_id || counter）
    if not verify_challenge_response(challenge, credential_id, counter, client_signature):
        raise HTTPException(400, "Invalid signature")

    # 验证 counter 必须 > stored counter（防 replay）
    if counter <= cred["counter"]:
        raise HTTPException(400, f"Counter must be > {cred['counter']} (replay protection)")

    new_counter = increment_credential_counter(credential_id)

    # 建 session cookie
    session_id = "WEBAUTHN-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + credential_id[:8]

    _log_audit(action="webauthn_authenticate", entity_id=credential_id,
                actor=username, details={"user_id": user_id, "new_counter": new_counter})

    response = JSONResponse({
        "status": "authenticated",
        "user_id": user_id,
        "credential_id": credential_id,
        "new_counter": new_counter,
        "session_id": session_id,
    })
    response.set_cookie(
        key="webauthn_session", value=session_id,
        httponly=True, samesite="strict", path="/", max_age=8 * 3600
    )
    return response


# ============================================
# 5. List credentials (debug)
# ============================================
@router.get("/webauthn/credentials/{username}")
async def list_credentials(username: str):
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        raise HTTPException(404, f"User not found: {username}")
    credentials = list_credentials_for_user(row["user_id"])
    return {"username": username, "count": len(credentials), "credentials": credentials}


# ============================================
# 6. Delete credential
# ============================================
@router.delete("/webauthn/credentials/{credential_id}")
async def delete_credential_endpoint(credential_id: str, request: Request):
    body = await _parse_form(request)
    username = body.get("username", "")
    if not username:
        raise HTTPException(400, "Missing username")
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        raise HTTPException(404, f"User not found: {username}")
    ok = delete_credential(credential_id, row["user_id"])
    if not ok:
        raise HTTPException(404, "Credential not found for this user")
    _log_audit(action="webauthn_delete_credential", entity_id=credential_id,
                actor=username, details={"user_id": row["user_id"]})
    return {"status": "deleted", "credential_id": credential_id}