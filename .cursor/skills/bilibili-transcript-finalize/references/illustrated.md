# 图文笔记分支（mode=illustrated）

从仓库根目录执行命令。当前 UP 主的输出模式、命名、截图设置和归档目录，全部以根目录 `uploader_mapping.json` 及 `route` 返回结果为准；用户当次明确要求可覆盖配置。此分支取代 SKILL.md 中纯文字直播的小节数量、时间标签、直播命名规则。

## 获取字幕与画面

在原字幕优先/登录态验证流程上，加 `--screenshots`，并把 mapping 中的 `screenshots.interval`、`subtitle_bottom_ratio`、`crop_subtitles` 分别传给 `--screenshot-interval`、`--subtitle-bottom-ratio`、`--crop-subtitles`（false 时用 `--no-crop-subtitles`）。默认每 30 秒取样，排除字幕区域去重，裁掉底部字幕。

```powershell
python -m bilibili_transcript transcript "<BV号>" -o "case_outputs/<BV号>" --no-asr --screenshots
```

不要重复执行字幕或 ASR。已有 JSON 可用 `screenshots` 子命令补图；已有视频可用 `--video-file` 复用（仅单个分 P）。保留原始转录 JSON、`*_frames/frames.json` 和视频，作为事实源与时间定位依据。

## 整理图文成稿

- 首部包含全文总结；总结与小标题可基于字幕/PPT 概括，不虚构观点或数字。
- 正文尽量保持原字幕措辞、口播顺序、例子和数字。只补标点、分段及必要的上下衔接，不改写成总结稿；检查长句和连续排比的标点。
- 不显示正文时间轴；时间保留在源 JSON 和截图清单中。
- 按课件画面/主题分节，标题使用 PPT 标题或有意义的话题，不能停留在“画面 N”；不限制 3–8 节。
- 跨截图边界按完整句意调整归属，不把“而且很不幸的是”“因为”等半句话留在上一节末尾，不丢失或重复原文。
- 同一画面不重复展示；引用已展示的画面时保留后续讲解。
- Markdown 图片保留相对路径，导出 HTML 使用内嵌图片。图片独占一行，与正文用空行分开。

可直接编辑生成的 Markdown，再运行 `export-html`。需要可重复生成时，将审阅后的标题和段落保存为 `--notes-file` JSON：

```json
{
  "summary": "全文总结",
  "sections": [
    {"part": 1, "time": 0, "heading": "课件主题", "paragraphs": ["尽量保持原文的完整段落。"]}
  ]
}
```

`sections` 必须覆盖 `frames.json` 的全部小节；截图时间和去重设置保持一致。样例为 `bilibili_transcript/presets/BV152PMeEESE_notes.json`，只适用于对应视频，不套用于其他视频。

## 命名、合集编号与归档

- `filename_style=title`：文件名为 `{document_prefix}_{视频标题}.md/html`，不加 BV 号、不套“直播”命名。如 `黄阳_为什么要学习投资.md`。
- 若配置 `collection`，使用完整顺序清单中的位置添加编号。如当前样例为第 2 个：`02_黄阳_为什么要学习投资.md/html`。不要按发布日期、下载顺序或本次处理的子集重新编号。
- 图片归档时统一命名为 `{BV号}_P{分P}_{截图毫秒数}.jpg`，避免统一 assets 目录中重名。
- 使用公共 `archive-notes` 命令复制 MD/图片、改写相对引用、导出单文件 HTML，并刷新 mapping 指定目录的总目。合集总目按编号升序，直播总目按日期降序。
- 合集更新或重排时先刷新顺序清单，再核对已归档文件编号。刷新清单不会自动重命名、删除已归档文件；不要留下同一视频两个编号版本，需整理时先列出受影响文件再处理。
