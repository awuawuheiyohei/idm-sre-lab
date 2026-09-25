"""
Structured JSON Logging (Week 15-16 MVP)
- 自定义 logging Formatter（输出 JSON 行）
- 内存 ring buffer（最近 N 条）
- log query endpoint（按 level / service / time range 过滤）
- 真实生产用 Loki/ELK（这里是简化版）
"""
import json
import logging
import time
import threading
from collections import deque
from datetime import datetime, timezone, timedelta


# ============================================
# In-memory log ring buffer
# ============================================
_BUFFER_SIZE = 5000
_log_buffer: deque = deque(maxlen=_BUFFER_SIZE)
_buffer_lock = threading.RLock()


class JSONLogFormatter(logging.Formatter):
    """输出 JSON 一行格式的日志"""
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        entry = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        # 附加 extras
        for k, v in record.__dict__.items():
            if k not in ("name", "msg", "args", "levelname", "levelno", "pathname",
                         "filename", "module", "exc_info", "exc_text", "stack_info",
                         "lineno", "funcName", "created", "msecs", "relativeCreated",
                         "thread", "threadName", "processName", "process", "message"):
                entry[k] = v
        return json.dumps(entry, ensure_ascii=False, default=str)


class BufferHandler(logging.Handler):
    """把日志写进 ring buffer（供 /logs endpoint 查询）"""
    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            with _buffer_lock:
                _log_buffer.append(msg)
        except Exception:
            self.handleError(record)


def setup_logging():
    """配置 root logger"""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 清掉已有的 handler（避免重复）
    for h in list(root.handlers):
        root.removeHandler(h)
    # Buffer handler
    buf_handler = BufferHandler()
    buf_handler.setFormatter(JSONLogFormatter())
    root.addHandler(buf_handler)
    # 控制台 handler（保持人可读）
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(console)


# ============================================
# Query helpers
# ============================================
def query_logs(level: str = None, logger: str = None, limit: int = 100,
                since_seconds: int = 3600) -> list:
    """从 ring buffer 查询日志（按 level / logger 过滤）"""
    with _buffer_lock:
        items = list(_log_buffer)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=since_seconds)
    out = []
    for line in reversed(items):
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry["ts"].replace("Z", "+00:00"))
            if ts < cutoff:
                continue
            if level and entry["level"] != level.upper():
                continue
            if logger and entry["logger"] != logger:
                continue
            out.append(entry)
            if len(out) >= limit:
                break
        except Exception:
            continue
    return out


def get_log_stats(since_seconds: int = 3600) -> dict:
    """统计日志 level 分布"""
    entries = query_logs(level=None, logger=None, limit=10000,
                          since_seconds=since_seconds)
    by_level: dict = {}
    by_logger: dict = {}
    for e in entries:
        by_level[e["level"]] = by_level.get(e["level"], 0) + 1
        by_logger[e["logger"]] = by_logger.get(e["logger"], 0) + 1
    return {
        "total_entries": len(entries),
        "by_level": by_level,
        "by_logger": by_logger,
    }