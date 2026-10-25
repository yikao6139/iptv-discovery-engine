# -*- coding: utf-8 -*-
"""生成标准化 M3U / TXT（DIYP 格式）播放列表文件。"""
from __future__ import annotations

from pathlib import Path

try:
    from . import config
except ImportError:  # 允许作为独立脚本执行
    import config as config  # type: ignore


def _group(channel: str) -> str:
    """轻量分组：央视→央视；含「卫视」→卫视；其它→综合。"""
    if channel.startswith("CCTV"):
        return "央视"
    if "卫视" in channel:
        return "卫视"
    return "综合"


def _sort_key(entry: dict):
    height = (entry.get("quality") or {}).get("height") or 0
    return (entry["channel"], -(height or 0), entry.get("latency_ms") or 1e9)


def _escape_attr(s: str) -> str:
    return s.replace('"', "").replace("\\", "").replace("\n", " ")


def write_m3u(entries: list[dict], path: Path) -> int:
    """生成标准 M3U 文件，返回频道条目数。按频道名→清晰度→延迟排序。"""
    lines = ["#EXTM3U"]
    for e in sorted(entries, key=_sort_key):
        name = _escape_attr(e["channel"])
        group = _group(e["channel"])
        lines.append(
            f'#EXTINF:-1 tvg-id="{name}" tvg-name="{name}" '
            f'group-title="{group}",{name}'
        )
        lines.append(e["url"])
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(entries)


def write_txt(entries: list[dict], path: Path) -> int:
    """生成 DIYP/百川 兼容 TXT：分组头（频道,#genre#）+ channel,url。"""
    groups: dict[str, list[dict]] = {}
    for e in sorted(entries, key=_sort_key):
        groups.setdefault(_group(e["channel"]), []).append(e)
    lines: list[str] = []
    for gname in sorted(groups):
        lines.append(f"{gname},#genre#")
        for e in groups[gname]:
            lines.append(f"{e['channel']},{e['url']}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(entries)
