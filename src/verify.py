# -*- coding: utf-8 -*-
"""流可播放性验证：HTTP 预检 + FFmpeg/ffprobe 真实拉流探测。

核心要求：验证「真实可播放性」而非仅 HTTP 状态码 ——
- 第一关：HTTP GET（带 Range）预检，过滤死链；
- 第二关：ffprobe 读取流信息，必须存在 video 或 audio 流；
- 第三关：ffprobe 失败的源再用 ffmpeg 实际拉取 N 秒（兼容部分保守服务器）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import requests
import urllib3

try:
    from . import config
except ImportError:  # 允许作为独立脚本执行
    import config as config  # type: ignore

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _resolve_bin(name: str) -> str | None:
    """定位 ffmpeg/ffprobe：PATH 优先，其次 IPTV_ENGINE_FFMPEG_DIR 目录。

    目录内可执行文件可能带版本后缀（如 ffmpeg-win-x86_64-v7.1.exe），
    故按 name*.exe 通配匹配。
    """
    import glob

    exe = shutil.which(name)
    if exe:
        return exe
    d = os.environ.get("IPTV_ENGINE_FFMPEG_DIR")
    if d:
        for pat in (os.path.join(d, f"{name}*.exe"),
                    os.path.join(d, f"{name}*")):
            hits = sorted(glob.glob(pat))
            if hits:
                return hits[0]
    return None


@dataclass
class ProbeResult:
    url: str
    ok: bool = False
    latency_ms: float = 0.0
    width: int = 0
    height: int = 0
    codec: str = ""
    reason: str = ""

    def quality_meta(self) -> dict:
        d = {"width": self.width, "height": self.height}
        if self.codec:
            d["codec"] = self.codec
        return d


def _http_precheck(url: str, timeout: float) -> tuple[bool, float, bool]:
    """快速预检。

    返回 (ok, latency_ms, responded)：
    - responded=True 表示服务器有 HTTP 响应（可能 403/405，此类源仍可能可播）；
    - responded=False 表示连接/DNS/读超时，属于死链。
    """
    t0 = time.monotonic()
    responded = False
    try:
        r = requests.get(
            url, timeout=timeout, stream=True,
            headers={"User-Agent": config.UA, "Range": "bytes=0-2048"},
            allow_redirects=True, verify=config.SSL_VERIFY,
        )
        r.close()
        responded = True
        latency = (time.monotonic() - t0) * 1000.0
        return (r.status_code < 400), latency, responded
    except requests.RequestException:
        return False, (time.monotonic() - t0) * 1000.0, responded


def _ffprobe(url: str, timeout: float) -> ProbeResult:
    """ffprobe 解析流信息，必须有 video 或 audio 流才算可播放。"""
    probe = _resolve_bin("ffprobe")
    if probe is None:
        return ProbeResult(url=url, ok=False, reason="ffprobe not installed")
    cmd = [
        probe, "-v", "error",
        "-rw_timeout", "10000000",
        "-user_agent", config.UA,
        "-show_entries", "stream=codec_type,codec_name,width,height",
        "-of", "json", "-i", url,
    ]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ProbeResult(url=url, ok=False, reason="ffprobe timeout")
    latency = (time.monotonic() - t0) * 1000.0
    if proc.returncode != 0:
        return ProbeResult(url=url, ok=False, latency_ms=latency,
                           reason="ffprobe exit!=0")
    try:
        info = json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return ProbeResult(url=url, ok=False, latency_ms=latency,
                           reason="probe json parse fail")
    streams = info.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if not videos and not audios:
        return ProbeResult(url=url, ok=False, latency_ms=latency,
                           reason="no media stream")
    v = videos[0] if videos else {}
    return ProbeResult(
        url=url, ok=True, latency_ms=latency,
        width=int(v.get("width") or 0), height=int(v.get("height") or 0),
        codec=v.get("codec_name") or "", reason="ok",
    )


def _ffmpeg_read_test(url: str, timeout: float) -> ProbeResult:
    """兜底：ffprobe 读不到但实际可播放的源，用 ffmpeg 实测拉流 N 秒。"""
    ffmpeg = _resolve_bin("ffmpeg")
    if ffmpeg is None:
        return ProbeResult(url=url, ok=False, reason="ffmpeg not installed")
    cmd = [
        ffmpeg, "-v", "error",
        "-rw_timeout", "10000000",
        "-user_agent", config.UA,
        "-i", url,
        "-t", str(config.FFMPEG_READ_SECONDS),
        "-c", "copy", "-f", "null", "-",
    ]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ProbeResult(url=url, ok=False, reason="ffmpeg read timeout")
    latency = (time.monotonic() - t0) * 1000.0
    err = proc.stderr.decode("utf-8", "replace").lower()
    if proc.returncode == 0 and "error" not in err:
        return ProbeResult(url=url, ok=True, latency_ms=latency,
                           reason="ffmpeg read ok")
    return ProbeResult(url=url, ok=False, latency_ms=latency,
                       reason="ffmpeg read failed")


def verify_one(url: str, timeout: float | None = None) -> ProbeResult:
    """单个 URL 完整验证：HTTP 预检 → ffprobe → ffmpeg 兜底。"""
    timeout = timeout if timeout is not None else config.FFPROBE_TIMEOUT
    http_ok, latency, responded = _http_precheck(url, config.VERIFY_HTTP_TIMEOUT)
    if not http_ok and not responded:
        # 完全无响应（超时/DNS 失败）才快速淘汰；有响应但非 2xx 仍实测拉流
        return ProbeResult(url=url, ok=False, latency_ms=latency,
                           reason="http precheck fail")
    res = _ffprobe(url, timeout)
    if not res.ok:
        res2 = _ffmpeg_read_test(url, timeout)
        if res2.latency_ms <= 0:
            res2.latency_ms = latency
        return res2
    if res.latency_ms <= 0:
        res.latency_ms = latency
    return res


def verify_batch(urls: list[str], concurrency: int | None = None,
                 timeout: float | None = None) -> dict[str, ProbeResult]:
    """并发验证一批 URL，返回 {url: ProbeResult}；单条异常不影响整体。"""
    concurrency = concurrency if concurrency is not None else config.VERIFY_CONCURRENCY
    results: dict[str, ProbeResult] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {pool.submit(verify_one, u, timeout): u for u in urls}
        for fut in as_completed(futs):
            u = futs[fut]
            try:
                results[u] = fut.result()
            except Exception as exc:  # noqa: BLE001
                results[u] = ProbeResult(url=u, ok=False, reason=f"exc:{exc}")
    return results


if __name__ == "__main__":
    # 独立调试入口：python src/verify.py <url>
    import sys

    if len(sys.argv) < 2:
        print("usage: python src/verify.py <url>")
        raise SystemExit(1)
    res = verify_one(sys.argv[1])
    print(res)
