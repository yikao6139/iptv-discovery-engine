# -*- coding: utf-8 -*-
"""发现模块公共工具：HTTP 抓取、链接翻译、播放列表/流地址提取。"""
from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin

import requests

try:
    from .. import config
except ImportError:  # 允许作为独立脚本执行
    import config as config  # type: ignore

URL_RE = re.compile(r"https?://[^\s\"'<>()\[\]]+", re.IGNORECASE)
PLAYLIST_EXT_RE = re.compile(r"\.(m3u8?|txt)(\?[^\s\"'<>]*)?$", re.IGNORECASE)


def make_session() -> requests.Session:
    """创建统一 UA / SSL 策略的会话。"""
    import urllib3

    s = requests.Session()
    s.headers["User-Agent"] = config.UA
    if not config.SSL_VERIFY:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    s.verify = config.SSL_VERIFY
    return s


def http_get(url: str, timeout: float | None = None,
             session: requests.Session | None = None,
             headers: dict | None = None) -> str:
    """GET 并返回文本；失败抛异常由调用方决定跳过。"""
    s = session or make_session()
    h = {"User-Agent": config.UA}
    if headers:
        h.update(headers)
    resp = s.get(url, timeout=timeout or config.HTTP_TIMEOUT, headers=h)
    resp.raise_for_status()
    return resp.text


def github_link_to_raw(u: str) -> str:
    """github.com/owner/repo/blob/branch/path 转 raw.githubusercontent.com 直链。"""
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/blob/([^/]+)/(.+)$", u)
    if m:
        owner_repo, branch, path = m.groups()
        return f"https://raw.githubusercontent.com/{owner_repo}/{branch}/{path}"
    return u


def github_file_urls(owner_repo: str, branch: str, path: str) -> list[str]:
    """同一 GitHub 文件的多通道直链：raw.githubusercontent 优先，jsDelivr CDN 兜底。

    jsDelivr 为公开 CDN 镜像（cdn.jsdelivr.net/gh/owner/repo@branch/path），
    在国内网络下可达性通常优于 raw 域名，用于增强本地调试与 CI 韧性。
    """
    raw = f"https://raw.githubusercontent.com/{owner_repo}/{branch}/{path}"
    jd = f"https://cdn.jsdelivr.net/gh/{owner_repo}@{branch}/{path}"
    return [raw, jd]


def fetch_github_file(owner_repo: str, branch: str, path: str,
                      session: requests.Session | None = None) -> str:
    """按多通道顺序抓取 GitHub 原始文件，全部失败抛异常。"""
    s = session or make_session()
    last_exc: Exception | None = None
    for url in github_file_urls(owner_repo, branch, path):
        try:
            resp = s.get(url, timeout=config.HTTP_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            last_exc = RuntimeError(f"HTTP {resp.status_code} for {url}")
        except requests.RequestException as exc:
            last_exc = exc
    raise RuntimeError(f"all github file channels failed for "
                       f"{owner_repo}/{branch}/{path}: {last_exc}")


def is_playlist_url(url: str) -> bool:
    path = url.split("?", 1)[0].split("#", 1)[0]
    return bool(PLAYLIST_EXT_RE.search(path))


def extract_playlist_urls(text: str, base: str | None = None) -> set[str]:
    """从网页/Markdown/播放列表文本中提取 .m3u/.m3u8/.txt 链接（去重）。"""
    out: set[str] = set()
    for m in URL_RE.finditer(text):
        u = html_lib.unescape(m.group(0)).rstrip(".,;)]}")
        if not is_playlist_url(u):
            continue
        if base and not u.lower().startswith(("http://", "https://")):
            u = urljoin(base, u)
        u = github_link_to_raw(u)
        out.add(u)
    return out


def parse_m3u_streams(text: str, base: str | None = None) -> list[tuple[str, str]]:
    """解析 M3U/M3U8 文本，返回 [(频道名, url)]。

    - 支持相对路径 URL（有 base 时 urljoin 解析，如 "nested.m3u"）；
    - 无 EXTINF 的 URL 行频道名置空串。
    """
    out: list[tuple[str, str]] = []
    pending_name: str | None = None
    for raw in text.splitlines():
        line = html_lib.unescape(raw.strip())
        if not line:
            continue
        if line.startswith("#EXTINF"):
            m = re.search(r",\s*([^,]+)$", line)
            pending_name = m.group(1).strip() if m else None
        elif line.startswith("#"):
            continue
        else:
            u = line
            if u.lower().startswith(("http://", "https://")):
                pass
            elif (base and "://" not in u and "." in u
                  and not any(c in u for c in " \t\"'<>")):
                u = urljoin(base, u)
            else:
                continue
            u = github_link_to_raw(u)
            out.append(((pending_name or "").strip(), u))
            pending_name = None
    return out
