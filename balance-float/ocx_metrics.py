# -*- coding: utf-8 -*-
"""
OCX 指标后端：只读本机 ~/.opencodex/usage.jsonl，不高频打 OCX HTTP。

- 今日总请求 / 总 token / 平均延迟（整个 API 端口合计，不按模型拆）
- 输出 token 速度曲线：默认 30 秒滚动窗口，过期点自动删除
- 轮询间隔可调（接口/配置），避免持续请求 OCX 增加负担
"""
import json
import os
import threading
import time
from collections import deque
from datetime import date
from pathlib import Path

USAGE_PATH = Path.home() / ".opencodex" / "usage.jsonl"
DEFAULT_ENDPOINT = "http://127.0.0.1:10100"
# 可调范围：轮询本地账本的间隔（秒）。默认 3s，禁止 <1s，避免无意义 IO
DEFAULT_INTERVAL = 3.0
MIN_INTERVAL = 1.0
MAX_INTERVAL = 60.0
DEFAULT_WINDOW = 30.0
MIN_WINDOW = 10.0
MAX_WINDOW = 120.0


def _num(*vals):
    for v in vals:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, dict):
            for k in ("amount", "usd", "value", "cost", "tokens"):
                if isinstance(v.get(k), (int, float)):
                    return float(v[k])
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                continue
    return 0.0


def _parse_row(row):
    if not isinstance(row, dict):
        return None
    ts = row.get("timestamp")
    if not isinstance(ts, (int, float)):
        return None
    sec = ts / 1000.0 if ts > 1e12 else float(ts)
    usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
    inn = _num(usage.get("inputTokens"), usage.get("input_tokens"), usage.get("promptTokens"))
    out = _num(usage.get("outputTokens"), usage.get("output_tokens"), usage.get("completionTokens"))
    tot = _num(usage.get("totalTokens"), row.get("totalTokens")) or (inn + out)
    cache_r = _num(usage.get("cacheReadInputTokens"), usage.get("cacheReadTokens"),
                   usage.get("cachedInputTokens"))
    status = row.get("status")
    ok = isinstance(status, int) and 200 <= status < 300
    dur = row.get("durationMs")
    ttft = row.get("firstOutputMs")
    return {
        "ts": sec,
        "day": time.strftime("%Y-%m-%d", time.localtime(sec)),
        "in": inn,
        "out": out,
        "total": tot,
        "cache_r": cache_r,
        "ok": bool(ok),
        "dur": float(dur) if isinstance(dur, (int, float)) else None,
        "ttft": float(ttft) if isinstance(ttft, (int, float)) else None,
    }


