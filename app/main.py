"""IdM SRE Lab FastAPI 入口（Week 3-4：OAuth2/OIDC MVP）"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .db import init_db
from .oauth.routes import router as oauth_router


app = FastAPI(
    title="IdM SRE Lab",
    version="0.2.0",
    description="Apple IdMS 风格 Identity Management + 完整 SRE 实践（Week 3-4 OAuth2/OIDC MVP）",
)


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "idm-sre-lab",
        "version": "0.2.0",
        "week": "3-4 (OAuth2/OIDC MVP)",
        "endpoints_count": 8,
    }


@app.get("/")
async def root():
    return {
        "service": "IdM SRE Lab",
        "version": "0.2.0",
        "week": "3-4",
        "endpoints": {
            "health": "/health",
            "discovery": "/.well-known/openid-configuration",
            "jwks": "/.well-known/jwks.json",
            "authorize": "/oauth/authorize",
            "token": "/oauth/token",
            "userinfo": "/oauth/userinfo",
            "revoke": "/oauth/revoke",
            "audit": "/oauth/audit",
            "admin_seed": "/admin/seed",
        },
        "roadmap": {
            "current": "Week 3-4 (OAuth2/OIDC MVP)",
            "next": "Week 5-6 (SAML 2.0)",
            "weeks_total": 30,
        },
    }


# OAuth 路由
app.include_router(oauth_router)


# ============================================
# Admin / Seed
# ============================================
@app.post("/admin/seed")
async def admin_seed():
    from .models.seed import seed_all
    stats = seed_all(verbose=False)
    return {"status": "ok", "stats": stats}


def run():
    import uvicorn
    import os
    port = int(os.environ.get("WEB_PORT", "5050"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    run()