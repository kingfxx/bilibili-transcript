# bilibili-transcript

本地视频转写流水线：**优先字幕 → 否则本机 ASR → 结构化 JSON + Markdown + HTML**。

当前支持 **Bilibili**，架构已预留扩展接口（YouTube、小宇宙等可通过添加 Provider 接入）。Python 流水线**不调用外部 LLM API**——全文总结、翻译、润色由 AI 编程助手（Cursor、Claude Code 等）按 [Skill](.cursor/skills/bilibili-transcript-finalize/SKILL.md) 完成。

## 快速开始

```bash
pip install -e .                  # 或 pip install -r requirements.txt
python -m bilibili_transcript transcript "BV1xxxxxxxxx" -o case_outputs/BV1xxxxxxxxx
```

> 不带子命令的旧式调用（`python -m bilibili_transcript "BV..."`）仍兼容。
> 子命令：`transcript`（抓字幕/转录）、`export-html`（导出 HTML）、`merge-parts`（合并分P）、`index-html`（重建总目）。

> **登录态（可选但推荐）**：部分稿件的字幕仅在登录后返回。把浏览器扩展导出的 cookie 保存为
> 项目根目录下的 `bili_cookie.txt`（JSON 数组或 Netscape 格式均可），脚本会自动加载；
> 也可用 `--cookies-file path/to/cookies.txt` 指定其他位置，或用 `--cookies-from-browser chrome`
> 直接从浏览器读取（注意新版 Chrome/Edge 加密可能读取失败）。

## 流程总览

```
视频 URL / ID
  → Provider 识别来源（Bilibili / ...）
  → 拉取元数据（标题、分 P、cid、aid）并验证 cookie 登录态
  → 每个分 P：优先字幕（官方 CC / yt-dlp）→ 否则下载音轨 + faster-whisper ASR 兜底
  → 合并分段 → {BV号}_transcript.json
  → 可选：生成草稿 Markdown
  → AI 助手：润色成稿 → {博主名}{日期}直播_{主题}.md
  → 导出 HTML → {同名}.html（莫兰迪卡片）
  → 归档：HTML → 直播回放总目（merge-parts + index-html），MD → Evernote
```

## 三阶段分工


| 阶段          | 执行者                                         | 产出                                 |
| ----------- | ------------------------------------------- | ---------------------------------- |
| **① 脚本**    | `python -m bilibili_transcript`             | `{BV号}_transcript.json`（分段时间轴 + 原文）    |
| **② AI 助手** | Cursor / Claude Code / 其他                   | `{标题}.md`（总结 + 润色 + 翻译） |
| **③ 导出**    | `python -m bilibili_transcript export-html` | `{标题}.html`（莫兰迪卡片）      |


脚本只管拉稿和结构化。去口癖、标点、分段、翻译等终稿处理由 AI 助手完成。

## 代码结构

```
bilibili_transcript/
  cli.py              主入口（transcript / export-html / merge-parts / index-html 等子命令）
  providers/
    base.py            Provider 抽象接口（扩展新来源时实现此接口）
    bilibili.py        Bilibili Provider
  bvid.py              BV 号解析
  meta.py              B 站元数据 API
  download.py          音轨下载（API + yt-dlp 兜底）+ ffmpeg 转码
  wbi.py               B 站 WBI 签名 + cookie 登录态验证
  subtitles.py         官方字幕抓取 + SRT 解析
  transcribe.py        faster-whisper ASR（Windows 自动注入 nvidia cuBLAS/cuDNN DLL）
  draft_md.py          按时间分块的草稿 Markdown
  finalize_md.py       结构化成稿 Markdown（从 presets/ 加载配置）
  export_html.py       成稿 Markdown → 莫兰迪 HTML
  text_post.py         文件名清理
  utils.py             公共工具函数
  presets/             按视频 ID 的预设内容（标题、摘要、总结）
tools/
  dump_transcript.py   字幕 JSON 快速查看工具
```

## 字幕策略（每个分 P 独立判断）

1. **B 站官方 CC**（推荐）— WBI 签名请求 `x/player/wbi/v2`
2. **yt-dlp 字幕文件** — 需登录 cookie（`--cookies-file` / `--cookies-from-browser`）或 `--ytdlp-subs`
3. **本机 faster-whisper ASR** — 以上均不可用时的兜底（官方字幕确认没有、且 cookie 登录态有效时才走）

部分稿件的字幕**仅在登录态返回**。未登录时接口返回空列表属正常现象，不是 bug。
脚本会按优先级注入登录态：项目根目录 `bili_cookie.txt`（默认）→ `--cookies-file` 显式指定 → `--cookies-from-browser`。
两种 cookie 格式均支持：浏览器扩展导出的 **JSON 数组**（EditThisCookie / Cookie-Editor 格式）与 **Netscape**（yt-dlp 兼容）。

运行时会先**验证 cookie 登录态**：日志出现 `Cookie 登录态有效: xxx (mid=xxx)` 说明登录有效；cookie 过期（SESSDATA 失效）或无法确认时会提示，此时应先刷新 `bili_cookie.txt`。

