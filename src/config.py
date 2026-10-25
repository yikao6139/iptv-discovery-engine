# -*- coding: utf-8 -*-
"""集中配置模块。

设计约束（最高优先级）：
1. 除「冷启动种子」外，本文件及全部代码不得硬编码任何具体 IPTV 源地址。
   种子仓库属于 awesome-iptv 类「元列表」仓库 —— 它们发布的是指向播放列表
   的链接，而非具体的直播流地址，仅用于首次运行引路。
2. 所有源地址必须由运行时「发现模块」通过网络请求动态获得。
3. 所有可调参数集中于此，便于调整而不改动逻辑。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # 项目根目录（src/ 的上一级）
SOURCES_DIR = BASE_DIR / "sources"
OUTPUT_DIR = BASE_DIR / "output"

REGISTRY_PATH = SOURCES_DIR / "registry.json"

# ---------------------------------------------------------------------------
# 冷启动种子（唯一允许的硬编码项，仅 2-3 个 awesome-iptv 类元列表仓库）
# 元组：仓库全名 + README 文件名。默认分支在运行时通过 GitHub API 解析，
# 不硬编码 master/main。
# ---------------------------------------------------------------------------
SEED_REPOS: list[tuple[str, str]] = [
    ("iptv-org/awesome-iptv", "README.md"),
    ("iptv-org/iptv", "README.md"),
    ("imDazui/Tvlist-awesome-m3u-m3u8", "README.md"),
]

# 仓库中常见的播放列表文件名（探测用，非源地址）
PLAYLIST_FILENAMES: list[str] = [
    "playlist.m3u", "tv.m3u", "live.m3u", "list.m3u", "iptv.m3u",
    "index.m3u", "all.m3u", "channels.m3u", "tv.m3u8", "live.m3u8",
    "iptv.m3u8", "playlist.m3u8", "index.m3u8",
]

# GitHub 仓库搜索关键词（运行时传给 Search API，全部为关键词而非源地址）
GITHUB_SEARCH_QUERIES: list[str] = [
    "iptv m3u playlist",
    "iptv m3u8",
    "tv m3u live stream",
    "ipv6 iptv m3u",
    "m3u8 直播源",
    "iptv playlist github",
    "m3u iptv 电视直播",
    "live tv m3u8",
]

# 网页搜索关键词（DuckDuckGo HTML 免密钥接口）
WEB_SEARCH_QUERIES: list[str] = [
    "iptv m3u playlist",
    "m3u8 直播源",
    "tv m3u8 live stream",
    "iptv playlist github m3u",
]

# 网络参数
HTTP_TIMEOUT: float = 15.0          # 秒
VERIFY_HTTP_TIMEOUT: float = 8.0    # 验证前 HTTP 预检超时
UA: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 流可播放性验证参数（真实拉流探测，非仅 HTTP 状态码）
FFPROBE_TIMEOUT: float = 20.0       # 秒
FFMPEG_READ_SECONDS: int = 5        # ffmpeg 兜底实测拉流秒数
VERIFY_CONCURRENCY: int = 16        # 并发验证线程数

# 失效淘汰：连续失败 N 次即从注册表删除
MAX_CONSECUTIVE_FAILURES: int = 3

# 复验周期（小时）：超过该时长的历史源在每日运行中重新验证
REVERIFY_AFTER_HOURS: float = 24.0

# 输出文件名（生成 live.m3u / live.txt）
PLAYLIST_NAME: str = "live"

# 环境变量：GitHub Token（Actions 自动注入 secrets.GITHUB_TOKEN；本地可选）
GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""

# SSL 证书校验开关。GitHub Actions 系统 Python 证书链正常，保持开启；
# 仅当本地调试环境证书链损坏（CERTIFICATE_VERIFY_FAILED）时，
# 设置环境变量 IPTV_ENGINE_SSL_VERIFY=0 临时关闭。
SSL_VERIFY: bool = os.environ.get("IPTV_ENGINE_SSL_VERIFY", "1") != "0"
