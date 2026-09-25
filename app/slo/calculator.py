"""
SLI/SLO Calculator (Week 17-18 MVP)

定义 4 个核心 SLO（按 PRD）：
1. Availability: 99.9% 月度（monthly error budget = 43.2 min）
2. p99 token 签发延迟 < 200ms
3. p99 SAML AuthnRequest 处理 < 500ms
4. Error rate < 1%

Error budget 计算：
- budget_total = (1 - SLO_target) × time_window
- budget_burned = 当前错误数 / 允许错误数
- burn_rate = (budget_burned / elapsed_fraction) - 1.0

(Prometheus burn-rate alert 标准公式)
"""
from __future__ import annotations
import math
from datetime import datetime, timezone, timedelta


# 4 个核心 SLO 定义（per PRD）
SLO_DEFINITIONS = [
    {
        "id": "availability",
        "name": "Availability",
        "description": "Service availability (HTTP 200/300/400 占比)",
        "target_pct": 99.9,
        "window": "30d",
        "budget_total_minutes_30d": 43.2,
        "objective": "可用性月度 99.9%（monthly error budget = 43.2 min）",
        "slf_formula": "successful_requests / total_requests",
    },
    {
        "id": "token_p99_latency",
        "name": "Token Issuance p99 Latency",
        "description": "p99 /oauth/token 端到端延迟",
        "target_pct": 99.0,  # 99% 的请求必须 < 200ms
        "threshold_ms": 200,
        "window": "30d",
        "objective": "p99 token 签发延迟 < 200ms",
        "slf_formula": "requests_under_threshold_ms / total_requests",
    },
    {
        "id": "saml_p99_latency",
        "name": "SAML AuthnRequest p99 Latency",
        "description": "p99 /saml/* AuthnRequest 处理延迟",
        "target_pct": 99.0,
        "threshold_ms": 500,
        "window": "30d",
        "objective": "p99 SAML AuthnRequest 处理 < 500ms",
        "slf_formula": "requests_under_threshold_ms / total_requests",
    },
    {
        "id": "error_rate",
        "name": "Error Rate (5xx)",
        "description": "5xx HTTP 错误率",
        "target_pct": 99.0,  # 99% 必须 < 1% error
        "threshold_pct": 1.0,
        "window": "30d",
        "objective": "Error rate < 1%",
        "slf_formula": "1 - (5xx_count / total_requests)",
    },
]


def compute_slo_status(slo_id: str, total_requests: int, errors: int,
                        elapsed_days: float, window_days: float = 30.0) -> dict:
    """计算单个 SLO 当前状态"""
    slo = next((s for s in SLO_DEFINITIONS if s["id"] == slo_id), None)
    if not slo:
        raise ValueError(f"Unknown SLO: {slo_id}")

    if total_requests == 0:
        return {
            **slo,
            "total_requests": 0,
            "budget_burned_pct": 0.0,
            "budget_remaining_pct": 100.0,
            "burn_rate": 0.0,
            "status": "insufficient_data",
            "objective_met": None,
        }

    elapsed_fraction = min(elapsed_days / window_days, 1.0)
    # 简化 budget 计算：每个 SLO 的 budget 是"允许失败率"
    if slo_id == "availability":
        success_rate = (total_requests - errors) / total_requests
        target = slo["target_pct"] / 100
        # error budget = (1 - target) × window（用 round 避免浮点精度）
        budget_pct = round((1 - target) * 100, 4)
        # 实际错误率（保留 4 位小数）
        actual_error_rate = round(errors / total_requests * 100, 4)
        # burned budget
        burned = actual_error_rate / budget_pct * 100 if budget_pct > 0 else 0
        # burn rate（相对于 elapsed_fraction 的预期 burn）
        expected_burn = elapsed_fraction * 100
        burn_rate = (burned - expected_burn) / expected_burn if expected_burn > 0 else 0
        remaining = max(0, 100 - burned)
        # objective_met: error rate ≤ budget（避免浮点 < 误判）
        objective_met = actual_error_rate <= budget_pct
        # status
        if objective_met and remaining >= 0:
            status = "ok" if burned < 100 else "warning"
        else:
            status = "exhausted"
    elif slo_id in ("token_p99_latency", "saml_p99_latency"):
        # 简化：用 golden_signals_summary 的 p99
        from ..observability.metrics import golden_signals_summary
        summary = golden_signals_summary()
        ep = "/oauth/token" if slo_id == "token_p99_latency" else "/saml/idp/sso"
        p99 = summary["latency_ms"].get(ep, {}).get("p99", 0)
        objective_met = p99 < slo["threshold_ms"]
        budget_pct = 1.0  # 99% 必须达标
        # 简化：1 - p99/threshold 假设 SLO 违反率
        burned = (p99 / slo["threshold_ms"]) * 100 if slo["threshold_ms"] > 0 else 0
        burn_rate = (burned - 1.0) if burned > 1.0 else 0
        remaining = max(0, 100 - burned)
        status = "ok" if objective_met else ("warning" if remaining > 0 else "exhausted")
    elif slo_id == "error_rate":
        actual_error_rate = round(errors / total_requests * 100, 4)
        threshold = slo["threshold_pct"]
        objective_met = actual_error_rate <= threshold
        burned = actual_error_rate / threshold * 100 if threshold > 0 else 0
        expected_burn = elapsed_fraction * 100
        burn_rate = (burned - expected_burn) / expected_burn if expected_burn > 0 else 0
        remaining = max(0, 100 - burned)
        if objective_met:
            status = "ok" if burned < 100 else "warning"
        else:
            status = "exhausted"
    else:
        burned = 0
        remaining = 100
        burn_rate = 0
        status = "ok"
        objective_met = None

    return {
        **slo,
        "total_requests": total_requests,
        "errors": errors,
        "elapsed_days": round(elapsed_days, 2),
        "window_days": window_days,
        "elapsed_fraction": round(elapsed_fraction, 4),
        "budget_burned_pct": round(burned, 2),
        "budget_remaining_pct": round(remaining, 2),
        "burn_rate": round(burn_rate, 4),
        "status": status,
        "objective_met": objective_met,
    }


def generate_slo_report(elapsed_days: float = 15.0, window_days: float = 30.0,
                         total_requests: int = 1000, errors: int = 5) -> dict:
    """生成所有 SLO 状态报告"""
    return {
        "report_date": datetime.now(timezone.utc).isoformat(),
        "elapsed_days": elapsed_days,
        "window_days": window_days,
        "slos": [
            compute_slo_status(s["id"], total_requests=total_requests,
                                errors=errors, elapsed_days=elapsed_days,
                                window_days=window_days)
            for s in SLO_DEFINITIONS
        ],
    }