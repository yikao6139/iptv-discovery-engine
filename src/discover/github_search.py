# -*- coding: utf-8 -*-
"""GitHub 搜索发现：Search API 找仓库 → Trees API 定位 m3u 文件 → Contents API 读取内容。

通道策略（重要）：
- 所有发现/读取均走 api.github.com —— 该域名在全球（含中国大陆）可达性远好于
  raw.githubusercontent.com，本地调试与 CI 均可用；
- raw.githubusercontent.com 仅作为「探测常见文件名」的兜底通道（CI 环境可用）。

凭据策略：优先读 GITHUB_TOKEN（Actions 自动注入 secrets.GITHUB_TOKEN，
配额 5000 req/h）；未提供时匿名降级（60 req/h + 10 次搜索/min），
足以支撑每日一次的小规模运行。
"""
from __future__ import annotations

import base64
import os
import re
import time
from typing import Iterable

import requests

try:
    from .. import config
    from .common import fetch_github_file, make_session
except ImportError:  # 允许作为独立脚本执行
    import config as config  # type: ignore
    from common import fetch_github_file, make_session  # type: ignore

_REPO_FILTER = re.compile(r"iptv|m3u|直播|电视|tv.?list|live.?tv", re.IGNORECASE)
_M3U_PATH_RE = re.compile(r"\.m3u8?$", re.IGNORECASE)
_M3U_HINT = re.compile(r"#EXTM3U|#EXTINF", re.IGNORECASE)


class GitHubDiscovery:
    """GitHub 仓库发现器：搜索 → 文件树定位 → 内容读取。"""

    def __init__(self, token: str | None = None, max_repos: int = 25,
                 max_files_per_repo: int = 5):
        self.token = token or config.GITHUB_TOKEN or ""
        self.max_repos = max_repos
        self.max_files_per_repo = max_files_per_repo
        self.session = make_session()
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"
        # 本次运行已读取的播放列表内容：{url: text}，供爬虫直接使用（免二次 HTTP）
        self.prefetched: dict[str, str] = {}

    # ------------------------------------------------------------------ API
    def _api(self, url: str, params: dict) -> dict:
        for attempt in (1, 2):
            try:
                r = self.session.get(url, params=params, timeout=config.HTTP_TIMEOUT)
            except requests.RequestException as exc:
                if attempt == 2:
                    raise
                time.sleep(3)
                continue
            if r.status_code in (403, 429):
                if attempt == 2:
                    raise RuntimeError(
                        "GitHub API rate limited; 请在仓库 Secrets 中配置 "
                        "GITHUB_TOKEN 以提升配额（Actions 默认自动注入）"
                    )
                time.sleep(10)
                continue
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            return r.json()
        raise RuntimeError("unreachable")

    # ------------------------------------------------------------------ 搜索
    def search_repos(self) -> set[str]:
        """按关键词搜索仓库，返回经过主题过滤的 owner/repo 集合。"""
        repos: set[str] = set()
        per = max(1, self.max_repos // max(1, len(config.GITHUB_SEARCH_QUERIES)))
        for q in config.GITHUB_SEARCH_QUERIES:
            try:
                data = self._api(
                    "https://api.github.com/search/repositories",
                    {"q": q, "sort": "updated", "order": "desc", "per_page": per},
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[gh] query '{q}' failed: {exc}")
                continue
            for item in data.get("items", []):
                name = item["full_name"]
                desc = f"{name} {item.get('description') or ''} {' '.join(item.get('topics') or [])}"
                if _REPO_FILTER.search(desc):
                    repos.add(name)
            print(f"[gh] query '{q}' -> +{len(data.get('items', []))} results, pool={len(repos)}")
            time.sleep(2)
        return repos

    # ------------------------------------------------------------------ 定位
    def locate_playlists(self, repos: Iterable[str]) -> set[str]:
        """对每个仓库：默认分支 → 递归文件树找 m3u/m3u8 → Contents API 读取内容。

        返回播放列表 URL 集合；读取到的内容同时存入 self.prefetched。
        """
        playlists: set[str] = set()
        for repo in sorted(repos)[: self.max_repos]:
            branch = self._default_branch(repo)
            if not branch:
                continue
            paths = self._tree_playlist_paths(repo, branch)
            if paths:
                for path in paths:
                    text = self._fetch_contents(repo, path, branch)
                    if text and _M3U_HINT.search(text[:3000]):
                        url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
                        self.prefetched[url] = text
                        playlists.add(url)
            else:
                # 兜底：文件树失败（超大仓库截断/限流）时探测常见文件名
                for fname in config.PLAYLIST_FILENAMES:
                    try:
                        text = fetch_github_file(repo, branch, fname, session=self.session)
                        if _M3U_HINT.search(text[:3000]):
                            playlists.add(f"https://raw.githubusercontent.com/{repo}/{branch}/{fname}")
                            break
                    except Exception:  # noqa: BLE001
                        pass
            # README 中的播放列表链接（awesome 类仓库常用）
            try:
                data = self._api(f"https://api.github.com/repos/{repo}/readme", {"ref": branch})
                if data.get("encoding") == "base64":
                    text = base64.b64decode(data["content"]).decode("utf-8", "replace")
                    # 复用 common 的链接提取
                    from .common import extract_playlist_urls
                    playlists |= extract_playlist_urls(text)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        return playlists

    def _tree_playlist_paths(self, repo: str, branch: str) -> list[str]:
        """递归文件树，返回仓库内 m3u/m3u8 文件路径（根目录优先，限量）。"""
        try:
            data = self._api(
                f"https://api.github.com/repos/{repo}/git/trees/{branch}",
                {"recursive": "1"},
            )
        except Exception:  # noqa: BLE001
            return []
        paths = [
            t["path"] for t in data.get("tree", [])
            if t.get("type") == "blob" and _M3U_PATH_RE.search(t["path"])
            and not t["path"].startswith(("node_modules", "venv", ".git", "dist"))
        ]
        paths.sort(key=lambda p: (p.count("/"), p))  # 根目录文件优先
        return paths[: self.max_files_per_repo]

    def _fetch_contents(self, repo: str, path: str, ref: str) -> str:
        """Contents API 读取文件文本（base64 解码）。"""
        try:
            data = self._api(
                f"https://api.github.com/repos/{repo}/contents/{path}",
                {"ref": ref},
            )
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _default_branch(self, repo: str) -> str:
        try:
            data = self._api(f"https://api.github.com/repos/{repo}", {})
            return data.get("default_branch", "")
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------------ 入口
    def discover(self) -> set[str]:
        repos = self.search_repos()
        print(f"[gh] discovered {len(repos)} candidate repos")
        if not repos:
            return set()
        playlists = self.locate_playlists(repos)
        print(f"[gh] located {len(playlists)} playlists, "
              f"prefetched content: {len(self.prefetched)}")
        return playlists


if __name__ == "__main__":
    # 独立调试入口：python src/discover/github_search.py
    g = GitHubDiscovery(max_repos=5, max_files_per_repo=3)
    found = g.discover()
    for u in sorted(found)[:20]:
        print(u)
    print(f"total={len(found)} prefetched={len(g.prefetched)}")
