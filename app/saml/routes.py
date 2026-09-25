"""
SAML 2.0 endpoints（Week 5-6 MVP）：
- GET /saml/metadata — SP metadata XML（demo SP）
- GET /saml/idp-metadata — IdP metadata XML（self-hosted IdP）
- GET /saml/login?RelayState=... — SP-initiated AuthnRequest → IdP redirect
- GET /saml/idp/sso — IdP 模拟登录页（POST 接 SAMLRequest + RelayState）
- POST /saml/idp/sso — IdP 签发 SAML Response → 302 redirect to SP ACS
- POST /saml/acs — Assertion Consumer Service（SP 侧）
- GET /saml/userinfo — 已登录用户拿 profile（带 session cookie）
- GET /saml/sessions — 当前用户所有活跃 SAML session
- POST /saml/slo — Single Logout（本地 session 清除）

简化设计：
- 自建 IdP 同一进程模拟两端
- 用 cookie 跟踪 session（HttpOnly + SameSite=Strict）
- 简化签名：HMAC over canonical XML（生产用 XML-DSig）
"""
import secrets
from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Query, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from ..db import get_conn
from ..models.oauth_store import authenticate_user, get_user_by_id
from .saml_core import (
    SAML_PROTOCOL_NS, SAML_ASSERTION_NS, SAML_METADATA_NS,
    build_sp_metadata, build_idp_metadata, build_authn_request,
    build_saml_response, parse_saml_response,
    save_saml_session, get_saml_session, list_user_sessions, delete_session,
    log_event, b64encode, b64decode, deflate_then_b64, b64_then_inflate,
)

router = APIRouter()

DEMO_SP_ID = "SP-001"   # demo IdP 引用 SP
DEMO_IDP_ID = "IDP-001"


async def _parse_form(request: Request) -> dict:
    """手写 url-encoded parser（PEP 668 兼容）"""
    from urllib.parse import parse_qs
    body = await request.body()
    if not body:
        return {}
    try:
        return {k: v[0] for k, v in parse_qs(body.decode("utf-8")).items()}
    except Exception as e:
        raise HTTPException(400, f"Invalid form body: {e}")


# ============================================
# 1. SP Metadata
# ============================================
@router.get("/saml/metadata")
async def sp_metadata():
    xml = build_sp_metadata(DEMO_SP_ID, "http://127.0.0.1:5050")
    return Response(content=xml, media_type="application/samlmetadata+xml")


# ============================================
# 2. IdP Metadata
# ============================================
@router.get("/saml/idp-metadata")
async def idp_metadata():
    xml = build_idp_metadata(DEMO_IDP_ID)
    return Response(content=xml, media_type="application/samlmetadata+xml")


# ============================================
# 3. SP-initiated Login → AuthnRequest → IdP redirect
# ============================================
@router.get("/saml/login")
async def sp_login(RelayState: str = Query(default="")):
    plain_b64, request_id = build_authn_request(DEMO_SP_ID, DEMO_IDP_ID,
                                                relay_state=RelayState)
    # HTTP-Redirect binding: SAMLRequest 用 DEFLATE + base64（简化版直接 base64）
    redirect_url = f"/saml/idp/sso?SAMLRequest={plain_b64}"
    if RelayState:
        redirect_url += f"&RelayState={RelayState}"
    conn = get_conn()
    log_event(conn, action="authn_request", actor="sp", sp_id=DEMO_SP_ID,
              idp_id=DEMO_IDP_ID, details={"request_id": request_id, "relay_state": RelayState})
    return RedirectResponse(redirect_url, status_code=302)


