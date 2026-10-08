---
name: bilibili-transcript-finalize
description: >-
  Use when 用户要求「分析 / 整理 / 转写 B 站视频」并给出 BV 号或 bilibili 链接（bilibili.com、b23.tv）。
  按 uploader_mapping.json 根据 UP 主自动选择纯文字或图文笔记，获取字幕/必要时 ASR，整理成稿并按配置归档；支持合集顺序编号。
  也适用于已有 *_transcript.json 或 *_成稿.md 需要补后续阶段时。
metadata:
  origin: custom
  version: "2.8.1"
---

# B 站视频一键分析全流程

> 所有路径相对仓库根目录 `E:\07_git\01_python\02_personal\bilibili-transcript`。
> 适用于任何支持读写文件、执行 shell 的 AI 编程助手（Claude Code、Cursor 等）。

## 三阶段分工（LLM 只用于最后一步）

| 阶段 | 执行者 | 产出 | LLM？ |
|------|--------|------|-------|
| **① 字幕导出** | 纯脚本 `python -m bilibili_transcript` | `{BV号}_transcript.json` + 草稿 `.md` | **否**（禁止） |
| **② 成稿润色** | 你（读 JSON → 分析 → 润色） | `{标题}.md` | 是 |
| **③ 导出 HTML** | 纯脚本 `export-html` | `{标题}.html` | 否 |

**铁律：阶段①和③直接跑脚本，不要用 LLM 做任何读取、总结、转写工作；LLM 只负责阶段②的成稿润色。**

## 触发条件

1. 用户说「分析 / 整理 / 转写 BVxxx」或发 bilibili 链接（`bilibili.com`、`b23.tv`、含 `BV` 号）→ 完整执行 ①②③
2. 已有 `*_transcript.json` 或 `成稿.md` → 从缺失阶段开始补

## ⓪ 按 UP 主映射选择流程

每次分析视频先读取仓库根目录 `uploader_mapping.json`，不要沿用上次视频的模式或目录。通过视频元数据中的 `owner.name` / `owner.mid` 匹配，不能凭视频标题、PPT 风格或内容猜 UP 主。

```powershell
python -m bilibili_transcript route "<视频URL/BV号/已有转录JSON>"
```

- UID（mid）优先，名称和 aliases 精确匹配；用户当次明确指定的模式/目录优先于 mapping。
- `mode=text`：沿用下方纯文字流程，归档目录以 mapping 为准。买股票的老木匠已配置为此模式。
- `mode=illustrated`：先阅读 [图文笔记流程](references/illustrated.md)，按其中规则执行阶段①②③；不套用下方直播命名、3–8 节与时间标签要求。黄阳的学习分享已配置为此模式。
- 未匹配：默认纯文字，产出保留本地；需要归档时询问归档路径，不能使用别人的目录。可让用户将新 UP 主加入 mapping。
- 有 `collection` 配置：开始一次课程处理/批次前，用下列命令刷新完整合集清单，再运行 route。URL 和输出位置都从 mapping 读取：

```powershell
python -m bilibili_transcript sync-collection "<collection.url>" -o "<collection.order_file>"
```

合集编号以全部视频的显示顺序为准。单独处理某一课也取它在完整合集中的位置；不按发布时间重排。合集接口失败时明确报告，不能猜序号。未列入指定合集的视频不强行编号。清单改变不会自动重命名旧文件，需在归档前核对已存在的文件。

## ① 字幕导出与 ASR 兜底（纯脚本）

**Step 1：探测官方字幕（带 cookie，快速）**

```bash
python -m bilibili_transcript transcript "<BV号或链接>" \
  -o case_outputs/<视频ID> --no-asr
```

- 按需加 `--part N`（多 P 视频指定分 P）；不指定则自动处理所有分 P
- cookie：自动加载项目根目录 `bili_cookie.txt`
- **先看日志确认 cookie 登录态**：出现 `Cookie 登录态有效: xxx (mid=xxx)` → cookie 有效；若提示失效/无法确认（SESSDATA 过期等）→ **先提示用户刷新 bili_cookie.txt，不要走 ASR**
- 产出后检查 JSON 的 `part_sources[].mode`：
  - `official_cc` / `ytdlp_subtitle_file` / `srt` → 有字幕，直接进入 ②
  - 报错"官方字幕不可用"：可加 `--ytdlp-subs` 再试一次（yt-dlp 字幕仍属字幕路径）；仍失败 → 进入 Step 2

