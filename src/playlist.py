# -*- coding: utf-8 -*-
"""生成标准化 M3U / TXT（DIYP 格式）播放列表文件。"""
from __future__ import annotations

from pathlib import Path

try:
    from . import config
except ImportError:  # 允许作为独立脚本执行
    import config as config  # type: ignore


# 输出分组顺序（M3U 与 TXT 均按此排列）
GROUP_ORDER: list[str] = ["央视", "卫视", "体育", "港澳台", "少儿", "其它"]
GROUP_INDEX: dict[str, int] = {g: i for i, g in enumerate(GROUP_ORDER)}

# 分组关键词（匹配归一化后的频道名：大写、无空格）
_CCTV_TOKENS = ("CCTV", "CGTN", "中央")
_HMT_TOKENS = (
    "凤凰", "TVB", "翡翠", "明珠", "无线", "星空", "香港", "澳门", "台湾",
    "台北", "台中", "高雄", "台视", "中视", "华视", "民视", "公视", "东森",
    "中天", "三立", "年代", "八大", "纬来", "靖天", "非凡", "壹电视", "港台",
    "澳视", "莲花", "美亚", "天映",
)
_SPORTS_TOKENS = (
    "体育", "足球", "篮球", "排球", "网球", "台球", "斯诺克", "高尔夫", "赛车",
    "F1", "搏击", "格斗", "拳击", "摔跤", "电竞", "王者", "英雄联盟", "LPL",
    "NBA", "CBA", "ESPN", "羽球", "乒乓",
)
_KIDS_TOKENS = (
    "少儿", "儿童", "卡通", "动画", "宝贝", "亲子", "优漫", "宝宝", "玩具",
)


def _group(channel: str) -> str:
    """频道分组：央视 → 港澳台 → 卫视 → 体育 → 少儿 → 其它。

    - 凤凰卫视/星空卫视等港台系归「港澳台」（先于卫视判断）；
    - CCTV 系（含 CCTV5 体育台）统一归「央视」。
    """
    if any(t in channel for t in _CCTV_TOKENS):
        return "央视"
    if any(t in channel for t in _HMT_TOKENS):
        return "港澳台"
    if "卫视" in channel:
        return "卫视"
    if any(t in channel for t in _SPORTS_TOKENS):
        return "体育"
    if any(t in channel for t in _KIDS_TOKENS):
        return "少儿"
    return "其它"


def _sort_key(entry: dict):
    height = (entry.get("quality") or {}).get("height") or 0
    group = _group(entry["channel"])
    return (GROUP_INDEX.get(group, 99), entry["channel"],
            -(height or 0), entry.get("latency_ms") or 1e9)


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
    for gname in GROUP_ORDER:
        if gname not in groups:
            continue
        lines.append(f"{gname},#genre#")
        for e in groups[gname]:
            lines.append(f"{e['channel']},{e['url']}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(entries)