# ============================================
# 4. IdP SSO (mock IdP login page)
# ============================================
@router.get("/saml/idp/sso", response_class=HTMLResponse)
async def idp_sso_get(SAMLRequest: str = Query(...), RelayState: str = Query(default="")):
    """显示 mock IdP 登录页（让用户选 demo 用户模拟 IdP 颁发）"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Mock IdP — SSO</title>
    <style>
      body {{ font-family: -apple-system, sans-serif; background: #0f1419; color: #e6edf3;
              display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
      .card {{ background: #1a2028; padding: 32px 36px; border-radius: 12px; width: 360px;
               border: 1px solid #2f3845; }}
      h1 {{ font-size: 18px; margin: 0 0 6px; }}
      .meta {{ color: #8b949e; font-size: 12px; margin-bottom: 18px; }}
      label {{ display: block; font-size: 12px; color: #8b949e; margin: 8px 0 4px; }}
      input {{ width: 100%; background: #232a36; color: #e6edf3; border: 1px solid #2f3845;
               padding: 10px 12px; border-radius: 6px; font-size: 14px; box-sizing: border-box; }}
      button {{ width: 100%; background: #58a6ff; color: white; border: none; padding: 11px;
                border-radius: 6px; font-size: 14px; font-weight: 600; cursor: pointer; margin-top: 14px; }}
      .demo {{ background: #232a36; padding: 10px 12px; border-radius: 6px; font-size: 11px;
               color: #8b949e; margin-top: 14px; line-height: 1.6; }}
      code {{ color: #d29922; }}
    </style>
    </head>
    <body>
      <form class="card" method="POST" action="/saml/idp/sso">
        <h1>Mock SAML IdP — Single Sign-On</h1>
        <div class="meta">自建 IdP · SP-001 接入</div>
        <input type="hidden" name="SAMLRequest" value="{SAMLRequest}">
        <input type="hidden" name="RelayState" value="{RelayState}">
        <label>Username</label>
        <input type="text" name="username" value="engineer01" required autofocus>
        <label>Password</label>
        <input type="password" name="password" value="Engineer@2026" required>
        <button type="submit">Sign in via SAML</button>
        <div class="demo">
          <strong>Demo credentials:</strong><br>
          <code>engineer01</code> / <code>Engineer@2026</code><br>
          <code>admin01</code> / <code>Admin@2026</code>
        </div>
      </form>
    </body>
    </html>
    """


@router.post("/saml/idp/sso")
async def idp_sso_post(request: Request):
    form = await _parse_form(request)
    SAMLRequest = form.get("SAMLRequest", "")
    RelayState = form.get("RelayState", "")
    username = form.get("username", "")
    password = form.get("password", "")
    """IdP 验证 user → 颁发 SAML Response → 302 redirect to SP ACS"""
    # 验证 user
    user = authenticate_user(username, password)
    if not user:
        conn = get_conn()
        log_event(conn, action="login_fail", actor=username, sp_id=DEMO_SP_ID,
                  idp_id=DEMO_IDP_ID, details={"reason": "invalid_credentials"})
        raise HTTPException(401, "Invalid username or password")

    # 从 SAMLRequest 解出 request_id（简化版不做完整 base64 解析，直接 build_response）
    # 实际生产需要解析 AuthnRequest 拿 InResponseTo
    import base64
    try:
        ar_bytes = base64.b64decode(SAMLRequest)
        ar_xml = ar_bytes.decode("utf-8")
        import xml.etree.ElementTree as ET
        ar_root = ET.fromstring(ar_xml)
        request_id = ar_root.get("ID", "")
    except Exception:
        request_id = ""

    # 颁发 SAML Response
    response_b64, sig, session_index, response_id = build_saml_response(
        sp_id=DEMO_SP_ID, idp_id=DEMO_IDP_ID, user_id=user["user_id"],
        request_id=request_id, relay_state=RelayState
    )

    conn = get_conn()
    log_event(conn, action="assertion_issued", actor=username, sp_id=DEMO_SP_ID,
              idp_id=DEMO_IDP_ID, user_id=user["user_id"],
              details={"session_index": session_index, "response_id": response_id})

    # HTTP-POST binding: form auto-submit to SP ACS
    # 简化实现：302 redirect 带 query（生产用 auto-submit form）
    acs_url = "/saml/acs"
    qs = urlencode({"SAMLResponse": response_b64, "RelayState": RelayState})
    return RedirectResponse(f"{acs_url}?{qs}", status_code=302)