## 常用参数


| 场景               | 参数                                                        |
| ---------------- | --------------------------------------------------------- |
| 默认（能抓字幕就不 ASR）   | 无额外参数（自动加载根目录 `bili_cookie.txt`）                 |
| 登录字幕在网页有、接口无     | `--cookies-file bili_cookie.txt` 或 `--cookies-from-browser chrome` |
| 强制 ASR           | `--force-asr`                                             |
| 禁用音频转写（只用字幕） | `--no-asr`（字幕不可用时直接报错，不下载音频）                  |
| GPU 转录（ASR 兜底推荐） | `--device cuda --compute-type float16`                    |
| 换更小/更大的模型        | `--whisper-model small` / `large-v3` / `medium`（默认 large-v3-turbo） |
| 处理音乐/BGM 场景       | `--no-vad`（默认开启 VAD，会滤掉静音/音乐段）                    |
| 复用已下载的音频          | `--skip-download`（ASR 路径，跳过重新下载/转码）                |
| 仅输出 JSON         | `--json-only`                                             |
| 官方无 CC 时试 yt-dlp | `--ytdlp-subs`                                            |
| 指定分 P            | `--part N`                                                |
| 覆盖成稿小节数          | `--buckets N`（默认按时长自动 3-8 节）                        |
| 导出 HTML          | `python -m bilibili_transcript export-html path/to/{标题}.md` |
| 合并分 P HTML        | `python -m bilibili_transcript merge-parts <目录>`          |
| 重建总目 index.html  | `python -m bilibili_transcript index-html <目录>`           |


## 输出物


| 文件                     | 说明                                                 |
| ---------------------- | -------------------------------------------------- |
| `{BV号}_transcript.json` | 事实源：`video_id`、`title`、`segments[]`、`part_sources` |
| `{BV号}_transcript.md` | 按时间分块的草稿（总结留空）                                     |
| `{标题}.md`            | 结构化成稿（初版由脚本生成，终稿由 AI 覆盖；命名如 `老木匠20260824直播_交易制度、量化、市场点评.md`） |
| `{标题}.html`          | 莫兰迪卡片单页 HTML                                       |


## 扩展新的视频来源

1. 在 `bilibili_transcript/providers/` 下创建新模块（如 `youtube.py`）
2. 实现 `TranscriptProvider` 接口：`match()`、`extract_id()`、`fetch_metadata()`、`fetch_segments()`、`download_audio()`
3. 在 `providers/__init__.py` 的 `PROVIDERS` 列表中注册
4. 下游流程（JSON → MD → HTML）无需改动

```python
# providers/youtube.py 示例骨架
class YouTubeProvider(TranscriptProvider):
    name = "youtube"

    def match(self, url_or_id: str) -> bool:
        return "youtube.com" in url_or_id or "youtu.be" in url_or_id
    # ... 实现其余方法
```

## 环境要求

- Python ≥ 3.10
- `ffmpeg` on PATH
- 依赖：`pip install -e .` 或 `pip install -r requirements.txt`

### GPU 转录（可选，强烈推荐）

- NVIDIA 显卡 + 驱动（CUDA 12.8+，Blackwell 如 RTX 50 系需 cuBLAS 12.8+）
- 安装 CUDA 运行库：`pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`
- **Windows 注意**：ctranslate2 用标准 LoadLibrary 找 DLL（只搜 PATH），不会自动发现 nvidia pip 包的目录——本项目 `transcribe.py` 已在启动时自动把 `nvidia/{cublas,cudnn}/bin` 注入 PATH，装好依赖后 `--device cuda` 开箱即用
- 首次运行会从 HuggingFace 下载模型（默认 large-v3-turbo，约 1.6G）；直连超时时可用代理：`HTTPS_PROXY=http://127.0.0.1:10808 HTTP_PROXY=http://127.0.0.1:10808 python -m ...`

## AI 助手集成

本项目的 Skill 文件定义了 AI 助手的执行流程：官方字幕优先，确认无字幕且 cookie 登录态有效时走 GPU ASR 兜底转录 → 润色成稿 → 导出 HTML → 归档发布。它不绑定特定工具——任何能读写文件、执行 shell 命令的 AI 编程助手都可以按此流程工作。

- Cursor 版：`.cursor/skills/bilibili-transcript-finalize/SKILL.md`
- Claude Code 版：`~/.claude/skills/bilibili-transcript-finalize/SKILL.md`（内容同步）

## 已知案例

- `case_outputs/BV1f3DYBDE9h/` — 中文评述
- `case_outputs/BV1ijE4zwEHP/` — 英文 ASR
- `case_outputs/BV1728bzzEwA/` — 多 P 视频
- `case_outputs/BV1zn8v66EzF/` — 无官方字幕，GPU ASR 兜底全流程（1h37m 约 3 分钟转完）

## 致谢

本项目基于 [znygithub/bilibili-transcript](https://github.com/znygithub/bilibili-transcript) 修改而来（新增 cookie 文件注入登录态等改动），遵循 MIT 许可，详见 [LICENSE](LICENSE)。

