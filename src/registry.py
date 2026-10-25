# -*- coding: utf-8 -*-
"""动态注册表：sources/registry.json 的读写与生命周期管理。

每日增删全部由程序自动完成，禁止人工维护。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from . import config
except ImportError:  # 允许作为独立脚本执行
    import config as config  # type: ignore


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def source_id(channel: str, url: str) -> str:
    """稳定 ID：由归一化后的 (channel, url) 哈希而来，跨日可追踪。"""
    key = f"{channel}||{url}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


class Registry:
    """线程安全的 JSON 注册表，原子写入。"""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config.REGISTRY_PATH
        self._lock = threading.RLock()
        self.data: dict[str, Any] = {"meta": {"version": 1}, "sources": {}}
        self.load()

    # ------------------------------------------------------------------ 读写
    def load(self) -> None:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            self.data = raw
            self.data.setdefault("meta", {"version": 1})
            self.data.setdefault("sources", {})
        else:
            self.data = {"meta": {"version": 1}, "sources": {}}

    def save(self) -> None:
        """原子写：先写临时文件再 os.replace，避免进程中断留下半截 JSON。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # ------------------------------------------------------------------ 增
    def upsert_candidate(self, channel: str, url: str, origin: str,
                         quality: dict | None = None,
                         latency_ms: float | None = None) -> str:
        """新增候选或更新已有条目，返回 source_id。"""
        sid = source_id(channel, url)
        now = utcnow_iso()
        with self._lock:
            src = self.data["sources"].get(sid)
            if src is None:
                self.data["sources"][sid] = {
                    "id": sid,
                    "channel": channel,
                    "url": url,
                    "origin": origin,
                    "discovered_at": now,
                    "last_verified_at": None,
                    "verify_status": "pending",
                    "consecutive_failures": 0,
                    "quality": quality or {},
                    "latency_ms": latency_ms,
                }
            else:
                src.setdefault("origin", origin)
                if quality:
                    src["quality"] = quality
                if latency_ms is not None:
                    src["latency_ms"] = round(latency_ms, 1)
            return sid

    # ------------------------------------------------------------------ 改
    def mark_verified(self, sid: str, latency_ms: float | None = None,
                      quality: dict | None = None) -> None:
        with self._lock:
            src = self.data["sources"].get(sid)
            if not src:
                return
            src["verify_status"] = "ok"
            src["consecutive_failures"] = 0
            src["last_verified_at"] = utcnow_iso()
            if latency_ms is not None:
                src["latency_ms"] = round(latency_ms, 1)
            if quality:
                src["quality"] = quality

    def mark_failed(self, sid: str) -> None:
        with self._lock:
            src = self.data["sources"].get(sid)
            if not src:
                return
            src["verify_status"] = "fail"
            src["consecutive_failures"] = int(src.get("consecutive_failures", 0)) + 1
            src["last_verified_at"] = utcnow_iso()

    def should_reverify(self, sid: str, hours: float | None = None) -> bool:
        """超过复验周期（或从未验证）的条目需要重新验证。"""
        hours = hours if hours is not None else config.REVERIFY_AFTER_HOURS
        src = self.data["sources"].get(sid)
        if not src:
            return True
        last = src.get("last_verified_at")
        if not last:
            return True
        try:
            t = datetime.fromisoformat(last)
        except ValueError:
            return True
        age = (datetime.now(timezone.utc) - t).total_seconds() / 3600.0
        return age >= hours

    # ------------------------------------------------------------------ 删
    def evict_failures(self, max_fail: int | None = None) -> list[str]:
        """淘汰连续失败达到阈值的条目，返回被淘汰的 id 列表。"""
        max_fail = max_fail if max_fail is not None else config.MAX_CONSECUTIVE_FAILURES
        dead: list[str] = []
        with self._lock:
            for sid, src in list(self.data["sources"].items()):
                if int(src.get("consecutive_failures", 0)) >= max_fail:
                    dead.append(sid)
                    del self.data["sources"][sid]
        return dead

    # ------------------------------------------------------------------ 查
    def valid_entries(self) -> list[dict]:
        """当前验证通过的源（用于生成播放列表）。"""
        return [s for s in self.data["sources"].values()
                if s.get("verify_status") == "ok"]

    def pending_entries(self) -> list[dict]:
        return [s for s in self.data["sources"].values()
                if s.get("verify_status") != "ok"]

    def __len__(self) -> int:
        return len(self.data["sources"])

    def summary(self) -> dict[str, int]:
        vals = self.data["sources"].values()
        return {
            "total": len(vals),
            "ok": sum(1 for v in vals if v.get("verify_status") == "ok"),
            "pending": sum(1 for v in vals if v.get("verify_status") != "ok"),
        }
