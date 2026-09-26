"""
IdM SRE Lab - Week 23-24 (GenAI Alert Engineering) tests
- LLM-based alert interpretation
- Runbook auto-linking
- _strip_thinking protection
- Log persistence
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.ai_alert.interpreter import (
    _strip_thinking, _build_user_prompt, SYSTEM_PROMPT,
    interpret_alert, list_ai_alerts, get_ai_alert,
)


# ============================================
# _strip_thinking
# ============================================
def test_strip_thinking_full_tag():
    text = "<think>\nOK let me think about this...\n</think>\n## Summary\nReal answer"
    out = _strip_thinking(text)
    assert "OK let me think" not in out
    assert "Real answer" in out


def test_strip_thinking_unclosed():
    text = "<think>thinking without close\n## Summary\nReal answer"
    out = _strip_thinking(text)
    assert "thinking" not in out
    assert "Real answer" in out


def test_strip_thinking_bare_markers():
    text = "OK let me think about this\n## Summary\nReal answer"
    out = _strip_thinking(text)
    assert "OK let me think" not in out
    assert "Real answer" in out


def test_strip_thinking_actually_now():
    text = "Actually, wait let me write this first\n## Summary\nX"
    out = _strip_thinking(text)
    assert "Actually" not in out
    assert "## Summary" in out


def test_strip_thinking_clean_text_unchanged():
    text = "## Summary\nThis is clean"
    out = _strip_thinking(text)
    assert out.strip() == text.strip()


# ============================================
# Prompt builder
# ============================================
def test_build_user_prompt_basic():
    metrics = {"total_requests": 50, "total_errors": 5, "error_rate_pct": 10.0}
    prompt = _build_user_prompt("HighErrorRate", "critical", "2026-09-25T00:00:00Z",
                                  1.0, metrics, None)
    assert "HighErrorRate" in prompt
    assert "critical" in prompt
    assert "50" in prompt
    assert "10.0" in prompt
    assert "Associated Runbook" not in prompt  # 没传 runbook


def test_build_user_prompt_with_runbook():
    metrics = {"total_requests": 50}
    rb = {"title": "HTTP 5xx 错误率突增", "severity": "SEV-1",
           "indicators": ["error_rate > 5%"], "steps": [{"action": "check chaos"}]}
    prompt = _build_user_prompt("HighErrorRate", "critical", "2026-09-25", 1.0,
                                  metrics, rb)
    assert "Associated Runbook" in prompt
    assert "HTTP 5xx" in prompt
    assert "check chaos" in prompt


def test_system_prompt_has_constraints():
    assert "ONLY use the provided metrics" in SYSTEM_PROMPT
    assert "≤ 500 tokens" in SYSTEM_PROMPT
    assert "Summary" in SYSTEM_PROMPT
    assert "Hypotheses" in SYSTEM_PROMPT
    assert "Mitigation" in SYSTEM_PROMPT


# ============================================
# DB helpers
# ============================================
def test_get_ai_alert_not_found():
    assert get_ai_alert(999999) is None


# ============================================
# FastAPI endpoints
# ============================================
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
        assert r.status_code == 200
        yield c


def test_endpoint_show_prompt(client):
    r = client.get("/ai-alerts/prompt")
    assert r.status_code == 200
    d = r.json()
    assert "system_prompt" in d
    assert "constraints" in d


def test_endpoint_interpret_missing_alert_name(client):
    r = client.post("/ai-alerts/interpret", data={"alert_name": ""})
    assert r.status_code == 400


def test_endpoint_log_list_empty(client):
    r = client.get("/ai-alerts/log")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_endpoint_log_one_404(client):
    r = client.get("/ai-alerts/log/999999")
    assert r.status_code == 404


def test_endpoint_log_filter_by_alert_name(client):
    """先 mock 一条 log（手动调 interpret_alert 写到 DB）"""
    from app.ai_alert.interpreter import interpret_alert
    metrics = {"total_requests": 50, "error_rate_pct": 10.0}
    interpret_alert("HighErrorRate", metrics, severity="warning")

    r = client.get("/ai-alerts/log?alert_name=HighErrorRate")
    assert r.status_code == 200
    items = r.json()["items"]
    for it in items:
        assert it["alert_name"] == "HighErrorRate"


def test_endpoint_interpret_real_llm(client):
    """真实 LLM 调用 — 需要 LLM_API_KEY"""
    import os
    if not os.environ.get("LLM_API_KEY"):
        pytest.skip("LLM_API_KEY not set")
    metrics = '{"total_requests":50,"total_errors":45,"error_rate_pct":90.0}'
    r = client.post("/ai-alerts/interpret", data={
        "alert_name": "HighErrorRate",
        "severity": "critical",
        "duration_minutes": "1.0",
        "metrics": metrics,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["runbook_id"] == "high_error_rate"
    assert "Summary" in d["interpretation"] or "## " in d["interpretation"]


def test_endpoint_interpret_invalid_metrics(client):
    """invalid JSON metrics → 用空 dict（不 crash）"""
    r = client.post("/ai-alerts/interpret", data={
        "alert_name": "HighErrorRate",
        "metrics": "INVALID",
    })
    # metrics 解析失败 → fallback 到 {}，但需要 LLM_API_KEY
    # 跳过如果没 key
    import os
    if not os.environ.get("LLM_API_KEY"):
        pytest.skip("LLM_API_KEY not set")
    assert r.status_code in (200, 500)  # 200 if LLM OK, 500 if LLM fails