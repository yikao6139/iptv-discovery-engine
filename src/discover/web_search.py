# -*- coding: utf-8 -*-
"""全网搜索发现：DuckDuckGo HTML 免密钥接口（尽力而为模块，失败不影响主流程）。

搜索关键词全部来自 config，代码内零硬编码源地址。
"""
from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, unquote, urlparse

import requests

try:
    from .. import config
    from .common import extract_playlist_urls, make_session
except ImportError:  # 允许作为独立脚本执行
    import config as config  # type: ignore
    from common import extract_playlist_urls, make_session  # type: ignore


def _decode_uddg(href: str) -> str:
    """DuckDuckGo 结果链接形如 //duckduckgo.com/l/?uddg=<编码URL>，解码还原。"""
    if href.startswith("//duckduckgo.com/l/?uddg="):
        qs = parse_qs(urlparse(href).query)
        u = qs.get("uddg", [""])[0]
        return unquote(u) if u else ""
    return href


def search_duckduckgo(query: str, max_results: int = 20) -> list[str]:
    """搜索并返回结果页 URL 列表；任何失败返回空列表。"""
    try:
        r = make_session().post(
            "https://html.duckduckgo.com/html/",
            data={"q": query, "kl": "cn-zh"},
            timeout=config.HTTP_TIMEOUT,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"[web] ddg '{query}' failed: {exc}")
        return []
    urls: list[str] = []
    for m in re.finditer(r'href="([^"]+)"', r.text):
        href = _decode_uddg(m.group(1))
        if href.startswith(("http://", "https://")) and href not in urls:
            urls.append(href)
        if len(urls) >= max_results:
            break
    return urls


def discover() -> set[str]:
    """搜索网页并抓取结果页，返回候选播放列表 URL 集合（尽力而为）。"""
    found: set[str] = set()
    for q in config.WEB_SEARCH_QUERIES:
        session = make_session()
        for page_url in search_duckduckgo(q):
            try:
                r = session.get(page_url, timeout=config.HTTP_TIMEOUT)
                if r.status_code != 200:
                    continue
                found |= extract_playlist_urls(r.text, base=page_url)
            except requests.RequestException:
                continue
        print(f"[web] '{q}' -> {len(found)} playlist urls (cumulative)")
        time.sleep(2)
    return found


if __name__ == "__main__":
    # 独立调试入口：python src/discover/web_search.py
    found = discover()
    for u in sorted(found)[:20]:
        print(u)
    print(f"total={len(found)}")
