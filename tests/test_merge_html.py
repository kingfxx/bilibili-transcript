"""merge_morandi_html: 多个成稿 HTML 合并为单文件。"""

from pathlib import Path

from bilibili_transcript.merge_html import merge_morandi_html, merge_part_groups

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


class TestMergePartGroups:
    def test_merges_groups_moves_parts_keeps_singles(self, tmp_path):
        parts15 = [
            (tmp_path / "老木匠20260815直播_P1_成稿.html", _html("P1", "P1")),
            (tmp_path / "老木匠20260815直播_P2_成稿.html", _html("P2", "P2")),
        ]
        parts10 = [
            (tmp_path / "老木匠20260810直播_P1_成稿.html", _html("P1b", "P1b")),
            (tmp_path / "老木匠20260810直播_P2_成稿.html", _html("P2b", "P2b")),
            (tmp_path / "老木匠20260810直播_P3_成稿.html", _html("P3b", "P3b")),
        ]
        for p, content in parts15 + parts10:
            p.write_text(content, encoding="utf-8")
        single = tmp_path / "老木匠20260818直播_成稿.html"
        single.write_text(_html("single", "single"), encoding="utf-8")

        merged = merge_part_groups(tmp_path)

        assert len(merged) == 2
        m15 = tmp_path / "老木匠20260815直播_成稿_合并.html"
        m10 = tmp_path / "老木匠20260810直播_成稿_合并.html"
        assert m15.exists() and m10.exists()
        t15 = m15.read_text(encoding="utf-8")
        assert t15.index("P1 总结") < t15.index("P2 总结")
        t10 = m10.read_text(encoding="utf-8")
        assert t10.index("P1b 总结") < t10.index("P2b 总结") < t10.index("P3b 总结")
        # 分P原件移入备份子目录，单场文件原地不动
        backup = tmp_path / "_分P原件备份"
        assert sorted(p.name for p in backup.glob("*.html")) == sorted([
            "老木匠20260815直播_P1_成稿.html",
            "老木匠20260815直播_P2_成稿.html",
            "老木匠20260810直播_P1_成稿.html",
            "老木匠20260810直播_P2_成稿.html",
            "老木匠20260810直播_P3_成稿.html",
        ])
        assert single.exists()
        # 分P已移走，重复执行应无新合并（幂等）
        assert merge_part_groups(tmp_path) == []

    def test_single_part_group_merged_and_moved(self, tmp_path):
        p1 = tmp_path / "老木匠20260815直播_P1_成稿.html"
        p1.write_text(_html("P1", "P1"), encoding="utf-8")

        merged = merge_part_groups(tmp_path)

        assert len(merged) == 1
        assert (tmp_path / "老木匠20260815直播_成稿_合并.html").exists()
        assert not p1.exists()
        assert (tmp_path / "_分P原件备份" / "老木匠20260815直播_P1_成稿.html").exists()

    def test_no_parts_returns_empty(self, tmp_path):
        (tmp_path / "老木匠20260818直播_成稿.html").write_text(
            _html("single", "single"), encoding="utf-8"
        )

        assert merge_part_groups(tmp_path) == []
        assert not (tmp_path / "_分P原件备份").exists()
