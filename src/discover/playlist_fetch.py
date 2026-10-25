# -*- coding: utf-8 -*-
"""播放列表爬虫：多级抓取 M3U/M3U8/HTML 页面，提取直播流与嵌套播放列表。

- 带深度限制（默认 2 层）与节点上限，防止失控膨胀。
- HTML 页面：提取播放列表链接 + 直接内嵌的 .m3u8 流地址。
- M3U 文本：解析 EXTINF 频道名与流地址，并跟进嵌套播放列表。
- 所有源地址均来自运行时抓取内容，代码零硬编码。
"""
from __future__ import annotations

import html as html_lib
import re
import time
from urllib.parse import urljoin, urlparse

import requests

try:
    from .. import config
    from .common import (URL_RE, extract_playlist_urls, github_link_to_raw,
                         make_session, parse_m3u_streams)
except ImportError:  # 允许作为独立脚本执行
    import config as config  # type: ignore
    from common import (URL_RE, extract_playlist_urls, github_link_to_raw,  # type: ignore
                        make_session, parse_m3u_streams)

_HTML_HINT = re.compile(r"<html|<!doctype", re.IGNORECASE)
_M3U_HINT = re.compile(r"#EXTM3U|#EXTINF", re.IGNORECASE)
_DIRECT_STREAM_RE = re.compile(r"\.(ts|mp4|flv|aac|mp3|m4s|m4a|ogg)$", re.IGNORECASE)
_GENERIC_STEMS = {
    "index", "live", "playlist", "list", "tv", "channel", "channels",
    "stream", "iptv", "default", "master", "main", "video", "test",
}


def _is_direct_stream(url: str) -> bool:
    """是否为直接媒体地址（非播放列表）。是则无需再当嵌套列表跟随。"""
    path = urlparse(url).path.lower()
    return not bool(re.search(r"\.m3u8?$", path))


def guess_name_from_url(url: str) -> str:
    """从 URL 最后一段文件名猜频道名（无 EXTINF 时的兜底）。"""
    path = urlparse(url).path
    stem = path.rstrip("/").rsplit("/", 1)[-1]
    stem = re.sub(r"\.(m3u8?|ts)$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[_\-.]+", " ", stem).strip()
    return stem