**Step 2：ASR 兜底转录（仅 cookie 有效时）**

```bash
python -m bilibili_transcript transcript "<BV号或链接>" \
  -o case_outputs/<视频ID> --device cuda --compute-type float16
```

- **前提：Step 1 已确认 cookie 登录态有效**；cookie 无效必须先提示刷新，不私自转写
- 默认 GPU（本机 RTX 5070 已配置好，transcribe.py 自动注入 nvidia DLL 路径）；无 GPU 机器去掉 `--device cuda --compute-type float16` 即回落 CPU
- 模型：默认 large-v3-turbo（已缓存 1.6G，repo 为 mobiuslabsgmbh/faster-whisper-large-v3-turbo）；新机器缺模型时若直连 huggingface.co 超时，带代理下载：`HTTPS_PROXY=http://127.0.0.1:10808 HTTP_PROXY=http://127.0.0.1:10808`
- 音频已下载过可加 `--skip-download` 复用
- 耗时：GPU 约 1/20 实时（1 小时音频约 3-5 分钟）；CPU 30-60 分钟，嫌慢可 `--whisper-model small`
- 产出物：`{BV号}_transcript.json`（事实源：title、segments[]、part_sources，mode 可能为 `asr`）

## ② 成稿 Markdown（LLM 分析 + 润色）

以下为 `mode=text` 的标准直播规则；图文分支使用 references/illustrated.md。

基于 `{BV号}_transcript.json` 完成。**文件名不用视频原标题**（可能是"【直播回放】…"等流水账标题），按统一风格命名：

```
{博主名}{YYYYMMDD}直播_{主题关键词}.md
```

- **博主名**：从内容推断（如"老木匠"，不用"买股票的老木匠"）
- **日期**：直播日期 `YYYYMMDD`
- **主题关键词**：2–3 个核心话题，顿号 `、` 分隔（与博主名/日期之间用 `_`）
- **文件名不含"成稿"字样**
- 示例：`老木匠20260822直播_风险、房地产、周期股.md`、`老木匠20260823直播_美债、美元、国家队.md`

### 文档结构（标准版，参照 `老木匠20260822直播_风险、房地产、周期股.md` 与 `老木匠20260830直播_美联储加息、理性思维、财务知识.md`）

1. 首行 `# {博主名}{YYYYMMDD}直播（主题词1、主题词2、…）` —— 内部标题用**全角括号**、主题间用中文顿号（与文件名的下划线式不同），如 `# 老木匠20260822直播（风险、房地产、周期股）`
2. `## 全文总结` — 散文式分段中文总结：背景、说话人、主线论点、关键数据、结论；可用 **加粗** 突出重点；不编造；如含数字，末尾单独一段 `关键数据（均出自原话，未做核实）：…` 列明
3. `## 1. 完整逐字稿` — 其下 **3–8 个小节** `### 1.1` … `### 1.N`
4. 小节标题 = **话题短标题**（如"美联储的两难与先确定输家的博弈"；不要用纯时间段做标题）
5. **每节开头为两行引用块**：
   - 首行：`> （时间参考：MM:SS–MM:SS）`（**独占一行**）
   - 次行：`> 摘要`（2–4 句，概括本小节主题与要点；也放在引用块内）
6. **正文为第一人称口播整理（"完整度稿"）**：
   - 用**第一人称**、保留主播说话的原话语感（如"谢谢大家，周日还陪我聊天""我是博弈场上的运动员"），去掉语气碎屑、理顺句子、按语义分段；
   - **不要写成第三人称转述**（避免"主播说…他解释…"的新闻稿口吻）；
   - **内容完整性优先**：论点、例子、数字、推演过程尽量保留，宁可长也不要过度压缩成要点式摘要；
   - 简体中文；英文口播译中文；专名统一；中文全角标点；不虚构观点与数字
7. 直播/闲聊内容：可按话题合并小节；偏离主题的闲聊可压缩为一个自然段、或引用块内一句带过

### 分P 与合并

