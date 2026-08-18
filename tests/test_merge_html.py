"""merge_morandi_html: 多个成稿 HTML 合并为单文件。"""

from pathlib import Path

from bilibili_transcript.merge_html import merge_morandi_html

TEMPLATE_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{t}</title>
<style>
  .container {{ max-width: 780px; }}
</style>
</head>"""


def _html(title: str, container_id: str) -> str:
    return f"""{TEMPLATE_HEAD.format(t=title)}
<body>
<div class="container">
  <header><h1>{title}</h1></header>
  <div class="summary-card"><h2>全文总结</h2><p>{container_id} 总结</p></div>
  <div class="section"><h3>小节</h3><p>{container_id} 正文</p></div>
  <footer><p>footer</p></footer>
</div>
</body>
</html>"""


class TestMergeMorandiHtml:
    def test_merges_two_parts_into_one(self, tmp_path):
        p1 = tmp_path / "P1.html"
        p2 = tmp_path / "P2.html"
        p1.write_text(_html("标题 第 1 部分", "P1"), encoding="utf-8")
        p2.write_text(_html("标题 第 2 部分", "P2"), encoding="utf-8")
        out = tmp_path / "merged.html"

        merge_morandi_html([p1, p2], out)

        text = out.read_text(encoding="utf-8")
        # 单骨架：一份 head/body 闭合
        assert text.count("<!DOCTYPE html>") == 1
        assert text.count("<head>") == 1
        assert text.count("</body>") == 1
        assert text.count("</html>") == 1
        # 两个容器按序排列
        assert text.count('class="container"') == 2
        assert text.index("P1 总结") < text.index("P2 总结")
        # 中间有分隔标签（CSS 类名也算一次，需按 div 标签计数）
        assert "第 2 部分" in text
        assert text.count('<div class="part-divider-label">') == 1

    def test_three_parts_two_dividers(self, tmp_path):
        files = []
        for i in range(1, 4):
            p = tmp_path / f"P{i}.html"
            p.write_text(_html(f"标题 第 {i} 部分", f"P{i}"), encoding="utf-8")
            files.append(p)
        out = tmp_path / "merged.html"

        merge_morandi_html(files, out)

        text = out.read_text(encoding="utf-8")
        assert text.count('class="container"') == 3
        assert text.count('<div class="part-divider-label">') == 2
        assert text.count("<head>") == 1

    def test_single_part_no_divider(self, tmp_path):
        p = tmp_path / "P1.html"
        p.write_text(_html("标题 第 1 部分", "P1"), encoding="utf-8")
        out = tmp_path / "merged.html"

        merge_morandi_html([p], out)

        text = out.read_text(encoding="utf-8")
        assert text.count('<div class="part-divider-label">') == 0
        assert text.count('class="container"') == 1
