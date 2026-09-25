"""
In-process metrics (Week 13-14 MVP)

Self-implemented metrics (PEP 668 compatible — no prometheus_client):
- request counter (per endpoint + method + status)
- latency histogram (per endpoint, exponential buckets)
- in-flight gauge
- per-error counter

Exposes Prometheus exposition format at /metrics
+ 4 Golden Signals dashboard at /observability/dashboard

Google SRE book 4 Golden Signals:
1. Traffic (requests/sec)
2. Latency (response time distribution)
3. Errors (5xx / 4xx rate)
4. Saturation (in-flight + resource pressure)
"""
import time
import threading
from collections import defaultdict
from typing import Dict, Tuple


# ============================================
# Metrics storage
# ============================================
_lock = threading.RLock()

# request count: {(endpoint, method, status): count}
_request_count: Dict[Tuple[str, str, int], int] = defaultdict(int)

# latency histogram buckets (seconds): {endpoint: {bucket: count}}
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_latency_buckets: Dict[str, Dict[float, int]] = defaultdict(
    lambda: {b: 0 for b in _BUCKETS}
)
_latency_sum: Dict[str, float] = defaultdict(float)
_latency_count: Dict[str, int] = defaultdict(int)

# in-flight gauge: {endpoint: count}
_in_flight: Dict[str, int] = defaultdict(int)

# error counter: {endpoint: {status: count}}
_error_count: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))

# active tokens (for sat signal)
_active_users: int = 0


# ============================================
# Recording API
# ============================================
def record_request(endpoint: str, method: str, status: int, duration_s: float):
    """每个 HTTP 请求结束时调用"""
    with _lock:
        _request_count[(endpoint, method, status)] += 1
        # latency histogram (count buckets <= duration)
        bucket_map = _latency_buckets[endpoint]
        for b in _BUCKETS:
            if duration_s <= b:
                bucket_map[b] += 1
        # +Inf bucket always counts
        bucket_map[float("inf")] = bucket_map.get(float("inf"), 0) + 1
        _latency_sum[endpoint] += duration_s
        _latency_count[endpoint] += 1
        # errors
        if status >= 400:
            _error_count[endpoint][status] += 1


def incr_in_flight(endpoint: str):
    with _lock:
        _in_flight[endpoint] += 1


def decr_in_flight(endpoint: str):
    with _lock:
        _in_flight[endpoint] = max(0, _in_flight[endpoint] - 1)


def set_active_users(n: int):
    global _active_users
    with _lock:
        _active_users = n


# ============================================
# Prometheus exposition format
# ============================================
def render_prometheus() -> str:
    """生成 Prometheus text exposition format（兼容 Grafana scrape）"""
    lines = []
    with _lock:
        # HELP / TYPE for each metric
        lines.append("# HELP idm_requests_total Total HTTP requests")
        lines.append("# TYPE idm_requests_total counter")
        for (endpoint, method, status), count in sorted(_request_count.items()):
            labels = f'endpoint="{endpoint}",method="{method}",status="{status}"'
            lines.append(f"idm_requests_total{{{labels}}} {count}")

        lines.append("")
        lines.append("# HELP idm_request_duration_seconds Request latency")
        lines.append("# TYPE idm_request_duration_seconds histogram")
        for endpoint, buckets in sorted(_latency_buckets.items()):
            for b in _BUCKETS:
                labels = f'endpoint="{endpoint}",le="{b}"'
                lines.append(f'idm_request_duration_seconds_bucket{{{labels}}} {buckets[b]}')
            # +Inf
            labels = f'endpoint="{endpoint}",le="+Inf"'
            lines.append(f'idm_request_duration_seconds_bucket{{{labels}}} {buckets.get(float("inf"), 0)}')
            # sum + count
            lines.append(f'idm_request_duration_seconds_sum{{endpoint="{endpoint}"}} {_latency_sum[endpoint]:.6f}')
            lines.append(f'idm_request_duration_seconds_count{{endpoint="{endpoint}"}} {_latency_count[endpoint]}')

        lines.append("")
        lines.append("# HELP idm_in_flight_requests In-flight HTTP requests")
        lines.append("# TYPE idm_in_flight_requests gauge")
        for endpoint, count in sorted(_in_flight.items()):
            if count > 0:
                lines.append(f'idm_in_flight_requests{{endpoint="{endpoint}"}} {count}')

        lines.append("")
        lines.append("# HELP idm_errors_total HTTP error responses (>=400)")
        lines.append("# TYPE idm_errors_total counter")
        for endpoint, by_status in sorted(_error_count.items()):
            for status, count in sorted(by_status.items()):
                labels = f'endpoint="{endpoint}",status="{status}"'
                lines.append(f"idm_errors_total{{{labels}}} {count}")

        lines.append("")
        lines.append("# HELP idm_active_users Active user sessions")
        lines.append("# TYPE idm_active_users gauge")
        lines.append(f"idm_active_users {_active_users}")

    return "\n".join(lines) + "\n"


# ============================================
# 4 Golden Signals summary（JSON for dashboard）
# ============================================
def golden_signals_summary() -> dict:
    """返回 4 大黄金信号汇总（dashboard 用）"""
    with _lock:
        total_requests = sum(_request_count.values())
        total_errors = sum(
            sum(by_status.values())
            for by_status in _error_count.values()
        )
        error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0

        # latency p50 / p95 / p99（按 endpoint 算）
        latency_summary = {}
        for endpoint, buckets in _latency_buckets.items():
            total = _latency_count[endpoint]
            if total == 0:
                continue
            # 找到 p50/p95/p99 bucket
            for p, label in [(0.50, "p50"), (0.95, "p95"), (0.99, "p99")]:
                target = total * p
                cumsum = 0
                for b in sorted([x for x in buckets.keys() if x != float("inf")]):
                    cumsum += buckets[b]
                    if cumsum >= target:
                        latency_summary.setdefault(endpoint, {})[label] = round(b * 1000, 2)
                        break
                else:
                    latency_summary.setdefault(endpoint, {})[label] = 10000

        # traffic per endpoint (last snapshot)
        traffic = defaultdict(int)
        for (endpoint, method, status), count in _request_count.items():
            traffic[endpoint] += count

        # saturation
        saturation = dict(_in_flight)

        # by status code
        by_status = defaultdict(int)
        for (ep, m, status), count in _request_count.items():
            by_status[status] += count

    return {
        "total_requests": total_requests,
        "total_errors": total_errors,
        "error_rate_pct": round(error_rate, 2),
        "traffic": dict(traffic),
        "latency_ms": latency_summary,
        "saturation": saturation,
        "by_status": dict(by_status),
        "active_users": _active_users,
    }


# ============================================
# Middleware factory
# ============================================
async def metrics_middleware(request, call_next):
    """FastAPI middleware：记录每个 endpoint 的 latency + status"""
    endpoint = request.url.path
    method = request.method
    incr_in_flight(endpoint)
    start = time.time()
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception as e:
        status = 500
        record_request(endpoint, method, status, time.time() - start)
        raise
    duration = time.time() - start
    record_request(endpoint, method, status, duration)
    decr_in_flight(endpoint)
    # 加 X-Response-Time header
    response.headers["X-Response-Time-Ms"] = f"{duration * 1000:.2f}"
    return response


# ============================================
# Test helpers
# ============================================
def reset_metrics():
    """测试时清空"""
    with _lock:
        _request_count.clear()
        _latency_buckets.clear()
        _latency_sum.clear()
        _latency_count.clear()
        _in_flight.clear()
        _error_count.clear()