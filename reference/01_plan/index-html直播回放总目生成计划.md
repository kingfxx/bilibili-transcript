# 计划：直播回放总目 index.html（生成 + 可刷新）

## Context

用户已把 19 场"老木匠"B 站直播的成稿 HTML（莫兰迪卡片，由 bilibili-transcript 导出）汇总到 `E:\06_learning\01_python\01_learning\my_code\daily_case\xueqiu\直播回放\`。目前目录里只有 22 个孤立的 HTML（18 个独立场次 + 20260815 的 P1/P2/P3/合并 4 件套），无法快速浏览"哪场讲了什么"。

目标：在该目录生成一个 **总目 index.html**——每场直播一张卡片（标题链接 + 导语小结 + 小节标题列表 + 可展开的完整全文总结），按日期**倒序**（最新在前），点击跳转到具体成稿 HTML。**后期有新的直播文档放入目录后，跑一条命令即可刷新总目。**

已确认决策：
- 脚本放 **bilibili-transcript** 项目，注册为 `index-html` CLI 子命令（样式复用莫兰迪模板、有测试）
- 排序：按日期**倒序**（最新在前）
- 卡片小结：**导语 + 可展开完整总结**（`<details>` 原生折叠，无 JS）

## 探索结论（事实依据）

- 19 个 HTML 结构统一（用户已删除 20260815 的 P1/P2/P3，只留合并版）：`<h1>` 标题、`<div class="subtitle">{BV号} · 视频转写</div>`、`<div class="summary-card">`（含 `<h2>全文总结</h2>` + 若干 `<p>`，首段为约 80-100 字导语，后续为 markdown 字面量段落 `### 一、…` 和 `- …`，**无 `<ul>/<li>`**）、每篇 5 个 `<div class="section">`（`section-number` + `<h3>` 小节标题 + `time-tag`；20260815 合并版为 3 个 summary-card + 15 个 section，解析时需容错）。
- 文件名规律：`老木匠{YYYYMMDD}直播{可选后缀}_成稿.html`，日期为 8 位数字。**每个文件就是一个条目，无需分组逻辑。**
- 特殊处理点：
  1. **h1 与文件名不一致的 4 个**（20260723/0807/0808/0818）：以文件名日期为准排序，显示用 h1 标题。
  2. 扫描时排除 `index.html` 自身。
  3. 20260815 合并版 h1 为 3 个（"… · 第1/2/3部分"），取第一个并去掉" · 第N部分"后缀作为显示标题。
- 已确认目标目录当前无 index.html、无非 HTML 文件。

## 实现方案

### 1. 新模块 `bilibili_transcript/index_html.py`

**`parse_transcript_html(path: Path) -> dict`**
- 读 HTML，用正则/切片提取：
  - `h1` 列表（合并版有 3 个，取第一个，去" · 第N部分"后缀得基础标题）
  - `BV` 号：从 subtitle 正则 `BV[0-9A-Za-z]+`
  - `summary-card` 内 `<p>` 的 innerHTML 列表（保留 `<strong>`，用 `html.unescape` 还原；把 markdown 字面量轻量转换：`### ` 前缀 → 小标题样式 span、`- ` 前缀 → 列表项样式 div——生成 index 时包样式类）
  - `section` 的 h3 标题列表
- 返回 dict：`{title, bvid, summary_paras, section_titles}`

**`build_index_html(directory: Path, out_path: Path) -> Path`**
- 扫描 `directory.glob("*.html")`，排除 `index.html`
- 每个文件一个条目；从文件名正则 `(\d{8})` 提取日期，按日期字符串倒序
- 生成 HTML：
  - 样式：`from bilibili_transcript.export_html import _style_block` 复用莫兰迪模板 CSS + 追加 index 专属样式（卡片网格、日期徽章、details 折叠、chips）
  - 结构：
    - header：`<h1>老木匠直播回放 · 总目</h1>` + 副标题（共 N 场 · 生成时间）
    - 每张卡片 `<article class="index-card">`：
      - 日期徽章（2026-08-18 格式）
      - 标题 `<a href="{文件名}">`（同目录相对链接）
      - 导语段（summary 第一段）
      - 小节标题 chips（section h3 列表，仅文本展示）
      - `<details><summary>查看完整总结</summary>` 内放剩余总结段落
    - footer
- 输出 `directory/index.html`，返回路径

### 2. `bilibili_transcript/cli.py`

- 注册 `index-html` 子命令：`python -m bilibili_transcript index-html <目录>`（与 merge-html 相同的注册模式）
- `run_index_html(args)`：调 `build_index_html`，打印输出路径

### 3. 测试 `tests/test_index_html.py`（TDD：先写测试 RED → 实现 GREEN）

- 解析测试：构造 mini HTML → `parse_transcript_html` 提取 h1/BV/总结段落/小节标题正确
- 解析容错测试：20260815 合并版样式（3 个 h1、3 个 summary-card）→ 标题取第一个 h1 并去" · 第N部分"后缀
- 排序测试：tmp_path 造 3 个不同日期文件 → index.html 中顺序为倒序
- 排除自身：目录中有 index.html 时不被收录

### 4. 执行与验证

1. 全部测试通过（现有 48 + 新增若干）
2. 对直播回放目录运行：`python -m bilibili_transcript index-html "E:\06_learning\01_python\01_learning\my_code\daily_case\xueqiu\直播回放"`
3. 验证生成的 index.html：19 张卡片（每文件一条）、倒序、链接全部有效（文件名对得上）、展开 details 显示完整总结、浏览器打开目测样式

### 5. 后续刷新方式（交付说明）

以后新视频成稿 HTML 复制进目录后，重跑第 2 步命令即刷新总目。

## 关键文件

- 新增：`E:\07_git\01_python\02_personal\bilibili-transcript\bilibili_transcript\index_html.py`
- 修改：`E:\07_git\01_python\02_personal\bilibili-transcript\bilibili_transcript\cli.py`
- 新增：`E:\07_git\01_python\02_personal\bilibili-transcript\tests\test_index_html.py`
- 复用：`bilibili_transcript\export_html.py` 的 `_style_block()`（样式提取）
