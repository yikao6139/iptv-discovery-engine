# -*- coding: utf-8 -*-
"""爬虫端到端测试：本地 HTTP 服务 + 多级播放列表抓取。"""
import functools
import http.server
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.discover.playlist_fetch import PlaylistCrawler  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=FIXTURES)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, port


def test_crawler_multi_level():
    """主列表 + 相对路径嵌套列表（深度 2）。"""
    srv, port = _serve()
    try:
        base = f"http://127.0.0.1:{port}"
        crawler = PlaylistCrawler(max_nodes=10, max_runtime=60, timeout=3)
        streams, stats = crawler.crawl({f"{base}/sample.m3u"})
        assert stats["fetched"] == 2, stats          # sample.m3u + nested.m3u
        pairs = dict(streams)
        assert "CCTV-1 高清" in pairs
        assert "湖南卫视" in pairs
        assert "浙江卫视" in pairs
        assert "凤凰卫视" in pairs                    # 来自嵌套列表
        # 相对路径已解析为绝对 URL
        assert pairs["浙江卫视"].startswith(base)
    finally:
        srv.shutdown()


def test_crawler_prefetched():
    """发现模块预取内容直接解析（GitHub Contents API 通道）。"""
    srv, port = _serve()
    try:
        base = f"http://127.0.0.1:{port}"
        url = f"{base}/sample.m3u"
        import requests
        text = requests.get(url, timeout=5).text
        crawler = PlaylistCrawler(max_nodes=5, max_runtime=30, timeout=3, max_depth=0)
        streams, _ = crawler.crawl({url}, prefetched={url: text})
        assert len(streams) == 3
    finally:
        srv.shutdown()
