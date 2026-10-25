# -*- coding: utf-8 -*-
"""冷启动种子：从 2-3 个 awesome-iptv 类「元列表」仓库的 README 提取播放列表链接。

元列表仓库只发布指向播放列表的链接，不发布具体直播流地址，
因此这是唯一允许硬编码的项，且仅用于首次运行引路。

读取通道：GitHub Contents API（api.github.com）—— 全球（含中国大陆）
可达性好于 raw.githubusercontent.com，本地与 CI 均适用。
"""
from __future__ import annotations

import base64
import time

try:
    from .. import config
    from .common import extract_playlist_urls, make_session
except ImportError:  # 允许作为独立脚本执行
    import config as config  # type: ignore
    from common import extract_playlist_urls, make_session  # type: ignore


def _default_branch(repo: str) -> str:
    """通过 GitHub API 解析默认分支，不硬编码 master/main。"""
    try:
        r = make_session().get(
            f"https://api.github.com/repos/{repo}",
            timeout=config.HTTP_TIMEOUT,
            headers={"Accept": "application/vnd.github+json"},
        )
        if r.ok:
            return r.json().get("default_branch", "master")
    except Exception:  # noqa: BLE001
        pass
    return "master"


def _readme_text(repo: str, branch: str) -> str:
    """通过 Contents API 读取仓库 README 文本（base64 解码）。"""
    r = make_session().get(
        f"https://api.github.com/repos/{repo}/readme",
        params={"ref": branch},
        timeout=config.HTTP_TIMEOUT,
        headers={"Accept": "application/vnd.github+json"},
    )
    r.raise_for_status()
    data = r.json()
    if data.get("encoding") == "base64":
        return base64.b64decode(data["content"]).decode("utf-8", "replace")
    return ""


def fetch_seed_playlists() -> set[str]:
    """抓取种子仓库 README，返回其中出现的播放列表 URL 集合。"""
    found: set[str] = set()
    for repo, _readme in config.SEED_REPOS:
        try:
            branch = _default_branch(repo)
            text = _readme_text(repo, branch)
            found |= extract_playlist_urls(text)
            print(f"[seed] {repo} -> {len(found)} playlist urls (cumulative)")
        except Exception as exc:  # noqa: BLE001 单仓库失败不影响整体
            print(f"[seed] skip {repo}: {exc}")
        time.sleep(1)
    return found
