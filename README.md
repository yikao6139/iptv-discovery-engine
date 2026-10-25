# IPTV Discovery Engine（直播源整合引擎）

具备**自主发现能力**的 IPTV 直播源整合引擎：每天凌晨 02:00（北京时间）由
GitHub Actions 自动执行，全程无人工干预。**不预置任何固定源清单**——
代码在运行时通过网络搜索动态发现新源，验证通过即接入、失效即淘汰。

> ⚠️ 仅收录公开、可合法访问的流媒体地址。若你持有版权并希望移除特定源，
> 请提 issue 或 PR，将立即处理。

---

## 核心能力

| 需求 | 实现 |
|---|---|
| 每日 02:00（北京）自动运行 | GitHub Actions `schedule: cron "0 18 * * *"`（UTC 18:00 = 北京 02:00） |
| 无固定源清单，动态发现 | 冷启动种子（仅 3 个 awesome-iptv **元列表仓库**）+ GitHub Search API + 网页搜索，全部在运行时抓取 |
| 数量不设上限 | 只设播放列表抓取节点上限，直播流数量不设限 |
| URL + 频道名双重归一化去重 | `src/normalize.py`（NFKC、去画质后缀、query 排序键、URL 规范化） |
| 真实可播放性验证 | HTTP 预检 → `ffprobe` 读流 → `ffmpeg` 实测拉流兜底（非仅状态码） |
| 失效即淘汰 | `sources/registry.json` 记录连续失败次数，≥3 次自动删除 |
| 标准化输出 | `output/live.m3u`（M3U）+ `output/live.txt`（DIYP 格式），自动 commit |
| 播放器订阅同一 URL | 仓库每日更新后，raw 直链内容自动刷新 |

## 架构

```
                    ┌────────────────────────────────────┐
                    │  GitHub Actions（每日 02:00 北京） │
                    └────────────────────────────────────┘
                                        │
                    ┌───────────────────▼───────────────────┐
                    │         src/pipeline.py 主流水线        │
                    └───────────────────┬───────────────────┘
        ┌───────────────┬───────────────┼───────────────┬───────────────┐
        ▼               ▼               ▼               ▼               ▼
  discover/seed   discover/      discover/       discover/       src/verify.py
  （3 个元列表    github_search  web_search      playlist_fetch  HTTP预检→ffprobe
   仓库 README）  （Search API→  （DuckDuckGo，  （并发有界爬虫， →ffmpeg拉流兜底
                   Trees API→    尽力而为）      支持预取内容/嵌套列表）
                   Contents API）
        └───────────────┴───────────────┴───────────────┴───────────────┘
                                        │
                    ┌───────────────────▼───────────────────┐
                    │  归一化去重 → sources/registry.json     │
                    │  （动态注册表：发现/验证/连续失败/淘汰）  │
                    └───────────────────┬───────────────────┘
                                        ▼
                    ┌─────────────────────────────────────────┐
                    │ 生成 output/live.m3u + output/live.txt   │
                    │ → git add/commit/push（工作流自动完成）   │
                    └─────────────────────────────────────────┘
```

## 设计原则（代码级承诺）

1. **禁止白名单**：代码中唯一硬编码项是 `src/config.py` 的 `SEED_REPOS`
   （3 个 awesome-iptv 类**元列表仓库**，仅首次运行引路，它们发布的是
   「指向播放列表的链接」而非「具体直播流地址」）。任何具体源地址都来自
   运行时发现模块的网络响应。
2. **代码即猎手**：执行搜索的是 Python 代码（GitHub Search API、Trees API、
   Contents API、HTML 解析），不存在人工预置的源清单。
3. **质量硬门槛**：每个源必须通过「仓库级准入（内容含 #EXTM3U/#EXTINF）+
   流级验证（真实拉流）」双重考核。
4. **动态注册表**：`sources/registry.json` 记录每个源的发现时间、验证状态、
   连续失败次数、清晰度与延迟；每日增删全部由程序完成，禁止人工维护。

## 快速开始

### 本地运行

```bash
# 依赖（仅 requests）
pip install -r requirements.txt

# 完整运行（发现 + 验证，本机需安装 ffmpeg）
python -m src.pipeline

# 仅种子仓库发现（冷启动/调试，不联网搜索）
python -m src.pipeline --seed-only

# 本地无 ffmpeg 时跳过验证（仅入库标记 pending）
python -m src.pipeline --no-verify
```

