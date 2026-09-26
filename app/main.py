"""IdM SRE Lab FastAPI 入口（Week 3-4：OAuth2/OIDC MVP）"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .db import init_db
from .oauth.routes import router as oauth_router


app = FastAPI(
    title="IdM SRE Lab",
    version="1.1.0",
    description="Apple IdMS 风格 Identity Management + 完整 SRE 实践（Week 25-26 ISO 27001 + PCI-DSS + STRIDE）",
)


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "idm-sre-lab",
        "version": "1.1.0",
        "week": "25-26 (ISO 27001 + PCI-DSS)",
        "endpoints_count": 58,
    }


@app.get("/")
async def root():
    return {
        "service": "IdM SRE Lab",
        "version": "1.1.0",
        "week": "25-26",
        "endpoints": {
            "health": "/health",
            "discovery": "/.well-known/openid-configuration",
            "jwks": "/.well-known/jwks.json",
            "authorize": "/oauth/authorize",
            "token": "/oauth/token",
            "userinfo": "/oauth/userinfo",
            "revoke": "/oauth/revoke",
            "audit": "/oauth/audit",
            "saml_metadata": "/saml/metadata",
            "saml_idp_metadata": "/saml/idp-metadata",
            "saml_login": "/saml/login",
            "saml_idp_sso": "/saml/idp/sso",
            "saml_acs": "/saml/acs",
            "saml_userinfo": "/saml/userinfo",
            "saml_sessions": "/saml/sessions",
            "saml_slo": "/saml/slo",
            "saml_audit": "/saml/audit",
            "admin_seed": "/admin/seed",
        },
        "roadmap": {
            "current": "Week 5-6 (SAML 2.0 MVP)",
            "next": "Week 7-8 (WebAuthn)",
            "weeks_total": 30,
        },
    }


# OAuth 路由
app.include_router(oauth_router)

# SAML 路由
from .saml.routes import router as saml_router  # noqa: E402
app.include_router(saml_router)

# WebAuthn 路由（Week 7-8）
from .webauthn.routes import router as webauthn_router  # noqa: E402
app.include_router(webauthn_router)

# Devices 路由（Week 9-10）
from .devices.routes import router as devices_router  # noqa: E402
app.include_router(devices_router)

# Observability 路由 + middleware（Week 13-14）
from .observability.routes import router as obs_router  # noqa: E402
from .observability.metrics import metrics_middleware  # noqa: E402
app.include_router(obs_router)
app.middleware("http")(metrics_middleware)

# Logs + Alerts（Week 15-16）
from .logs.structured_logging import setup_logging  # noqa: E402
from .logs.routes import router as logs_router  # noqa: E402
setup_logging()  # 启动时配置 JSON logger
app.include_router(logs_router)

# SLO（Week 17-18）
from .slo.routes import router as slo_router  # noqa: E402
app.include_router(slo_router)

# Chaos Engineering（Week 19-20）
from .chaos.routes import router as chaos_router  # noqa: E402
app.include_router(chaos_router)

# Incident Response（Week 21-22）
from .incidents.routes import router as incidents_router  # noqa: E402
app.include_router(incidents_router)

# GenAI Alert（Week 23-24）
from .ai_alert.routes import router as ai_alert_router  # noqa: E402
app.include_router(ai_alert_router)

# Security compliance docs（Week 25-26）
from .security.routes import router as security_router  # noqa: E402
app.include_router(security_router)


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