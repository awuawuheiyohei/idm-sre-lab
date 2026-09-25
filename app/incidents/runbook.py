"""
Runbook library (Week 21-22 MVP)

10 个常见事故 runbook（按 PRD）:
1. HighErrorRate → 5xx 突增
2. HighLatencyP95 → p99 延迟 spike
3. TokenFailureSpike → 401/400 认证失败
4. DatabaseConnectionPool → DB 连接耗尽
5. CertificateExpiry → TLS 证书过期
6. RateLimitExceeded → 客户端 rate limit 触发
7. DiskSpaceLow → 磁盘空间不足
8. CPUSaturation → CPU 高负载
9. MemoryLeak → OOM
10. ServiceDiscoveryFailure → 服务发现失败

每个 runbook：
- alert_name: 对应的 Prometheus alert
- severity: SEV-1/2/3
- steps: 应急响应步骤（每步包含动作 + 验证方法）
- escalation: 升级路径
"""
from typing import List, Dict


RUNBOOKS: List[Dict] = [
    {
        "id": "high_error_rate",
        "alert_name": "HighErrorRate",
        "severity": "SEV-1",
        "title": "HTTP 5xx 错误率突增 (>5%)",
        "indicators": [
            "idm_errors_total 5xx 计数 > 总请求 5%",
            "持续 5+ 分钟",
        ],
        "steps": [
            {"action": "1. 检查 chaos_experiments 表，看是否在跑 chaos 实验（避免误判）",
             "verify": "SELECT * FROM chaos_experiments WHERE status='RUNNING'"},
            {"action": "2. 检查 token-issuer / saml-issuer 最近 deploy（rollback 候选）",
             "verify": "git log --since='2 hours ago' --oneline"},
            {"action": "3. 检查 dependencies（DB / JWT signing key / external IdP）",
             "verify": "GET /health + curl external services"},
            {"action": "4. 看 /logs 找 ERROR 模式（堆栈、5xx 响应体）",
             "verify": "GET /logs?level=ERROR&limit=50"},
            {"action": "5. 如果是 DB 问题：触发 connection pool reset（重启服务）",
             "verify": "kubectl rollout restart deployment/idm"},
        ],
        "escalation": "如果 15 分钟内未缓解 → on-call lead → Incident Commander",
    },
    {
        "id": "high_latency",
        "alert_name": "HighLatencyP95",
        "severity": "SEV-2",
        "title": "p99 延迟 > 1000ms",
        "indicators": [
            "idm_request_duration_seconds_bucket p99 > 1000ms",
        ],
        "steps": [
            {"action": "1. 检查数据库连接池状态",
             "verify": "查 latency_ms 各 endpoint 对比 baseline"},
            {"action": "2. 检查 JWT signing key 缓存（RSA key 缓存 miss 触发重新生成）",
             "verify": "查 rsa_keys.active 计数"},
            {"action": "3. 减少 JWKS 端点的 cache TTL（避免 stale key）",
             "verify": "GET /.well-known/jwks.json 响应时间"},
            {"action": "4. 如果是依赖外部 IdP：检查 SSO flow timeout 配置",
             "verify": "查 /saml/idp-metadata + timeout 设置"},
        ],
        "escalation": "持续 > 30 分钟 → on-call lead",
    },
    {
        "id": "token_failure_spike",
        "alert_name": "TokenFailureSpike",
        "severity": "SEV-1",
        "title": "Token 验证失败突增 (>5 in 100 req)",
        "indicators": [
            "/oauth/introspect active=false 比例升高",
            "401 / 400 错误突增",
        ],
        "steps": [
            {"action": "1. 检查 RSA signing key 状态（是否过期/rotation 没完成）",
             "verify": "GET /.well-known/jwks.json 看 active keys"},
            {"action": "2. 检查 client_secret 是否被误 rotate",
             "verify": "SELECT * FROM oauth_clients"},
            {"action": "3. 检查是否有人在测试 expired token",
             "verify": "查 oauth_audit 中 token_introspect 失败频率"},
            {"action": "4. 如果是 key rotation 中：保留旧 key 至少 24h 让 client 切换",
             "verify": "看 rsa_keys.active 数量 >= 2"},
        ],
        "escalation": "如果影响所有 client → 立即 page security team",
    },
    {
        "id": "database_connection_pool",
        "alert_name": "DatabaseConnectionPool",
        "severity": "SEV-1",
        "title": "数据库连接池耗尽",
        "indicators": [
            "DB connection wait time > 1s",
            "5xx 错误集中在 DB 调用 endpoint",
        ],
        "steps": [
            {"action": "1. 检查连接池配置（busy_timeout / WAL mode）",
             "verify": "查 db.py 中的 busy_timeout 设置"},
            {"action": "2. 杀掉长查询（> 5s）",
             "verify": "PRAGMA busy_timeout = 5000"},
            {"action": "3. 重启服务（释放连接）",
             "verify": "service restart + check connection count"},
            {"action": "4. 临时降级：disable 长 query feature",
             "verify": "latency 恢复 < 200ms"},
        ],
        "escalation": "如果 5 分钟内未缓解 → on-call lead",
    },
    {
        "id": "certificate_expiry",
        "alert_name": "CertificateExpiry",
        "severity": "SEV-2",
        "title": "TLS 证书 30 天内过期",
        "indicators": [
            "RSA key 自创建起 > 720 天",
            "cert notAfter 在 30 天内",
        ],
        "steps": [
            {"action": "1. 检查 RSA key 创建时间",
             "verify": "SELECT kid, created_at FROM rsa_keys"},
            {"action": "2. 生成新 key（保留旧 key 作为轮换过渡）",
             "verify": "新 key active=1, 旧 key 继续 active=1"},
            {"action": "3. 通知所有 client 切换 JWKS endpoint",
             "verify": "client /jwks_uri 缓存 TTL < 24h"},
            {"action": "4. 24h 后撤销旧 key",
             "verify": "UPDATE rsa_keys SET active=0 WHERE kid='old-key'"},
        ],
        "escalation": "提前 7 天预警 → 立即升级 SEV-1",
    },
    {
        "id": "rate_limit_exceeded",
        "alert_name": "RateLimitExceeded",
        "severity": "SEV-3",
        "title": "客户端触发 rate limit",
        "indicators": [
            "特定 client_id 请求 > N/sec",
            "429 响应比例升高",
        ],
        "steps": [
            {"action": "1. 检查 client_id 是否合法",
             "verify": "SELECT * FROM oauth_clients"},
            {"action": "2. 临时增加 rate limit（缓解攻击）",
             "verify": "配置 50 → 100 RPS"},
            {"action": "3. 通知 client 团队让其自我 rate limit",
             "verify": "client 确认收到通知"},
        ],
        "escalation": "持续 > 1 小时 → on-call",
    },
    {
        "id": "disk_space_low",
        "alert_name": "DiskSpaceLow",
        "severity": "SEV-2",
        "title": "磁盘空间 < 10%",
        "indicators": [
            "df -h /data 剩余 < 10%",
            "DB WAL 文件增长失控",
        ],
        "steps": [
            {"action": "1. 检查 DB WAL / SHM 大小",
             "verify": "ls -la data/*.db-wal"},
            {"action": "2. 清理过期 chaos_experiments / incidents",
             "verify": "DELETE FROM chaos_experiments WHERE started_at < date('now', '-30 days')"},
            {"action": "3. 触发 checkpoint 收缩 WAL",
             "verify": "PRAGMA wal_checkpoint(TRUNCATE)"},
        ],
        "escalation": "持续 > 4 小时 → on-call lead",
    },
    {
        "id": "cpu_saturation",
        "alert_name": "CPUSaturation",
        "severity": "SEV-2",
        "title": "CPU > 90% 持续 5 分钟",
        "indicators": [
            "process CPU > 90%",
        ],
        "steps": [
            {"action": "1. 查热点 endpoint（p99 哪个 endpoint 慢）",
             "verify": "GET /observability/signals"},
            {"action": "2. 临时 HPA 扩容（如果有 k8s deployment）",
             "verify": "kubectl scale deployment/idm --replicas=4"},
            {"action": "3. 检查是否有死循环 / 死锁",
             "verify": "py-spy dump --pid <pid>"},
        ],
        "escalation": "立即 → on-call",
    },
    {
        "id": "memory_leak",
        "alert_name": "MemoryLeak",
        "severity": "SEV-1",
        "title": "内存泄漏 → OOM 风险",
        "indicators": [
            "RSS 持续增长不释放",
            "in-flight requests > 10000",
        ],
        "steps": [
            {"action": "1. 抓 heap snapshot（tracemalloc）",
             "verify": "tracemalloc.start()"},
            {"action": "2. 找 top 增长对象",
             "verify": "tracemalloc.get_traced_memory()"},
            {"action": "3. 临时 rollout restart 释放内存",
             "verify": "kubectl rollout restart"},
            {"action": "4. 找 leak 根因（未关闭的 connection / cache 无 eviction）",
             "verify": "查 db_connection() 上下文使用"},
        ],
        "escalation": "立即 → on-call lead",
    },
    {
        "id": "service_discovery_failure",
        "alert_name": "ServiceDiscoveryFailure",
        "severity": "SEV-2",
        "title": "服务发现失败（k8s pod unreachable）",
        "indicators": [
            "Readiness probe fail",
            "Pod restart 循环",
        ],
        "steps": [
            {"action": "1. kubectl describe pod 看 restart reason",
             "verify": "kubectl describe pod"},
            {"action": "2. 检查 DB connection（启动时 init_db）",
             "verify": "GET /health"},
            {"action": "3. 检查 signing key 是否能加载",
             "verify": "GET /.well-known/jwks.json"},
            {"action": "4. 查看 OOMKilled / CrashLoopBackoff",
             "verify": "kubectl get events"},
        ],
        "escalation": "立即 → on-call",
    },
]


def get_runbook_by_alert(alert_name: str) -> dict | None:
    for rb in RUNBOOKS:
        if rb["alert_name"] == alert_name:
            return rb
    return None


def get_runbook_by_id(runbook_id: str) -> dict | None:
    for rb in RUNBOOKS:
        if rb["id"] == runbook_id:
            return rb
    return None


def list_runbooks() -> list:
    return RUNBOOKS


def recommend_runbook(metrics_summary: dict) -> dict | None:
    """根据当前 metrics 推荐 runbook（最相关的）"""
    error_rate = metrics_summary.get("error_rate_pct", 0)
    if error_rate > 5:
        return get_runbook_by_alert("HighErrorRate")

    latency = metrics_summary.get("latency_ms", {})
    for ep, lat in latency.items():
        if isinstance(lat, dict) and lat.get("p99", 0) > 1000:
            return get_runbook_by_alert("HighLatencyP95")

    if metrics_summary.get("total_requests", 0) == 0:
        return get_runbook_by_alert("ServiceDiscoveryFailure")

    return None