常用参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--max-playlists` | 300 | 本次最多抓取的播放列表节点数 |
| `--max-repos` | 25 | GitHub 发现最多分析的仓库数 |
| `--max-runtime` | 1500s | 爬虫全局时间预算 |
| `--max-verify` | 0 | 本次最多验证的 URL 数（0=不限） |
| `--no-verify` | - | 跳过流验证 |

> 本地调试提示：
> - 证书链异常（`CERTIFICATE_VERIFY_FAILED`）时设 `IPTV_ENGINE_SSL_VERIFY=0` 临时关闭校验
>   （仅调试用，CI 默认开启校验）；
> - ffmpeg 不在 PATH 时，用 `IPTV_ENGINE_FFMPEG_DIR=<目录>` 指定目录
>   （目录内按 `ffmpeg*.exe` / `ffprobe*.exe` 通配识别，兼容带版本后缀的构建）。

### 单元测试

```bash
pip install pytest
python -m pytest tests -v
```

## 部署到 GitHub（每日自动更新）

1. 把本仓库推送到 GitHub（公开仓库，raw 直链无需鉴权）。
2. 首次推送后，**手动触发一次**工作流（Actions → Daily IPTV Update →
   Run workflow），确认全链路可用：
   - `GITHUB_TOKEN` 由 Actions 自动注入（已写入 `daily.yml` 的 env），
     用于 GitHub API 搜索（配额 5000 req/h）；
   - `ubuntu-latest` 自带 ffmpeg，真实拉流验证开箱即用。
3. 之后每天 02:00（北京时间）自动运行：发现 → 验证 → 淘汰 → 生成 → 提交。

> 注意：公开仓库的 scheduled workflow 在仓库 60 天无提交后会被 GitHub 暂停；
> 本仓库每日自动提交，天然避免该问题。

## 播放器订阅直链

仓库每日更新后，播放器拉取**同一 URL** 即自动获得最新内容（无需换链接）：

```
# M3U（VLC / TiviMate / 大多数播放器）
https://raw.githubusercontent.com/<owner>/<repo>/main/output/live.m3u

# TXT（DIYP / 百川 / 电视家等安卓壳）
https://raw.githubusercontent.com/<owner>/<repo>/main/output/live.txt
```

- **VLC**：媒体 → 打开网络串流 → 粘贴 M3U 链接
- **TiviMate**：设置 → 播放列表 → 添加 → URL 粘贴 M3U 链接
- **APTV**：订阅 → 添加订阅 → 粘贴 M3U 链接
- **DIYP 影音**：设置 → 节目源 → 填入 TXT 链接

## 目录结构

```
├── .github/workflows/
│   ├── daily.yml          # 每日 02:00(北京) 自动发现+提交
│   └── ci.yml             # push 时自动跑单元测试
├── src/
│   ├── config.py          # 全部可调参数（零硬编码源地址）
│   ├── pipeline.py        # 主流水线
│   ├── normalize.py       # URL/频道名双重归一化去重
│   ├── registry.py        # sources/registry.json 动态注册表
│   ├── verify.py          # 真实可播放性验证（ffprobe/ffmpeg）
│   ├── playlist.py        # M3U / DIYP-TXT 生成
│   └── discover/
│       ├── seed.py            # 冷启动种子（3 个元列表仓库）
│       ├── github_search.py   # GitHub Search/Trees/Contents API
│       ├── web_search.py      # DuckDuckGo 网页搜索（尽力而为）
│       └── playlist_fetch.py  # 并发有界爬虫（嵌套列表/HTML/预取）
├── sources/registry.json  # 动态注册表（程序自动维护）
├── output/live.m3u        # 输出（每日自动更新）
├── output/live.txt
└── tests/                 # 单元测试 + 本地 HTTP 端到端爬虫测试
```

## FAQ

**Q：为什么首次运行 GitHub 搜索配额不够？**
匿名访问 GitHub Search API 限 10 次/min、REST 60 次/h。Actions 中
`GITHUB_TOKEN` 自动注入后为 30 次/min、5000 次/h，远够每日运行。
本地调试可用 `--max-repos` 缩小范围。

**Q：验证为什么用 ffmpeg？**
仅查 HTTP 状态码无法判断「能不能真的播」。本引擎用 `ffprobe` 读取流信息
（必须存在 video/audio 轨），读不到再 `ffmpeg` 实际拉流数秒兜底，
并记录清晰度与延迟用于排序。

**Q：源失效了怎么办？**
每日运行会复验所有源（默认 24h 复验周期）。连续失败 ≥3 次的源由程序
自动从注册表删除，并从输出中消失。

**Q：为什么不内置一个现成源清单？**
这是本项目的核心立场：源地址易变、且不应由代码维护者垄断。
「发现模块」每天在网络上找新源，找到→验证→入库；找不到的旧源自然淘汰。
需要改关键词/种子仓库，只改 `src/config.py`，不动逻辑。

## License

MIT
