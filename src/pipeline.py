# -*- coding: utf-8 -*-
"""主流水线：发现 → 归一化 → 验证 → 注册表更新 → 生成 → 汇总。

运行方式（项目根目录）：
    python -m src.pipeline --seed-only            # 仅种子（冷启动/调试）
    python -m src.pipeline                        # 完整发现+验证
    python -m src.pipeline --no-verify            # 跳过验证（本地无 ffmpeg 时）
"""
from __future__ import annotations

import argparse
import time

try:
    from . import config
    from .discover.github_search import GitHubDiscovery
    from .discover.playlist_fetch import PlaylistCrawler
    from .discover.seed import fetch_seed_playlists
    from .discover.web_search import discover as web_discover
    from .normalize import canonical_key, is_generic_channel, normalize_channel_name, normalize_url
    from .playlist import write_m3u, write_txt
    from .registry import Registry
    from .verify import verify_batch
except ImportError:  # 允许作为独立脚本执行
    import config as config  # type: ignore
    from discover.github_search import GitHubDiscovery  # type: ignore
    from discover.playlist_fetch import PlaylistCrawler  # type: ignore
    from discover.seed import fetch_seed_playlists  # type: ignore
    from discover.web_search import discover as web_discover  # type: ignore
    from normalize import (canonical_key, is_generic_channel,  # type: ignore
                           normalize_channel_name, normalize_url)
    from playlist import write_m3u, write_txt  # type: ignore
    from registry import Registry  # type: ignore
    from verify import verify_batch  # type: ignore


def build_candidates(crawler: PlaylistCrawler, seed_only: bool,
                     max_repos: int = 25) -> list[tuple[str, str]]:
    """发现模块组合：种子 + GitHub 搜索 + 全网搜索 → 爬虫 → 直播流列表。"""
    pool: set[str] = set()
    prefetched: dict[str, str] = {}

    seed = fetch_seed_playlists()
    pool |= seed
    print(f"[pipeline] seed playlists: {len(seed)}")

    if not seed_only:
        gh = GitHubDiscovery(max_repos=max_repos)
        try:
            gh_pl = gh.discover()
            pool |= gh_pl
            prefetched.update(gh.prefetched)
            print(f"[pipeline] github playlists: {len(gh_pl)} "
                  f"(prefetched content: {len(gh.prefetched)})")
        except Exception as exc:  # noqa: BLE001
            print(f"[pipeline] github discovery failed (continue): {exc}")

        web_pl = web_discover()
        pool |= web_pl
        print(f"[pipeline] web playlists: {len(web_pl)}")

    streams, stats = crawler.crawl(pool, prefetched=prefetched)
    print(f"[pipeline] crawled streams={len(streams)} playlists_fetched={stats['fetched']}")
    return streams


def main() -> int:
    ap = argparse.ArgumentParser(description="IPTV 直播源整合引擎")
    ap.add_argument("--seed-only", action="store_true",
                    help="仅用种子仓库（冷启动/调试）")
    ap.add_argument("--max-playlists", type=int, default=300,
                    help="本次运行最多抓取的播放列表节点数")
    ap.add_argument("--max-runtime", type=float, default=1500.0,
                    help="爬虫全局时间预算（秒）")
    ap.add_argument("--max-repos", type=int, default=25,
                    help="GitHub 发现最多分析的仓库数")
    ap.add_argument("--max-verify", type=int, default=0,
                    help="本次最多验证的 URL 数（0=不限制）")
    ap.add_argument("--no-verify", action="store_true",
                    help="跳过流验证（仅入库标记 pending）")
    args = ap.parse_args()

    t0 = time.time()
    registry = Registry()

    crawler = PlaylistCrawler(max_nodes=args.max_playlists,
                              max_runtime=args.max_runtime)
    raw = build_candidates(crawler, seed_only=args.seed_only,
                           max_repos=args.max_repos)

    # ---- 归一化 + 批内去重（URL + 频道名双重归一化） ----
    seen: set[tuple[str, str]] = set()
    candidates: list[dict] = []
    skipped_generic = 0
    for ch, url in raw:
        nch = normalize_channel_name(ch)
        nurl = normalize_url(url)
        if not nch or is_generic_channel(nch):
            skipped_generic += 1
            continue
        if not nurl or not nurl.startswith(("http://", "https://")):
            continue
        key = (nch, canonical_key(nurl))
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"channel": nch, "url": nurl, "origin": "discovery"})
    print(f"[pipeline] after normalize/dedup: {len(candidates)} "
          f"(skipped generic names: {skipped_generic})")

    # ---- 与注册表合并：新增候选 + 到期待复验的历史源 ----
    reverify_urls: list[str] = []
    url2sid: dict[str, str] = {}
    pending_new = 0
    for c in candidates:
        sid = registry.upsert_candidate(c["channel"], c["url"], c["origin"])
        src = registry.data["sources"][sid]
        url2sid[src["url"]] = sid
        if src.get("verify_status") != "ok":
            pending_new += 1
        if registry.should_reverify(sid) and src["url"] not in reverify_urls:
            reverify_urls.append(src["url"])
    print(f"[pipeline] new/pending={pending_new} to_reverify={len(reverify_urls)}")

    # ---- 真实可播放性验证（HTTP 预检 + ffprobe/ffmpeg 拉流） ----
    verified_ok = verified_fail = 0
    if not args.no_verify and reverify_urls:
        if args.max_verify > 0:
            reverify_urls = reverify_urls[: args.max_verify]
        results = verify_batch(reverify_urls)
        for url, res in results.items():
            sid = url2sid.get(url)
            if not sid:
                continue
            if res.ok:
                registry.mark_verified(sid, latency_ms=res.latency_ms,
                                       quality=res.quality_meta())
                verified_ok += 1
            else:
                registry.mark_failed(sid)
                verified_fail += 1
        print(f"[pipeline] verified ok={verified_ok} fail={verified_fail}")

    # ---- 淘汰连续失败源 + 持久化 + 生成输出 ----
    evicted = registry.evict_failures()
    registry.data["meta"] = {
        "version": 1,
        "last_run": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "discovered": len(candidates),
        "verified_ok": verified_ok,
        "verified_fail": verified_fail,
        "evicted": len(evicted),
    }
    registry.save()

    entries = registry.valid_entries()
    n_m3u = write_m3u(entries, config.OUTPUT_DIR / f"{config.PLAYLIST_NAME}.m3u")
    n_txt = write_txt(entries, config.OUTPUT_DIR / f"{config.PLAYLIST_NAME}.txt")

    summary = registry.summary()
    print("=" * 60)
    print(f"[pipeline] done in {time.time() - t0:.1f}s")
    print(f"[pipeline] registry total={summary['total']} ok={summary['ok']} "
          f"pending={summary['pending']} evicted={len(evicted)}")
    print(f"[pipeline] m3u={n_m3u} txt={n_txt}")
    print(f"[pipeline] outputs: {config.OUTPUT_DIR / (config.PLAYLIST_NAME + '.m3u')}")
    print(f"           {config.OUTPUT_DIR / (config.PLAYLIST_NAME + '.txt')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
