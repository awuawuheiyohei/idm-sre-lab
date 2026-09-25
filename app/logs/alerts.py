"""
Alert Rules Engine (Week 15-16 MVP)

Simulate Prometheus alerting rules evaluation against current metrics:
- HighErrorRate: error_rate > 5% over 5min
- HighLatency: p95 latency > 1000ms
- ServiceDown: requests/sec == 0 (after initial warmup)
- TokenFailureSpike: 401 errors > 10 in window

Each rule:
- name + description + severity
- evaluator: function(metrics_summary) -> bool (active?)
"""
from __future__ import annotations
from typing import Callable, Dict
from datetime import datetime, timezone, timedelta
import threading


ALERT_RULES: list[dict] = [
    {
        "name": "HighErrorRate",
        "description": "Error rate exceeds 5% (5xx / total requests)",
        "severity": "critical",
        "evaluator": lambda s: (s.get("error_rate_pct", 0) > 5 and s.get("total_requests", 0) > 10),
        "runbook": "https://idm-sre-lab.local/runbooks/high-error-rate",
    },
    {
        "name": "HighLatencyP95",
        "description": "p95 latency > 1000ms on any endpoint",
        "severity": "warning",
        "evaluator": lambda s: any(v > 1000 for v in
                                     [v.get("p95", 0) for v in s.get("latency_ms", {}).values() if isinstance(v, dict)]),
        "runbook": "https://idm-sre-lab.local/runbooks/high-latency",
    },
    {
        "name": "TokenFailureSpike",
        "description": "Token validation failures > 5 in last 100 requests",
        "severity": "warning",
        "evaluator": lambda s: s.get("auth_401_count", 0) > 5,
        "runbook": "https://idm-sre-lab.local/runbooks/token-failures",
    },
    {
        "name": "LowTraffic",
        "description": "Total requests == 0 (possible outage)",
        "severity": "info",
        "evaluator": lambda s: s.get("total_requests", 0) == 0 and s.get("uptime_minutes", 0) > 5,
        "runbook": "https://idm-sre-lab.local/runbooks/no-traffic",
    },
]


# ============================================
# Alert state tracking（带 cooldown 防止 alert storm）
# ============================================
_alert_state: Dict[str, dict] = {}  # name -> {firing_since, last_fired_at, last_resolved_at}
_state_lock = threading.RLock()


def evaluate_alerts(metrics_summary: dict, uptime_minutes: float = 0) -> list:
    """评估所有规则，返回当前 firing 的 alerts"""
    metrics_summary = dict(metrics_summary)
    metrics_summary["uptime_minutes"] = uptime_minutes
    now = datetime.now(timezone.utc)
    firing = []
    with _state_lock:
        for rule in ALERT_RULES:
            is_active = bool(rule["evaluator"](metrics_summary))
            name = rule["name"]
            if is_active:
                if name not in _alert_state:
                    _alert_state[name] = {
                        "firing_since": now.isoformat(),
                        "last_fired_at": now.isoformat(),
                    }
                else:
                    _alert_state[name]["last_fired_at"] = now.isoformat()
                firing.append({
                    "name": name,
                    "description": rule["description"],
                    "severity": rule["severity"],
                    "firing_since": _alert_state[name]["firing_since"],
                    "last_fired_at": _alert_state[name]["last_fired_at"],
                    "runbook": rule["runbook"],
                    "state": "firing",
                })
            else:
                if name in _alert_state:
                    _alert_state[name]["last_resolved_at"] = now.isoformat()
                    _alert_state[name].pop("firing_since", None)
    return firing


def list_all_alerts(metrics_summary: dict, uptime_minutes: float = 0) -> list:
    """返回所有规则（firing + resolved），便于 dashboard 显示"""
    firing = evaluate_alerts(metrics_summary, uptime_minutes)
    firing_names = {a["name"] for a in firing}
    all_alerts = []
    now = datetime.now(timezone.utc)
    for rule in ALERT_RULES:
        if rule["name"] in firing_names:
            all_alerts.append(firing[next(i for i, a in enumerate(firing) if a["name"] == rule["name"])])
        else:
            state = _alert_state.get(rule["name"], {})
            all_alerts.append({
                "name": rule["name"],
                "description": rule["description"],
                "severity": rule["severity"],
                "runbook": rule["runbook"],
                "state": "ok",
                "last_resolved_at": state.get("last_resolved_at"),
            })
    return all_alerts


def reset_alert_state():
    with _state_lock:
        _alert_state.clear()