
# IdM SRE Lab SLI/SLO 文档（Week 17-18）

> **目标**：Apple IdMS SRE 风格 — 从"可用服务"到"可量化可靠性"的跨越
> **更新日期**：2026-09-25

---

## 4 个核心 SLO（Google SRE 标准）

### 1. Availability — 99.9% 月度

- **目标**：月度可用率 ≥ 99.9%
- **SLI 公式**：`successful_requests / total_requests`
  - successful = HTTP 2xx/3xx + 4xx（4xx 是 client error，不影响 availability）
  - failed = HTTP 5xx
- **Error Budget**：月度 43.2 min（= 30d × 24h × 60min × 0.1%）
- **Burn Rate Alert**：
  - 2% burn in 1h → page
  - 5% burn in 6h → page

### 2. Token Issuance p99 Latency — < 200ms

- **目标**：99% 的 /oauth/token 请求 < 200ms
- **SLI 公式**：`count(requests_under_200ms) / count(total_requests)`
- **实现**：`app/slo/calculator.py: token_p99_latency`
- **依赖**：RS256 JWT 签发 + bcrypt 校验（已用 stdlib）

### 3. SAML AuthnRequest p99 Latency — < 500ms

- **目标**：99% 的 /saml/* AuthnRequest < 500ms
- **SLI 公式**：`count(requests_under_500ms) / count(total_requests)`
- **实现**：`app/slo/calculator.py: saml_p99_latency`
- **依赖**：HMAC-SHA256 签名验证 + XML 解析（std lib）

### 4. Error Rate (5xx) — < 1%

- **目标**：5xx 错误率 < 1%
- **SLI 公式**：`1 - (5xx_count / total_requests)`
- **Alert**：error_rate > 1% (持续 5 分钟) → warning

---

## SLO 报告生成

```bash
# 当前状态
curl http://127.0.0.1:5050/slo/report

# 单个 SLO 详细
curl http://127.0.0.1:5050/slo/availability/status
curl http://127.0.0.1:5050/slo/token_p99_latency/status
curl http://127.0.0.1:5050/slo/saml_p99_latency/status
curl http://127.0.0.1:5050/slo/error_rate/status
```

返回字段：
- `budget_burned_pct` — 已消耗的 budget 百分比
- `budget_remaining_pct` — 剩余 budget 百分比
- `burn_rate` — 燃烧速率（> 1.0 表示 burn 比预期快）
- `status` — `ok` / `warning` / `exhausted`
- `objective_met` — SLO 是否达成

---

## Error Budget 多窗口策略（参考 Google SRE Workbook）

| Burn Rate | Window | Alert 级别 | 响应时间 |
|---|---|---|---|
| 14.4x | 1h | page | immediate |
| 6x | 6h | page | immediate |
| 3x | 24h | ticket | 24h |
| 1x | 3d | email | weekly review |

当前实现：`compute_slo_status()` 返回 `burn_rate` 单值（> 1.0 = 超预期），多窗口可在 Week 21-22 扩展。