# ============================================
# 5. SP ACS (Assertion Consumer Service)
# ============================================
@router.get("/saml/acs")
async def sp_acs(SAMLResponse: str = Query(...), RelayState: str = Query(default="")):
    """SP 接收 SAML Response → 验证 → 建立本地 session → 重定向"""
    try:
        result = parse_saml_response(SAMLResponse, expected_sp_id=DEMO_SP_ID,
                                     expected_idp_id=DEMO_IDP_ID)
    except ValueError as e:
        raise HTTPException(400, f"SAML validation failed: {e}")

    # 查 user（按 NameID = email）
    name_id = result["name_id"]
    conn = get_conn()
    user_row = conn.execute("SELECT * FROM users WHERE email=?", (name_id,)).fetchone()
    if not user_row:
        raise HTTPException(404, f"User not found: {name_id}")
    user = {k: user_row[k] for k in user_row.keys()}

    # 保存 SAML session
    session_id = save_saml_session(
        user_id=user["user_id"], sp_id=DEMO_SP_ID, name_id=name_id,
        session_index=result["session_index"],
        not_before=result["not_before"], not_on_or_after=result["not_on_or_after"],
        attributes=result["attributes"], relay_state=RelayState
    )
    log_event(conn, action="sso_completed", actor=name_id, sp_id=DEMO_SP_ID,
              idp_id=DEMO_IDP_ID, user_id=user["user_id"],
              details={"session_index": result["session_index"]})

    # 设置 HttpOnly cookie
    response = RedirectResponse(RelayState or "/saml/userinfo", status_code=302)
    response.set_cookie(
        key="saml_session", value=session_id,
        httponly=True, samesite="strict", path="/", max_age=8 * 3600
    )
    return response


# ============================================
# 6. Userinfo（带 session cookie）
# ============================================
@router.get("/saml/userinfo")
async def saml_userinfo(saml_session: str = Cookie(default=None)):
    if not saml_session:
        raise HTTPException(401, "No SAML session cookie")
    sess = get_saml_session(saml_session)
    if not sess:
        raise HTTPException(401, "Invalid or expired session")
    # 检查过期
    from datetime import datetime, timezone
    na = datetime.fromisoformat(sess["not_on_or_after"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > na:
        delete_session(saml_session)
        raise HTTPException(401, "Session expired")
    return {
        "name_id": sess["name_id"],
        "user_id": sess["user_id"],
        "session_index": sess["session_index"],
        "session_id": sess["session_id"],
        "sp_id": sess["sp_id"],
        "attributes": sess["attributes"],
        "not_before": sess["not_before"],
        "not_on_or_after": sess["not_on_or_after"],
    }


# ============================================
# 7. List sessions（debug）
# ============================================
@router.get("/saml/sessions")
async def saml_sessions(saml_session: str = Cookie(default=None)):
    if not saml_session:
        raise HTTPException(401, "No SAML session cookie")
    sess = get_saml_session(saml_session)
    if not sess:
        raise HTTPException(401, "Invalid session")
    user_id = sess["user_id"]
    sessions = list_user_sessions(user_id)
    return {"user_id": user_id, "active_sessions": sessions}


# ============================================
# 8. Single Logout (SLO)
# ============================================
@router.post("/saml/slo")
async def saml_slo(response: Response, saml_session: str = Cookie(default=None)):
    """本地 SLO：清除当前 session cookie + DB session"""
    if saml_session:
        delete_session(saml_session)
        conn = get_conn()
        log_event(conn, action="slo_completed", actor="user", sp_id=DEMO_SP_ID,
                  idp_id=DEMO_IDP_ID, details={"session_id": saml_session})
    response = JSONResponse({"status": "logged_out"})
    response.delete_cookie("saml_session", path="/")
    return response


# ============================================
# 9. SAML Audit
# ============================================
@router.get("/saml/audit")
async def saml_audit(limit: int = Query(50, ge=1, le=500)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM saml_audit ORDER BY occurred_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return {"count": len(rows),
            "items": [{k: r[k] for k in r.keys()} for r in rows]}