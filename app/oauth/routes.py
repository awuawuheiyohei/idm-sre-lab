"""
OAuth2 / OIDC endpoints（Week 3-4 MVP）：
- GET /oauth/authorize (with login form simulation)
- POST /oauth/token (authorization_code grant + refresh_token grant)
- GET /oauth/userinfo (Bearer access_token)
- POST /oauth/revoke (RFC 7009)
- GET /.well-known/openid-configuration (discovery)
- GET /.well-known/jwks.json (JWKS for RS256 verify)

PEP 668 兼容：手写 url-encoded parser，避免 python-multipart 依赖
"""
import json
import secrets
from urllib.parse import urlencode, parse_qs
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..db import get_oauth_config, get_active_jwks, get_conn, row_to_dict
from ..models import oauth_store
from ..models.oauth_store import (
    get_client, verify_client_secret, redirect_uri_matches,
    authenticate_user, get_user_by_id,
    create_authorization_code, consume_authorization_code,
    issue_access_token, issue_refresh_token, issue_id_token,
    verify_token, revoke_token, list_active_tokens,
    introspect_token, revoke_token_cached,
    log_event, validate_pkce_verifier,
    AUTH_CODE_TTL,
)

router = APIRouter()


async def parse_form(request: Request) -> dict:
    """手写 url-encoded parser，替代 FastAPI Form()（避免 python-multipart 依赖）"""
    body = await request.body()
    if not body:
        return {}
    try:
        return {k: v[0] for k, v in parse_qs(body.decode("utf-8")).items()}
    except Exception as e:
        raise HTTPException(400, f"Invalid form body: {e}")


# ============================================
# Discovery
# ============================================
@router.get("/.well-known/openid-configuration")
async def discovery():
    return get_oauth_config()


@router.get("/.well-known/jwks.json")
async def jwks():
    keys = get_active_jwks()
    return {"keys": keys}


