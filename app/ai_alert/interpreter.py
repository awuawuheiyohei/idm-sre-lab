"""
GenAI Alert Interpreter (Week 23-24 MVP)

LLM 解读 Prometheus alert：
- 收集当前 metrics + runbook
- 调 LLM（OpenAI 兼容协议，Interview/.env 的 key）
- _strip_thinking 处理
- 存 ai_alert_log 表

PRD 反模式：
- 禁止"LLM 瞎解读"——prompt 强制含 alert ID + time window + metrics + runbook
- LLM 仅作建议（不是 auto-execute）
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from ..db import db_connection


# ============================================
# Config (from env or defaults)
# ============================================
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.MiniMax.chat/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "MiniMax-M3")
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.3"))


# ============================================
# System prompt（强约束）
# ============================================
SYSTEM_PROMPT = """You are an SRE incident response assistant for an Apple IdMS-style Identity Management platform.

When given:
- Alert name (e.g. HighErrorRate)
- Severity
- Triggered time + duration
- Metrics snapshot (4 Golden Signals + per-endpoint latency/error/saturation)
- Associated runbook

You MUST output:
1. ## Summary (1-2 sentences): what's wrong, in plain language
2. ## Hypotheses (3 bullets): ranked by likelihood, with evidence from metrics
3. ## Runbook (1 specific step from the associated runbook)
4. ## Verification (2-3 curl/sql commands to confirm hypothesis)
5. ## Mitigation (3 specific actions, in order)

Strict rules:
- ONLY use the provided metrics. Do NOT invent log entries or numbers.
- If a metric is missing, say "metric X not available" — never guess.
- Output ≤ 500 tokens.
- No thinking traces (no "OK let me think", "Actually", "Wait").
- Output plain text with markdown headings (## Summary, ## Hypotheses, ## Runbook, ## Verification, ## Mitigation)."""


def _strip_thinking(content: str) -> str:
    """剥 LLM thinking 痕迹（与之前 3 个 LLM 项目一致）"""
    # 1) 完整 <think> 块
    content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL)
    # 2) 未闭合 <think>（删到下一个 markdown heading 之前）
    content = re.sub(r"<think>.*?(?=\n## |\Z)", "", content, flags=re.DOTALL)
    # 3) 裸 thinking markers（re.sub 整行删，保留 ## Summary 之后内容）
    for marker in [
        r"^OK final structure:.*\n",
        r"^OK let me (write|think).*\n",
        r"^OK writing now.*\n",
        r"^Actually[, ].*\n",
        r"^Wait[, ].*\n",
        r"^One more thought:.*\n",
        r"^Let me (write|think|finalize|now).*\n",
    ]:
        new_content, n = re.subn(marker, "", content, flags=re.MULTILINE)
        if n > 0:
            content = new_content
            break
    return content.strip()


def _build_user_prompt(alert_name: str, severity: str, triggered_at: str,
                        duration_minutes: float, metrics: dict,
                        runbook: dict | None) -> str:
    """构造 user prompt"""
    parts = [f"""## Alert
- Name: {alert_name}
- Severity: {severity}
- Triggered: {triggered_at}
- Duration: {duration_minutes} minutes

## Current Metrics Snapshot
- Total requests: {metrics.get('total_requests', 'N/A')}
- Total errors: {metrics.get('total_errors', 'N/A')} (error_rate_pct: {metrics.get('error_rate_pct', 'N/A')})
- Active users: {metrics.get('active_users', 'N/A')}

## Per-Endpoint Latency (p99)
```json
{json.dumps(metrics.get('latency_ms', {}), indent=2)}
```

## Per-Endpoint Errors (status → count)
```json
{json.dumps(metrics.get('by_status', {}), indent=2)}
```

## Per-Endpoint In-flight
```json
{json.dumps(metrics.get('saturation', {}), indent=2)}
```"""]
    if runbook:
        rb_text = f"""## Associated Runbook
- Title: {runbook.get('title')}
- Severity: {runbook.get('severity')}
- Indicators: {', '.join(runbook.get('indicators', []))}
- First Step: {runbook.get('steps', [{}])[0].get('action', 'N/A') if runbook.get('steps') else 'N/A'}"""
        parts.append(rb_text)
    parts.append("\nNow interpret this alert and recommend next steps.")
    return "\n\n".join(parts)


def call_llm(system_prompt: str, user_prompt: str,
             model: str = None, temperature: float = None,
             max_tokens: int = 1500) -> str:
    """调 OpenAI 兼容 chat completion API"""
    if not LLM_API_KEY:
        raise ValueError("LLM_API_KEY not configured. Set in .env")

    url = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or LLM_MODEL,
        "temperature": temperature if temperature is not None else LLM_TEMPERATURE,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"LLM call failed ({resp.status_code}): {resp.text[:500]}")
    content = resp.json()["choices"][0]["message"]["content"]
    return _strip_thinking(content)


# ============================================
# Main entry: interpret alert
# ============================================
def interpret_alert(alert_name: str, metrics: dict, runbook: dict | None = None,
                    severity: str = "warning",
                    triggered_at: str = None,
                    duration_minutes: float = 1.0) -> str:
    """LLM 解读 alert，返回 interpretation 文本（同时存 DB）"""
    triggered_at = triggered_at or datetime.now(timezone.utc).isoformat()
    user_prompt = _build_user_prompt(
        alert_name, severity, triggered_at, duration_minutes,
        metrics, runbook,
    )
    try:
        interpretation = call_llm(SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        interpretation = f"LLM call failed: {e}"

    # 存 log
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO ai_alert_log
               (alert_name, metrics_snapshot, llm_interpretation,
                runbook_ref, severity)
               VALUES (?, ?, ?, ?, ?)""",
            (alert_name, json.dumps(metrics, ensure_ascii=False),
             interpretation, runbook.get("id") if runbook else None,
             severity)
        )
        conn.commit()

    return interpretation


# ============================================
# DB query
# ============================================
def list_ai_alerts(alert_name: str = None, limit: int = 20) -> list:
    sql = "SELECT * FROM ai_alert_log WHERE 1=1"
    params = []
    if alert_name:
        sql += " AND alert_name=?"
        params.append(alert_name)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with db_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}
        try:
            d["metrics_snapshot"] = json.loads(d["metrics_snapshot"]) if d["metrics_snapshot"] else {}
        except Exception:
            pass
        out.append(d)
    return out


def get_ai_alert(alert_log_id: int) -> dict | None:
    with db_connection() as conn:
        row = conn.execute("SELECT * FROM ai_alert_log WHERE alert_id=?",
                          (alert_log_id,)).fetchone()
        if not row:
            return None
        d = {k: row[k] for k in row.keys()}
        try:
            d["metrics_snapshot"] = json.loads(d["metrics_snapshot"]) if d["metrics_snapshot"] else {}
        except Exception:
            pass
        return d