class PlaylistCrawler:
    """有界并发爬虫：从种子 URL 池出发抓取播放列表与直播流。

    - 并发抓取 + 节点上限 + 全局时间预算，防止失控与超时堆积；
    - HTML 页面：提取播放列表链接 + 直接内嵌的 .m3u8 流地址；
    - M3U 文本：解析 EXTINF 频道名与流地址，并跟进嵌套播放列表；
    - 所有源地址均来自运行时抓取内容，代码零硬编码。
    """

    def __init__(self, max_nodes: int = 300, max_depth: int = 2,
                 timeout: float | None = None, concurrency: int = 12,
                 max_runtime: float = 1500.0):
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.timeout = timeout if timeout is not None else config.HTTP_TIMEOUT
        self.concurrency = concurrency
        self.max_runtime = max_runtime
        self.session = make_session()
        self.visited: set[str] = set()
        self.streams: list[tuple[str, str]] = []
        self.fetched = 0
        self.queue: list[tuple[str, int]] = []
        self._t0 = time.monotonic()

    # ------------------------------------------------------------------ 主流程
    def crawl(self, start_urls: set[str],
              prefetched: dict[str, str] | None = None) -> tuple[list[tuple[str, str]], dict]:
        """返回 (直播流列表 [(频道名, url)], 统计)。

        prefetched: {url: 文本内容} —— 已由发现模块（如 GitHub Contents API）
        读取过的播放列表内容，直接解析，免二次 HTTP 抓取。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        prefetched = prefetched or {}
        # 预取内容（秒回）优先于网络抓取，避免排在不可达 URL 后被饿死
        self.queue = [(u, 0) for u in sorted(
            start_urls, key=lambda u: (u not in prefetched, u))]
        while self.queue and self.fetched < self.max_nodes:
            if time.monotonic() - self._t0 > self.max_runtime:
                print("[crawler] global time budget exceeded, stopping")
                break
            batch: list[tuple[str, int]] = []
            while self.queue and len(batch) < self.concurrency * 2:
                url, depth = self.queue.pop(0)
                key = github_link_to_raw(url)
                if key in self.visited or not key.startswith(("http://", "https://")):
                    continue
                self.visited.add(key)
                batch.append((key, depth))
            if not batch:
                break
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                futs = {pool.submit(self._fetch_one, key, depth, prefetched): (key, depth)
                        for key, depth in batch}
                for fut in as_completed(futs):
                    key, depth = futs[fut]
                    try:
                        text = fut.result()
                    except Exception:  # noqa: BLE001 单条失败不影响整体
                        continue
                    if text is None:
                        continue
                    self.fetched += 1
                    self._dispatch(text, key, depth)
            if self.fetched % 50 == 0 or self.fetched >= self.max_nodes:
                print(f"[crawler] fetched={self.fetched} streams={len(self.streams)} "
                      f"queue={len(self.queue)}")
        return self.streams, {"fetched": self.fetched, "visited": len(self.visited)}

    def _fetch_one(self, key: str, depth: int,
                   prefetched: dict[str, str]) -> str | None:
        if key in prefetched:
            return prefetched[key]
        try:
            resp = self.session.get(
                key, timeout=self.timeout,
                headers={"Range": "bytes=0-2097152"},
            )
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        return resp.text

    def _dispatch(self, text: str, url: str, depth: int) -> None:
        if _M3U_HINT.search(text[:3000]):
            self._handle_m3u(text, url, depth)
        elif _HTML_HINT.search(text[:2000]):
            self._handle_html(text, url, depth)
        else:
            self._handle_plain(text, depth)

    # ------------------------------------------------------------------ 分派
    def _enqueue(self, url: str, depth: int) -> None:
        if depth < self.max_depth:
            self.queue.append((url, depth + 1))

    def _accept(self, name: str, url: str) -> bool:
        if len(url) > 2000:
            return False
        if not name:
            return False
        if name.lower() in _GENERIC_STEMS:
            return False
        return True

    def _handle_m3u(self, text: str, url: str, depth: int) -> None:
        named_urls: set[str] = set()
        for name, su in parse_m3u_streams(text, base=url):
            if not su.startswith(("http://", "https://")):
                continue
            name = name or guess_name_from_url(su)
            if self._accept(name, su):
                self.streams.append((name, su))
                named_urls.add(su)
        if depth < self.max_depth:
            # 嵌套播放列表：绝对链接 + 无协议头的相对路径（如 "nested.m3u"）
            nested = extract_playlist_urls(text, base=url)
            for m in re.finditer(r"(?<![\w./])([^\s\"'<>]+\.m3u8?)(\?[^\s\"'<>]*)?",
                                 text, re.IGNORECASE):
                rel = m.group(0)
                if not rel.lower().startswith(("http://", "https://")):
                    nested.add(urljoin(url, rel))
            for pl in nested:
                if pl in named_urls and _is_direct_stream(pl):
                    continue  # 已作为命名流收录的直接媒体地址，无需再抓
                self._enqueue(pl, depth)

    def _handle_html(self, text: str, url: str, depth: int) -> None:
        # 页面内直接内嵌的流地址（如 <source src="xxx.m3u8">）
        for m in URL_RE.finditer(text):
            su = html_lib.unescape(m.group(0)).rstrip(".,;)]}")
            low = su.lower()
            if ".m3u8" in low:
                su = github_link_to_raw(su)
                name = guess_name_from_url(su)
                if self._accept(name, su):
                    self.streams.append((name, su))
        if depth < self.max_depth:
            for pl in extract_playlist_urls(text, base=url):
                self._enqueue(pl, depth)

    def _handle_plain(self, text: str, depth: int) -> None:
        # 无 EXTINF 的裸 URL 列表：每行一个 http 链接
        for raw in text.splitlines():
            line = html_lib.unescape(raw.strip())
            if line.startswith(("http://", "https://")):
                name = guess_name_from_url(line)
                if self._accept(name, line):
                    self.streams.append((name, line))


if __name__ == "__main__":
    # 独立调试入口：python src/discover/playlist_fetch.py
    import sys

    from seed import fetch_seed_playlists

    pool = fetch_seed_playlists()
    if len(sys.argv) > 1:
        pool |= {sys.argv[1]}
    crawler = PlaylistCrawler(max_nodes=60)
    streams, stats = crawler.crawl(pool)
    print(f"[debug] stats={stats}")
    for name, u in streams[:30]:
        print(f"{name} | {u}")
    print(f"streams={len(streams)}")