# ============================================
# /oauth/authorize（简化版：GET 直接显示 login form）
# ============================================
@router.get("/oauth/authorize", response_class=HTMLResponse)
async def authorize(
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    response_type: str = Query("code"),
    scope: str = Query("openid"),
    state: str = Query(""),
    code_challenge: str = Query(None),
    code_challenge_method: str = Query(None),
):
    # 校验 client + redirect_uri
    client = get_client(client_id)
    if not client:
        raise HTTPException(400, f"Unknown client_id: {client_id}")
    if not redirect_uri_matches(client["redirect_uris"], redirect_uri):
        raise HTTPException(400, "redirect_uri not registered")
    if response_type != "code":
        raise HTTPException(400, "Only response_type=code supported")

    # 简化版 login form（dev 用 — 真实场景需要 session/CSRF）
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <title>IdM SRE Lab — Sign In</title>
      <style>
        body {{ font-family: -apple-system, sans-serif; background: #0f1419; color: #e6edf3;
                display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
        .card {{ background: #1a2028; padding: 32px 36px; border-radius: 12px; width: 360px;
                 border: 1px solid #2f3845; }}
        h1 {{ font-size: 20px; margin: 0 0 8px; }}
        .meta {{ color: #8b949e; font-size: 12px; margin-bottom: 20px; }}
        input {{ width: 100%; background: #232a36; color: #e6edf3; border: 1px solid #2f3845;
                 padding: 10px 12px; border-radius: 6px; margin: 6px 0 14px; font-size: 14px; box-sizing: border-box; }}
        button {{ width: 100%; background: #58a6ff; color: white; border: none; padding: 11px;
                  border-radius: 6px; font-size: 14px; font-weight: 600; cursor: pointer; }}
        .demo {{ background: #232a36; padding: 10px 12px; border-radius: 6px; font-size: 11px;
                 color: #8b949e; margin-top: 16px; line-height: 1.6; }}
        code {{ color: #d29922; }}
      </style>
    </head>
    <body>
      <form class="card" method="POST" action="/oauth/authorize">
        <h1>Sign in to <span style="color:#58a6ff;">{client['client_name']}</span></h1>
        <div class="meta">via IdM SRE Lab · OAuth2 Authorization Code Grant</div>
        <input type="hidden" name="client_id" value="{client_id}">
        <input type="hidden" name="redirect_uri" value="{redirect_uri}">
        <input type="hidden" name="scope" value="{scope}">
        <input type="hidden" name="state" value="{state}">
        {f'<input type="hidden" name="code_challenge" value="{code_challenge}">' if code_challenge else ''}
        {f'<input type="hidden" name="code_challenge_method" value="{code_challenge_method}">' if code_challenge_method else ''}
        <label>Username</label>
        <input type="text" name="username" placeholder="engineer01" required autofocus>
        <label>Password</label>
        <input type="password" name="password" placeholder="Engineer@2026" required>
        <button type="submit">Authorize</button>
        <div class="demo">
          <strong>Demo credentials:</strong><br>
          <code>engineer01</code> / <code>Engineer@2026</code> (employee)<br>
          <code>bu-lead01</code> / <code>BuLead@2026</code> (BU lead)<br>
          <code>admin01</code> / <code>Admin@2026</code> (IT admin)
        </div>
      </form>
    </body>
    </html>
    """


@router.post("/oauth/authorize")
async def authorize_submit(request: Request):
    form = await parse_form(request)
    username = form.get("username", "")
    password = form.get("password", "")
    client_id = form.get("client_id", "")
    redirect_uri = form.get("redirect_uri", "")
    scope = form.get("scope", "openid")
    state = form.get("state", "")
    code_challenge = form.get("code_challenge")
    code_challenge_method = form.get("code_challenge_method")
    # 验证 client
    client = get_client(client_id)
    if not client:
        raise HTTPException(400, f"Unknown client_id: {client_id}")
    if not redirect_uri_matches(client["redirect_uris"], redirect_uri):
        raise HTTPException(400, "redirect_uri not registered")

    # 验证用户
    user = authenticate_user(username, password)
    conn = get_conn()
    if not user:
        log_event(conn, action="login_fail", actor=username, client_id=client_id,
                  details={"reason": "invalid_credentials"})
        raise HTTPException(401, "Invalid username or password")

    log_event(conn, action="login_success", actor=username, client_id=client_id,
              user_id=user["user_id"], details={"scope": scope})

    # 生成 authorization code
    code = create_authorization_code(
        client_id=client_id, user_id=user["user_id"], redirect_uri=redirect_uri,
        scope=scope, code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )
    log_event(conn, action="auth_code_issued", actor=username, client_id=client_id,
              user_id=user["user_id"], details={"ttl": AUTH_CODE_TTL, "pkce": bool(code_challenge)})

    # 302 redirect 回 client
    qs = urlencode({"code": code, **({"state": state} if state else {})})
    return RedirectResponse(f"{redirect_uri}?{qs}", status_code=302)


# ============================================
# /oauth/token
# ============================================
def _client_auth_form(request: Request, client_id: str, client_secret: str):
    """支持 client_secret_basic (Authorization header) + client_secret_post (form)"""
    # form
    if client_id and client_secret:
        return client_id, client_secret
    # basic
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        import base64
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            if ":" in decoded:
                cid, secret = decoded.split(":", 1)
                return cid, secret
        except Exception:
            pass
    return None, None


@router.post("/oauth/token")
async def token_endpoint(request: Request):
    form = await parse_form(request)
    grant_type = form.get("grant_type", "")
    code = form.get("code")
    redirect_uri = form.get("redirect_uri")
    code_verifier = form.get("code_verifier")
    refresh_token = form.get("refresh_token")
    client_id = form.get("client_id")
    client_secret = form.get("client_secret")
    scope = form.get("scope")

    # Client 认证（优先 form，fallback Basic）
    cid, secret = _client_auth_form(request, client_id, client_secret)
    if not cid or not verify_client_secret(cid, secret or ""):
        conn = get_conn()
        log_event(conn, action="token_request_fail", client_id=cid,
                  details={"grant_type": grant_type, "reason": "client_auth_failed"})
        raise HTTPException(401, "Invalid client credentials")

    conn = get_conn()

    if grant_type == "authorization_code":
        if not code or not redirect_uri:
            raise HTTPException(400, "Missing code or redirect_uri")
        consumed = consume_authorization_code(code, cid, redirect_uri, code_verifier)
        if not consumed:
            log_event(conn, action="token_request_fail", client_id=cid,
                      details={"grant_type": grant_type, "reason": "invalid_code"})
            raise HTTPException(400, "Invalid or expired authorization code")

        user_id = consumed["user_id"]
        scope_to_use = consumed["scope"]
        access = issue_access_token(cid, user_id, scope_to_use)
        refresh = issue_refresh_token(cid, user_id, scope_to_use)
        body = {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": refresh,
            "scope": scope_to_use,
        }
        # OIDC: 加 id_token
        if "openid" in scope_to_use:
            body["id_token"] = issue_id_token(cid, user_id, scope_to_use)
        log_event(conn, action="token_issued", client_id=cid, user_id=user_id,
                  details={"grant_type": grant_type, "scope": scope_to_use})
        return body

    elif grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(400, "Missing refresh_token")
        try:
            claims = verify_token(refresh_token, expected_aud=cid, expected_token_type="refresh")
        except ValueError as e:
            log_event(conn, action="token_request_fail", client_id=cid,
                      details={"grant_type": grant_type, "reason": str(e)})
            raise HTTPException(400, str(e))

        # 撤销旧 refresh_token（rotation）
        revoke_token(claims["jti"])

        # 签发新 access + refresh
        user_id = claims["sub"]
        scope_to_use = claims.get("scope", "openid")
        access = issue_access_token(cid, user_id, scope_to_use)
        refresh = issue_refresh_token(cid, user_id, scope_to_use)
        body = {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": refresh,
            "scope": scope_to_use,
        }
        log_event(conn, action="token_rotated", client_id=cid, user_id=user_id,
                  details={"grant_type": grant_type})
        return body

    else:
        raise HTTPException(400, f"Unsupported grant_type: {grant_type}")


# ============================================
# /oauth/userinfo (Bearer access_token)
# ============================================
@router.get("/oauth/userinfo")
async def userinfo(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = auth[7:]
    try:
        claims = verify_token(token, expected_token_type="access")
    except ValueError as e:
        raise HTTPException(401, str(e))

    user = get_user_by_id(claims["sub"])
    if not user:
        raise HTTPException(404, "User not found")

    scope = claims.get("scope", "")
    body = {"sub": claims["sub"]}
    if "email" in scope:
        body["email"] = user["email"]
        body["email_verified"] = True
    if "profile" in scope:
        body["name"] = user["full_name"]
        body["preferred_username"] = user["username"]
        body["business_unit"] = user["business_unit"]
        body["role"] = user["role"]
    return body


# ============================================
# /oauth/revoke (RFC 7009)
# ============================================
@router.post("/oauth/revoke")
async def revoke_endpoint(request: Request):
    form = await parse_form(request)
    token = form.get("token", "")
    token_type_hint = form.get("token_type_hint")
    """任何持有 client 凭据的应用都可撤销其签发的 token"""
    auth = request.headers.get("Authorization", "")
    cid, secret = None, None
    if auth.startswith("Basic "):
        import base64
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            if ":" in decoded:
                cid, secret = decoded.split(":", 1)
        except Exception:
            pass
    if not cid:
        # fallback to form
        raise HTTPException(401, "Client authentication required")

    try:
        claims = verify_token(token)
    except ValueError:
        # RFC 7009: 即使 token 无效也返回 200（防止 token 探测）
        return {"status": "ok"}

    # 只能撤销自己 client 签发的 token
    if claims.get("client_id") != cid:
        raise HTTPException(400, "Token does not belong to this client")

    revoke_token(claims["jti"])
    conn = get_conn()
    log_event(conn, action="token_revoked", client_id=cid, user_id=claims["sub"],
              details={"token_type": claims.get("token_type")})
    return {"status": "ok"}


# ============================================
# /oauth/introspect (RFC 7662)
# ============================================
@router.post("/oauth/introspect")
async def introspect_endpoint(request: Request):
    """RFC 7662 Token Introspection — 客户端调，看 token 状态"""
    form = await parse_form(request)
    token = form.get("token", "")
    if not token:
        raise HTTPException(400, "Missing token")

    # Client 认证（Basic auth 优先）
    cid, secret = _client_auth_form(
        request,
        form.get("client_id"),
        form.get("client_secret"),
    )
    if not cid or not verify_client_secret(cid, secret or ""):
        raise HTTPException(401, "Invalid client credentials")

    # Introspect（expected_aud 必须是这个 client 自己）
    result = introspect_token(token, expected_aud=cid)
    return result


# ============================================
# /oauth/tokens (debug: list active tokens for a user)
# ============================================
@router.get("/oauth/tokens/{user_id}")
async def list_user_tokens(user_id: str):
    """Dev/debug endpoint — 生产应禁掉"""
    tokens = list_active_tokens(user_id)
    return {"user_id": user_id, "active_tokens": tokens}


# ============================================
# /oauth/audit (last 50 events)
# ============================================
@router.get("/oauth/audit")
async def list_audit(limit: int = Query(50, ge=1, le=500)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM oauth_audit ORDER BY occurred_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return {"count": len(rows),
            "items": [{k: r[k] for k in r.keys()} for r in rows]}