class OcxMetrics:
    """整个 OCX API 端口的合计指标 + 短时输出速度曲线。"""

    def __init__(self, usage_path=None, endpoint=DEFAULT_ENDPOINT):
        self.usage_path = Path(usage_path or USAGE_PATH)
        self.endpoint = endpoint
        self.interval = DEFAULT_INTERVAL
        self.window = DEFAULT_WINDOW
        self.enabled = True
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._file_pos = 0
        self._day = date.today().isoformat()
        self._today = {
            "requests": 0,
            "ok_requests": 0,
            "tokens_total": 0.0,
            "tokens_input": 0.0,
            "tokens_output": 0.0,
            "cache_read_tokens": 0.0,
            "latency_sum": 0.0,
            "latency_n": 0,
            "ttft_sum": 0.0,
            "ttft_n": 0,
        }
        # 滚动速度点：{"ts", "output_tokens", "out_tok_per_s", "requests"}
        self._points = deque()
        self._last_poll_ts = None
        self._last_out_delta = 0.0
        self._last_req_delta = 0
        self._prev_out = 0.0
        self._prev_req = 0
        self._last_error = ""
        self._last_ok = False
        self._poll_count = 0

    # ---------- 配置 ----------
    def set_config(self, interval=None, window=None, enabled=None):
        # 只改参数、不碰线程：_loop 用 _wake 提前醒来用新参数，重启线程反而会把自己停死
        with self._lock:
            if interval is not None:
                try:
                    iv = float(interval)
                except (TypeError, ValueError):
                    return False, "interval 必须是数字"
                self.interval = max(MIN_INTERVAL, min(MAX_INTERVAL, iv))
            if window is not None:
                try:
                    w = float(window)
                except (TypeError, ValueError):
                    return False, "window 必须是数字"
                self.window = max(MIN_WINDOW, min(MAX_WINDOW, w))
            if enabled is not None:
                self.enabled = bool(enabled)
        # 间隔/开关变了，让后台循环立刻按新参数走一轮
        self._wake.set()
        return True, self.config()

    def config(self):
        return {
            "interval_seconds": self.interval,
            "window_seconds": self.window,
            "enabled": self.enabled,
            "endpoint": self.endpoint,
            "usage_path": str(self.usage_path),
            "min_interval": MIN_INTERVAL,
            "max_interval": MAX_INTERVAL,
            "min_window": MIN_WINDOW,
            "max_window": MAX_WINDOW,
            "note": "仅读本机 usage.jsonl，不按间隔请求 OCX HTTP；HTTP 仅在列表探测时使用",
        }

    # ---------- 账本读取 ----------
    def _reset_today(self, day):
        self._day = day
        self._today = {
            "requests": 0,
            "ok_requests": 0,
            "tokens_total": 0.0,
            "tokens_input": 0.0,
            "tokens_output": 0.0,
            "cache_read_tokens": 0.0,
            "latency_sum": 0.0,
            "latency_n": 0,
            "ttft_sum": 0.0,
            "ttft_n": 0,
        }
        self._points.clear()
        self._file_pos = 0
        self._last_poll_ts = None
        self._last_out_delta = 0.0
        self._last_req_delta = 0

    def _apply_row(self, r, today_day):
        if r["day"] != today_day:
            return
        t = self._today
        t["requests"] += 1
        if r["ok"]:
            t["ok_requests"] += 1
            t["tokens_total"] += r["total"]
            t["tokens_input"] += r["in"]
            t["tokens_output"] += r["out"]
            t["cache_read_tokens"] += r["cache_r"]
            if r["dur"] is not None:
                t["latency_sum"] += r["dur"]
                t["latency_n"] += 1
            if r["ttft"] is not None:
                t["ttft_sum"] += r["ttft"]
                t["ttft_n"] += 1

    def _read_new_rows(self, today_day):
        """增量读 usage.jsonl；跨日或文件变小则全量重扫。"""
        if not self.usage_path.is_file():
            self._last_ok = False
            self._last_error = "usage.jsonl 不存在: %s" % self.usage_path
            return 0
        try:
            size = self.usage_path.stat().st_size
        except OSError as e:
            self._last_ok = False
            self._last_error = str(e)
            return 0
        full = False
        if today_day != self._day or size < self._file_pos:
            self._reset_today(today_day)
            full = True
        n = 0
        try:
            with self.usage_path.open("r", encoding="utf-8", errors="replace") as f:
                if not full:
                    f.seek(self._file_pos)
                while True:
                    line = f.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    r = _parse_row(row)
                    if r:
                        self._apply_row(r, today_day)
                        n += 1
                self._file_pos = f.tell()
            self._last_ok = True
            self._last_error = ""
        except OSError as e:
            self._last_ok = False
            self._last_error = "%s: %s" % (type(e).__name__, e)
        return n

    def _push_speed_point(self, now, prev_out, prev_req):
        """用本轮 poll 前后的累计差，推入一个速度点，并丢弃窗口外过期点。"""
        if self._last_poll_ts is None:
            self._last_poll_ts = now
            self._prev_out = self._today["tokens_output"]
            self._prev_req = self._today["requests"]
            return
        dt = now - self._last_poll_ts
        if dt <= 0:
            return
        d_out = self._today["tokens_output"] - prev_out
        d_req = self._today["requests"] - prev_req
        if d_out < 0:
            d_out = 0.0
        if d_req < 0:
            d_req = 0
        self._points.append({
            "ts": now,
            "output_tokens": d_out,
            "out_tok_per_s": d_out / dt,
            "requests": d_req,
        })
        cutoff = now - self.window
        while self._points and self._points[0]["ts"] < cutoff:
            self._points.popleft()
        self._last_poll_ts = now
        self._last_out_delta = d_out
        self._last_req_delta = d_req
        self._prev_out = self._today["tokens_output"]
        self._prev_req = self._today["requests"]

    def poll_once(self):
        """读一次本地账本，更新今日合计与速度点。不请求 OCX HTTP。"""
        with self._lock:
            if not self.enabled:
                return self._snapshot_unlocked()
            today_day = date.today().isoformat()
            prev_out = self._today["tokens_output"]
            prev_req = self._today["requests"]
            self._read_new_rows(today_day)
            now = time.time()
            self._push_speed_point(now, prev_out, prev_req)
            self._poll_count += 1
            return self._snapshot_unlocked()

    def snapshot(self):
        with self._lock:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self):
        t = self._today
        avg_lat = (t["latency_sum"] / t["latency_n"]) if t["latency_n"] else None
        avg_ttft = (t["ttft_sum"] / t["ttft_n"]) if t["ttft_n"] else None
        pts = list(self._points)
        if pts:
            span = max(pts[-1]["ts"] - pts[0]["ts"], self.interval if self.interval > 0 else 1.0)
            if len(pts) == 1:
                span = max(self.interval, 1.0)
            window_out = sum(p["output_tokens"] for p in pts)
            current_rate = window_out / span
        else:
            current_rate = 0.0
        return {
            "ok": self._last_ok,
            "error": self._last_error,
            "endpoint": self.endpoint,
            "day": self._day,
            "poll_count": self._poll_count,
            "today": {
                "requests": int(t["requests"]),
                "ok_requests": int(t["ok_requests"]),
                "tokens_total": int(t["tokens_total"]),
                "tokens_input": int(t["tokens_input"]),
                "tokens_output": int(t["tokens_output"]),
                "cache_read_tokens": int(t["cache_read_tokens"]),
                "avg_latency_ms": round(avg_lat, 1) if avg_lat is not None else None,
                "avg_ttft_ms": round(avg_ttft, 1) if avg_ttft is not None else None,
            },
            "speed": {
                "window_seconds": self.window,
                "interval_seconds": self.interval,
                "current_out_tok_per_s": round(current_rate, 2),
                "points": [
                    {
                        "ts": p["ts"],
                        "t": time.strftime("%H:%M:%S", time.localtime(p["ts"])),
                        "output_tokens": int(p["output_tokens"]),
                        "out_tok_per_s": round(p["out_tok_per_s"], 2),
                        "requests": p["requests"],
                    }
                    for p in pts
                ],
            },
            "config": self.config(),
        }

    # ---------- 后台循环 ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._loop, name="ocx-metrics", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def _loop(self):
        # 启动立刻扫一遍，之后按 interval 轮询本地文件
        try:
            self.poll_once()
        except Exception as e:
            self._last_ok = False
            self._last_error = "%s: %s" % (type(e).__name__, e)
        while not self._stop.is_set():
            # 等 _wake 而不是 _stop：set_config/stop 都会置位 _wake，参数改了立刻按新间隔走，
            # 不必等满旧间隔（stop 也置位 _wake，所以退出同样及时）
            self._wake.wait(self.interval)
            self._wake.clear()
            if self._stop.is_set():
                break
            if not self.enabled:
                continue
            try:
                self.poll_once()
            except Exception as e:
                self._last_ok = False
                self._last_error = "%s: %s" % (type(e).__name__, e)

# 模块级单例（float_window / demo 共用）
metrics = OcxMetrics()
