# -*- coding: utf-8 -*-
"""URL 与频道名「双重归一化」+ 去重键。

- 频道名归一化：NFKC、去空白/连字符/下划线、大写、去画质后缀、去括号注释。
- URL 归一化：相对路径转绝对、协议/主机小写、去默认端口、去片段、去尾部斜杠。
  （保留 query 原始顺序 —— 部分 CDN 签名 URL 对参数顺序敏感，存储时不得重排。）
- 去重键 canonical_key()：query 排序后的 URL，用于「同流不同参数顺序」识别。
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

QUALITY_TOKENS: list[str] = [
    "4k", "uhd", "fhd", "hd", "sd", "1080p", "720p", "480p", "360p",
    "超清", "高清", "标清", "蓝光", "极清", "流畅", "原画",
]

_GENERIC_NAME_RE = re.compile(
    r"^(index|live|playlist|list|tv|channel|channels|stream|iptv|"
    r"default|master|main|video)([0-9]*)$", re.IGNORECASE
)


def _strip_quality(name: str) -> str:
    """去掉频道名末尾的画质后缀（如 "CCTV-1 高清" -> "CCTV-1"）。"""
    n = name
    for q in QUALITY_TOKENS:
        n = re.sub(rf"[\s\-_]*{re.escape(q)}[\s\-_]*$", "", n, flags=re.IGNORECASE)
    return n


def normalize_channel_name(name: str) -> str:
    """频道名归一化，返回规范去重名（不含画质/注释/空白）。"""
    if not name:
        return ""
    n = unicodedata.normalize("NFKC", str(name))
    n = re.sub(r"[（(][^)）]*[)）]", "", n)          # 去括号注释
    n = _strip_quality(n)
    n = re.sub(r"[\s\-_·]+", "", n)                  # 去空白/横线/下划线
    return n.upper()


def is_generic_channel(name: str) -> bool:
    """判断归一化后的频道名是否为占位性名称（如 INDEX / LIVE / 123）。"""
    n = normalize_channel_name(name)
    if not n or n.isdigit():
        return True
    return bool(_GENERIC_NAME_RE.match(n))


def normalize_url(url: str, base: str | None = None) -> str:
    """URL 归一化（保留 query 顺序，用于存储）。"""
    if not url:
        return ""
    u = str(url).strip()
    if base and not u.lower().startswith(("http://", "https://")):
        from urllib.parse import urljoin
        u = urljoin(base, u)
    try:
        parts = urlsplit(u)
    except ValueError:
        return u
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    # 去默认端口
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    # 保留原始 query 顺序
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def canonical_key(url: str) -> str:
    """去重键：query 排序后的 URL（不改变存储 URL）。"""
    u = normalize_url(url)
    try:
        parts = urlsplit(u)
    except ValueError:
        return u
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", query, ""))
