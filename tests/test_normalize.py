# -*- coding: utf-8 -*-
"""归一化模块单元测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.normalize import (canonical_key, is_generic_channel,  # noqa: E402
                           normalize_channel_name, normalize_url)


def test_channel_basic():
    assert normalize_channel_name(" CCTV-1 ") == "CCTV1"
    assert normalize_channel_name("cctv1") == "CCTV1"
    assert normalize_channel_name("CCTV-1") == "CCTV1"
    assert normalize_channel_name("cctv_1") == "CCTV1"


def test_channel_quality_suffix():
    assert normalize_channel_name("CCTV-1 高清") == "CCTV1"
    assert normalize_channel_name("湖南卫视(超清)") == "湖南卫视"
    assert normalize_channel_name("浙江卫视HD") == "浙江卫视"
    assert normalize_channel_name("CHC高清电影") == "CHC高清电影"


def test_channel_paren():
    assert normalize_channel_name("CCTV-5(体育)") == "CCTV5"
    assert normalize_channel_name("凤凰卫视（中文台）") == "凤凰卫视"


def test_channel_empty_and_generic():
    assert normalize_channel_name("") == ""
    assert is_generic_channel("") is True
    assert is_generic_channel("index") is True
    assert is_generic_channel("live") is True
    assert is_generic_channel("123") is True
    assert is_generic_channel("CCTV1") is False


def test_url_basic():
    assert normalize_url("HTTP://Example.COM:80/a/") == "http://example.com/a"
    assert normalize_url("https://x.com/b#frag") == "https://x.com/b"
    assert normalize_url("https://x.com:443/b") == "https://x.com/b"


def test_url_relative():
    assert normalize_url("/a.m3u8", base="http://h.com/dir/page") == "http://h.com/a.m3u8"
    assert normalize_url("stream.m3u8", base="http://h.com/dir/") == "http://h.com/dir/stream.m3u8"


def test_url_query_order_preserved():
    assert normalize_url("https://x.com/?b=2&a=1") == "https://x.com/?b=2&a=1"


def test_canonical_key_sorts_query():
    assert canonical_key("https://x.com/?b=2&a=1") == "https://x.com/?a=1&b=2"
    assert canonical_key("https://x.com/?a=1&b=2") == canonical_key("https://x.com/?b=2&a=1")
    assert canonical_key("http://A.com:80/x") == "http://a.com/x"
