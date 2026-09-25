"""
Observability endpoints（Week 13-14）：
- GET /metrics — Prometheus exposition format
- GET /observability/dashboard — 4 Golden Signals dashboard HTML
- GET /observability/signals — 4 Golden Signals JSON
- GET /observability/health-check — 业务级 health check（DB + JWT + signing key）
"""
from fastapi import APIRouter
from fastapi.responses import Response, HTMLResponse, JSONResponse

from .metrics import render_prometheus, golden_signals_summary

router = APIRouter()


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus scrape endpoint"""
    return Response(content=render_prometheus(), media_type="text/plain; version=0.0.4")


@router.get("/observability/signals")
async def signals():
    """4 Golden Signals JSON summary"""
    return golden_signals_summary()


@router.get("/observability/dashboard", response_class=HTMLResponse)
async def dashboard():
    """4 Golden Signals 可视化 dashboard（极简版）"""
    signals = golden_signals_summary()
    return _render_dashboard_html(signals)


def _render_dashboard_html(s: dict) -> str:
    """渲染 dashboard HTML（Vanilla JS + 简单 layout）"""
    import json as _json
    signals_json = _json.dumps(s)

    # 按 endpoint 渲染表格
    rows_traffic = ""
    all_eps = set(s["traffic"].keys()) | set(s["latency_ms"].keys())
    for ep in sorted(all_eps):
        rows_traffic += f"""
        <tr>
          <td><code>{ep}</code></td>
          <td>{s['traffic'].get(ep, 0)}</td>
          <td>{s['latency_ms'].get(ep, {}).get('p50', '—')} ms</td>
          <td>{s['latency_ms'].get(ep, {}).get('p95', '—')} ms</td>
          <td>{s['latency_ms'].get(ep, {}).get('p99', '—')} ms</td>
        </tr>"""

    by_status_rows = ""
    for status in sorted(s["by_status"].keys()):
        by_status_rows += f"""
        <tr><td><code>{status}</code></td><td>{s['by_status'][status]}</td></tr>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>IdM SRE Lab — 4 Golden Signals</title>
<style>
:root {{
  --bg: #0f1419; --panel: #1a2028; --panel2: #232a36; --border: #2f3845;
  --text: #e6edf3; --text-dim: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --yellow: #d29922; --red: #f85149;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
  background: var(--bg); color: var(--text); padding: 24px 32px; }}
h1 {{ font-size: 22px; margin-bottom: 4px; }}
.meta {{ color: var(--text-dim); font-size: 12px; margin-bottom: 24px; }}
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
.card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 18px 20px; }}
.card .label {{ font-size: 11px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }}
.card .value {{ font-size: 32px; font-weight: 700; margin-top: 6px; }}
.card .sub {{ font-size: 11px; color: var(--text-dim); margin-top: 4px; }}
.section {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
  padding: 18px 20px; margin-bottom: 18px; }}
.section h2 {{ font-size: 14px; margin-bottom: 12px; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 13px; }}
th {{ background: var(--panel2); color: var(--text-dim); text-transform: uppercase; font-size: 11px; }}
code {{ color: var(--accent); }}
.value.good {{ color: var(--green); }}
.value.warn {{ color: var(--yellow); }}
.value.bad {{ color: var(--red); }}
</style>
</head>
<body>
<h1>4 Golden Signals · SRE Observability</h1>
<div class="meta">Google SRE Book · Traffic / Latency / Errors / Saturation · Prometheus exposition at <code>/metrics</code></div>

<div class="cards">
  <div class="card">
    <div class="label">Traffic</div>
    <div class="value">{s['total_requests']}</div>
    <div class="sub">total requests</div>
  </div>
  <div class="card">
    <div class="label">Errors</div>
    <div class="value {'bad' if s['error_rate_pct'] > 5 else 'good'}">{s['error_rate_pct']}%</div>
    <div class="sub">{s['total_errors']} error responses (≥400)</div>
  </div>
  <div class="card">
    <div class="label">Saturation</div>
    <div class="value">{sum(s['saturation'].values())}</div>
    <div class="sub">in-flight requests</div>
  </div>
  <div class="card">
    <div class="label">Active Users</div>
    <div class="value">{s['active_users']}</div>
    <div class="sub">current sessions</div>
  </div>
</div>

<div class="section">
  <h2>Per-Endpoint Traffic + Latency (p50 / p95 / p99)</h2>
  <table>
    <thead><tr><th>Endpoint</th><th>Traffic</th><th>p50</th><th>p95</th><th>p99</th></tr></thead>
    <tbody>{rows_traffic or '<tr><td colspan="5" style="text-align:center;color:var(--text-dim);">No data</td></tr>'}</tbody>
  </table>
</div>

<div class="section">
  <h2>HTTP Status Code Distribution</h2>
  <table>
    <thead><tr><th>Status</th><th>Count</th></tr></thead>
    <tbody>{by_status_rows or '<tr><td colspan="2" style="text-align:center;color:var(--text-dim);">No data</td></tr>'}</tbody>
  </table>
</div>

<script>
// Auto-refresh every 5s
const SIGNALS = {signals_json};
setInterval(() => location.reload(), 5000);
</script>
</body>
</html>"""