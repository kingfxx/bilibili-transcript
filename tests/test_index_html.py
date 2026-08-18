"""index_html: 直播回放总目 index.html 生成（解析、排序、排除自身、导语/详情拆分）。"""

from bilibili_transcript.index_html import build_index_html, parse_transcript_html

HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{t}</title>
<style>.container {{ max-width: 780px; }}</style>
</head>
<body>
<div class="container">
"""

FOOT = """</div>
</body>
</html>
"""


def _transcript_html(title, bvid, summary_paras, section_titles):
    body = [
        HEAD.format(t=title),
        "  <header>",
        f"    <h1>{title}</h1>",
        f'    <div class="subtitle">{bvid} · 视频转写</div>',
        "  </header>",
        '  <div class="summary-card">',
        "    <h2>全文总结</h2>",
    ]
    for p in summary_paras:
        body.append(f"    <p>{p}</p>")
    body.append("  </div>")
    for i, s in enumerate(section_titles, 1):
        body.append('  <div class="section">')
        body.append("    <div class=\"section-header\">")
        body.append('      <div class="section-number">1</div>')
        body.append(f"      <h3>{s}</h3>")
        body.append("    </div>")
        body.append('    <span class="time-tag">⏱ 00:00–01:00</span>')
        body.append('    <div class="section-intro">导语</div>')
        body.append('    <div class="content-card"><p>正文</p></div>')
        body.append("  </div>")
    body.append(FOOT)
    return "\n".join(body)


def _write_transcript(tmp_path, date, name=None, **kw):
    fname = name or f"老木匠{date}直播_成稿.html"
    p = tmp_path / fname
    p.write_text(_transcript_html(**kw), encoding="utf-8")
    return p


class TestParseTranscriptHtml:
    def test_extracts_title_bvid_summary_sections(self, tmp_path):
        p = _write_transcript(
            tmp_path,
            "20260818",
            title="老木匠直播20260818",
            bvid="BV1QEbr6GECF",
            summary_paras=[
                "导语第一段",
                "<strong>重点</strong> &quot;引用&quot;",
                "### 一、标题段",
                "- 列表项",
            ],
            section_titles=["开场：A", "主题：B"],
        )

        parsed = parse_transcript_html(p)

        assert parsed["title"] == "老木匠直播20260818"
        assert parsed["bvid"] == "BV1QEbr6GECF"
        paras = parsed["summary_paras"]
        assert paras[0] == {"kind": "para", "html": "导语第一段"}
        assert paras[1]["kind"] == "para"
        assert "<strong>重点</strong>" in paras[1]["html"]
        assert '"引用"' in paras[1]["html"]
        assert paras[2] == {"kind": "heading", "html": "一、标题段"}
        assert paras[3] == {"kind": "item", "html": "列表项"}
        assert parsed["section_titles"] == ["开场：A", "主题：B"]

    def test_merged_version_takes_first_h1_and_collects_all_cards(self, tmp_path):
        # 真实合并结构：每部分各自带 summary-card + 5 个 section，逐部分交错
        p = tmp_path / "老木匠20260815直播_成稿_合并.html"
        body = [
            HEAD.format(t="老木匠20260815直播 · 第1部分"),
            "  <header>",
            "    <h1>老木匠20260815直播 · 第1部分</h1>",
            '    <div class="subtitle">BV1Sogg6gEb5 · 视频转写</div>',
            "  </header>",
            "    <h1>老木匠20260815直播 · 第2部分</h1>",
            "    <h1>老木匠20260815直播 · 第3部分</h1>",
        ]
        for part in range(1, 4):
            body.append(f'  <div class="summary-card">\n    <h2>全文总结</h2>\n    <p>第{part}部分总结一</p>\n    <p>第{part}部分总结二</p>\n  </div>')
            for i in range(1, 6):
                body.append(f'  <div class="section"><h3>P{part}-小节{i}</h3></div>')
        body.append(FOOT)
        p.write_text("\n".join(body), encoding="utf-8")

        parsed = parse_transcript_html(p)

        assert parsed["title"] == "老木匠20260815直播"
        assert len(parsed["summary_paras"]) == 6
        assert [x["html"] for x in parsed["summary_paras"]] == [
            "第1部分总结一", "第1部分总结二",
            "第2部分总结一", "第2部分总结二",
            "第3部分总结一", "第3部分总结二",
        ]
        assert len(parsed["section_titles"]) == 15

    def test_new_format_with_id_anchors_still_parses(self, tmp_path):
        """新版 HTML 的 summary-card/section 带 id 锚点（id="summary"、id="sec-1"），
        解析器需兼容带属性的开标签。"""
        p = tmp_path / "老木匠20260820直播_成稿.html"
        body = [
            HEAD.format(t="老木匠20260820直播"),
            "  <header>",
            "    <h1>老木匠20260820直播</h1>",
            '    <div class="subtitle">BV1TEST2026 · 视频转写</div>',
            "  </header>",
            '  <div class="summary-card" id="summary">',
            "    <h2>全文总结</h2>",
            "    <p>新版导语段落</p>",
            "    <p><strong>重点</strong>内容</p>",
            "  </div>",
            '  <div class="section" id="sec-1">',
            '    <div class="section-header">',
            '      <div class="section-number">1</div>',
            "      <h3>新版小节一</h3>",
            "    </div>",
            '    <span class="time-tag">⏱ 00:00–01:00</span>',
            "  </div>",
            '  <div class="section" id="sec-2">',
            "    <h3>新版小节二</h3>",
            "  </div>",
            FOOT,
        ]
        p.write_text("\n".join(body), encoding="utf-8")

        parsed = parse_transcript_html(p)

        assert parsed["title"] == "老木匠20260820直播"
        assert parsed["bvid"] == "BV1TEST2026"
        assert [x["html"] for x in parsed["summary_paras"]] == [
            "新版导语段落",
            "<strong>重点</strong>内容",
        ]
        assert parsed["section_titles"] == ["新版小节一", "新版小节二"]

    def test_new_format_merged_with_prefixed_anchors(self, tmp_path):
        """新版合并 HTML：summary-card/section 带 pN- 前缀锚点，仍需全部收集。"""
        p = tmp_path / "老木匠20260821直播_成稿_合并.html"
        body = [
            HEAD.format(t="老木匠20260821直播 · 第1部分"),
            "  <header>",
            "    <h1>老木匠20260821直播 · 第1部分</h1>",
            '    <div class="subtitle">BV1TEST2027 · 视频转写</div>',
            "  </header>",
        ]
        for part in (1, 2):
            body.append(f'  <div class="summary-card" id="p{part}-summary">\n    <h2>全文总结</h2>\n    <p>P{part}总结</p>\n  </div>')
            body.append(f'  <div class="section" id="p{part}-sec-1"><h3>P{part}小节</h3></div>')
        body.append(FOOT)
        p.write_text("\n".join(body), encoding="utf-8")

        parsed = parse_transcript_html(p)

        assert [x["html"] for x in parsed["summary_paras"]] == ["P1总结", "P2总结"]
        assert parsed["section_titles"] == ["P1小节", "P2小节"]


class TestBuildIndexHtml:
    def test_sorts_descending_and_counts_cards(self, tmp_path):
        _write_transcript(tmp_path, "20260718", title="老木匠20260718直播",
                          bvid="BV1", summary_paras=["旧场导语"], section_titles=["A"])
        _write_transcript(tmp_path, "20260815", title="老木匠20260815直播",
                          bvid="BV2", summary_paras=["合并场导语"], section_titles=["B1", "B2"])
        _write_transcript(tmp_path, "20260810", title="老木匠20260810直播",
                          bvid="BV3", summary_paras=["中场导语"], section_titles=["C"])

        out = tmp_path / "index.html"
        build_index_html(tmp_path, out)

        text = out.read_text(encoding="utf-8")
        assert text.count('<article class="index-card"') == 3
        i15 = text.index("老木匠20260815直播_成稿.html")
        i10 = text.index("老木匠20260810直播_成稿.html")
        i18 = text.index("老木匠20260718直播_成稿.html")
        assert i15 < i10 < i18

    def test_excludes_existing_index_itself(self, tmp_path):
        _write_transcript(tmp_path, "20260818", title="老木匠20260818直播",
                          bvid="BV1", summary_paras=["导语"], section_titles=["A"])
        (tmp_path / "index.html").write_text("<html><body>old</body></html>", encoding="utf-8")

        out = tmp_path / "index.html"
        build_index_html(tmp_path, out)

        text = out.read_text(encoding="utf-8")
        assert text.count('<article class="index-card"') == 1
        assert "old" not in text
        assert 'href="老木匠20260818直播_成稿.html"' in text

    def test_has_left_date_toc_with_anchors(self, tmp_path):
        """index 左侧应有日期目录：按月份分组可折叠、组内每行 4 个、指向卡片锚点、无平滑滚动。"""
        _write_transcript(tmp_path, "20260718", title="老木匠20260718直播",
                          bvid="BV1", summary_paras=["旧场导语"], section_titles=["A"])
        _write_transcript(tmp_path, "20260720", title="老木匠20260720直播",
                          bvid="BV2", summary_paras=["中场导语"], section_titles=["B"])
        _write_transcript(tmp_path, "20260815", title="老木匠20260815直播",
                          bvid="BV3", summary_paras=["合并场导语"], section_titles=["C"])

        out = tmp_path / "index.html"
        build_index_html(tmp_path, out)

        text = out.read_text(encoding="utf-8")
        # 左侧目录 nav + 月份分组
        assert '<nav class="toc">' in text
        assert text.count('<details class="toc-month"') >= 1
        assert "2026年8月" in text and "2026年7月" in text
        assert '(2)' in text and '(1)' in text  # 月份场次计数
        # 最新月份默认展开，其余收起
        assert '<details class="toc-month" open>' in text
        # 组内每行 4 个的 grid 容器
        assert 'class="toc-dates"' in text
        assert "grid-template-columns: repeat(4, 1fr)" in text
        # 日期条目 + 对应卡片锚点
        assert 'href="#card-20260718"' in text
        assert 'href="#card-20260815"' in text
        assert 'id="card-20260718"' in text
        assert 'id="card-20260815"' in text
        # 日期徽章格式
        assert "2026-07-18" in text and "2026-08-15" in text
        # 无平滑滚动（直接跳转）
        assert "scroll-behavior" not in text

    def test_shows_intro_chips_and_details(self, tmp_path):
        _write_transcript(
            tmp_path,
            "20260818",
            title="老木匠20260818直播",
            bvid="BV1QEbr6GECF",
            summary_paras=["开场导语。", "### 第一部分", "- 条目甲", "正文段落。"],
            section_titles=["开场：聊家常", "主题：美债"],
        )

        out = tmp_path / "index.html"
        build_index_html(tmp_path, out)

        text = out.read_text(encoding="utf-8")
        assert '<p class="card-intro">开场导语。</p>' in text
        assert "2026-08-18" in text  # 日期徽章
        assert '<span class="chip">开场：聊家常</span>' in text
        assert '<summary>查看完整总结</summary>' in text
        assert 'class="sum-heading"' in text and "第一部分" in text
        assert 'class="sum-item"' in text and "条目甲" in text
        assert text.count('<p class="sum-para">') == 1
