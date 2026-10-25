# -*- coding: utf-8 -*-
"""注册表与解析模块单元测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.discover.common import extract_playlist_urls, parse_m3u_streams  # noqa: E402
from src.registry import Registry  # noqa: E402


def test_registry_lifecycle(tmp_path):
    r = Registry(tmp_path / "registry.json")
    sid = r.upsert_candidate("CCTV1", "http://a.example.com/1", "test-origin")
    assert sid
    assert len(r) == 1
    assert r.data["sources"][sid]["verify_status"] == "pending"

    r.mark_verified(sid, latency_ms=123.4, quality={"width": 1920, "height": 1080})
    assert len(r.valid_entries()) == 1
    assert r.data["sources"][sid]["consecutive_failures"] == 0

    # 同 (channel, url) 幂等：不重复入库
    sid2 = r.upsert_candidate("CCTV1", "http://a.example.com/1", "another")
    assert sid2 == sid
    assert len(r) == 1

    # 连续失败 3 次后淘汰
    for _ in range(3):
        r.mark_failed(sid)
    evicted = r.evict_failures(max_fail=3)
    assert sid in evicted
    assert len(r) == 0

    # 原子落盘后可重载
    r.upsert_candidate("CCTV2", "http://b.example.com/2", "t")
    r.save()
    r2 = Registry(tmp_path / "registry.json")
    assert len(r2) == 1


def test_parse_m3u_streams():
    m3u = """#EXTM3U
#EXTINF:-1,CCTV-1 高清
http://a.example.com/cctv1.m3u8
#EXTINF:-1,湖南卫视
http://b.example.com/hnws
#EXT-X-STREAM-INF:BANDWIDTH=1000
http://c.example.com/variant.m3u8
"""
    out = parse_m3u_streams(m3u)
    assert ("CCTV-1 高清", "http://a.example.com/cctv1.m3u8") in out
    assert ("湖南卫视", "http://b.example.com/hnws") in out
    # 无 EXTINF 的行 → 频道名为空串
    assert ("", "http://c.example.com/variant.m3u8") in out


def test_extract_playlist_urls():
    text = (
        "see https://raw.githubusercontent.com/a/b/master/tv.m3u and "
        "http://example.com/list.m3u8?x=1 and https://github.com/a/b/blob/main/tv.m3u "
        "and https://example.com/not-a-playlist.html"
    )
    found = extract_playlist_urls(text)
    assert "https://raw.githubusercontent.com/a/b/master/tv.m3u" in found
    assert "http://example.com/list.m3u8?x=1" in found
    # blob 链接转为 raw
    assert "https://raw.githubusercontent.com/a/b/main/tv.m3u" in found
    assert "not-a-playlist" not in "".join(found)
