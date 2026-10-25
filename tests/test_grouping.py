# -*- coding: utf-8 -*-
"""分组逻辑单元测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.playlist import GROUP_ORDER, _group, _sort_key  # noqa: E402


def test_group_cctv():
    assert _group("CCTV1") == "央视"
    assert _group("CCTV5体育") == "央视"          # CCTV 系统一归央视
    assert _group("CGTN") == "央视"
    assert _group("中央一套") == "央视"


def test_group_weishi():
    assert _group("湖南卫视") == "卫视"
    assert _group("东方卫视") == "卫视"
    assert _group("浙江卫视") == "卫视"


def test_group_hmt():
    assert _group("凤凰卫视") == "港澳台"          # 港台系优先于卫视
    assert _group("翡翠台") == "港澳台"
    assert _group("东森新闻") == "港澳台"
    assert _group("中天综合") == "港澳台"
    assert _group("TVB明珠") == "港澳台"


def test_group_sports():
    assert _group("五星体育") == "体育"
    assert _group("劲爆体育") == "体育"
    assert _group("NBA") == "体育"
    assert _group("风云足球") == "体育"


def test_group_kids():
    assert _group("金鹰卡通") == "少儿"
    assert _group("优漫卡通") == "少儿"
    assert _group("宝贝家") == "少儿"


def test_group_other():
    assert _group("电影频道") == "其它"
    assert _group("综合") == "其它"


def test_group_order_complete():
    assert GROUP_ORDER == ["央视", "卫视", "体育", "港澳台", "少儿", "其它"]


def _entry(channel: str) -> dict:
    return {"channel": channel, "url": "http://x", "quality": {}, "latency_ms": 1}


def test_numeric_sort_cctv():
    """央视带数字的频道按数字从小到大排列。"""
    entries = [_entry(c) for c in
               ("CCTV10", "CCTV2", "CCTV1", "CCTV17", "CCTV5体育", "CCTV3")]
    ordered = sorted(entries, key=_sort_key)
    assert [e["channel"] for e in ordered] == \
        ["CCTV1", "CCTV2", "CCTV3", "CCTV5体育", "CCTV10", "CCTV17"]


def test_numeric_sort_keeps_height_secondary():
    """同一频道内仍按清晰度→延迟排序。"""
    entries = [
        {"channel": "CCTV1", "url": "a", "quality": {"height": 720}, "latency_ms": 5},
        {"channel": "CCTV1", "url": "b", "quality": {"height": 1080}, "latency_ms": 9},
        {"channel": "CCTV1", "url": "c", "quality": {"height": 1080}, "latency_ms": 3},
    ]
    ordered = sorted(entries, key=_sort_key)
    assert [e["url"] for e in ordered] == ["c", "b", "a"]