- **默认**将多 P 视频按时间顺序合并成**一个**成稿：时间轴为**连续通票**（第 1 个 P 从 00:00 起，后续 P 从前一个 P 的结束时刻继续，全程 `MM:SS` 无缝衔接，**不用 P1/P2 前缀**）；小节区间相邻无缝、覆盖到结尾总时长；不另出各 P 独立版
- **仅当用户明确要求分开时**：每个 P 各自走完 ②→③，各出成稿并各自归档

### 关键规则

- 阶段①产出的脚本草稿（`finalize_md` 分桶拼接）**必须覆盖为终稿**
- 分桶规则：`N = clamp(ceil(总时长 / 25min), 3, 8)`，可在 3–8 内按话题密度合并/拆分，但每节必须带时间参考、时间轴连续覆盖全文
- 长直播（>3 小时）：允许 6–8 节，每节对应一个大话题（宏观/房地产/周期股/消费等）
- AI 字幕音误需按上下文校正，专名统一：现任美联储主席＝**沃什**（字幕常见音误"卧室/沃时/沃斯/卧时/卧石"）；鲍威尔为**前任**（仅 2026 年 5 月前历史语境）；日央行行长＝**植田和男**（音误"子田河南"）；日央行鹰派＝**高市早苗**（音误"高斯枣苗"）；"娜子"→纳指
- 关键数据段落注明"均出自原话，未做核实"

## ③ 导出 HTML

```bash
python -m bilibili_transcript export-html "path/to/xxx.md"
```

- **默认必做**，除非用户明确只要 Markdown
- 多 P 视频**默认合并**为单份 md，以合并版为输入一次性导出；用户明确要求分开时（见②「分P与合并」），各 P 单独导出

## ④ 按 mapping 归档（两种模式共用）

归档目录不写死在 Skill 中，读取 `uploader_mapping.json`。默认完成归档，除非用户明确只要本地结果或尚未配置归档路径。仅在成稿完成后执行，不能把脚本占位草稿当成成稿归档。

```powershell
python -m bilibili_transcript archive-notes "<成稿.md>" --transcript "<转录.json>" --dry-run
python -m bilibili_transcript archive-notes "<成稿.md>" --transcript "<转录.json>"
```

`--dry-run` 在源稿目录的 publish 子目录生成可检查的成稿、图片和内嵌 HTML，以及 archive_plan.json；不写归档目录。检查计划中的 UP 主、输出模式、合集编号和目标路径后，执行实际归档，无需因例行检查另问用户确认。

- 新转录 JSON 自动保存 owner；旧 JSON 缺 owner 时 route 会查询视频元数据，也可用经确认的 `--uploader "UP主名称"`。
- 纯文字直播沿用成稿文件名；title 模式按 mapping 的 document_prefix 和视频标题命名，不加 BV 号；合集成员添加原始位置编号。
- 图片复制到 assets_dir，并改写 MD 图片相对引用；图片名包含 BV 号、分 P、截图时间。HTML 内嵌图片，只复制单个 HTML 到 html_dir 即可。
- `refresh_index=true` 时调用现有 index-html 实现刷新该目录总目；合集按编号升序，直播按日期降序。不依赖 refresh.cmd，不额外归档到别的 UP 主目录。
- 多 P 默认合成一份；用户明确要求分开时分别生成，并用 `archive-notes --name "有意义的文档名_P1"` 保留分 P 后缀，避免相互覆盖。`--name` 不含扩展名和合集序号前缀。
- 归档前检查目标同名文档是否属于本视频；若属于其他视频，用 `--name` 添加有意义的标题后缀区分，不擅自覆盖，也不要给文档添加用户已要求去掉的 BV 号。权限不足时保留本地 publish 包并报告，不能宣称归档成功。

## ⑤ 清理截图用视频（图文分支）

图文成稿的 Markdown、HTML 生成并检查完成后，按 [图文笔记流程的清理规则](references/illustrated.md#生成完成后清理视频) 删除流程自动下载的截图用视频。配置了归档时，先确认归档成功再清理；不要在仅生成脚本草稿时提前删除。

## 完成后回复

告知用户：
- `.md` 与 `.html` 的路径
- 字幕来源（`part_sources` 的 mode：`official_cc` / `ytdlp_subtitle_file` / `srt` / `asr`）
- 实际选择的 UP 主与模式、合集编号（如有）、MD/HTML/图片的归档位置与总目刷新状态
- 给 2–3 句内容摘要（体现分析价值）
