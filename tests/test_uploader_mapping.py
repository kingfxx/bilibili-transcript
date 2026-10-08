import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from bilibili_transcript.archive_notes import archive_notes
from bilibili_transcript.collection_order import fetch_collection_order
from bilibili_transcript.uploader_mapping import load_mapping, resolve_uploader, route_input


def test_configured_modes_uid_and_unknown_owner():
    mapping = load_mapping()
    assert resolve_uploader({"name": "买股票的老木匠"}, mapping)["mode"] == "text"
    assert resolve_uploader({"name": "老木匠"}, mapping)["name"] == "买股票的老木匠"
    result = resolve_uploader({"name": "改名后的黄阳", "mid": 291299472}, mapping)
    assert result["matched"] and result["mode"] == "illustrated"
    assert not resolve_uploader({"name": "黄阳的学习分享", "mid": 999}, mapping)["matched"]
    result = resolve_uploader({"name": "新UP主"}, mapping)
    assert result["mode"] == "text" and result["archive"] is None


def test_editable_mapping_changes_routing_without_code_changes(tmp_path):
    mapping = load_mapping()
    mapping["uploaders"][0]["mode"] = "illustrated"
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    assert route_input(None, uploader="买股票的老木匠", mapping_file=path)["mode"] == "illustrated"
    mapping["uploaders"][1]["aliases"] = ["买股票的老木匠"]
    path.write_text(json.dumps(mapping), encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        load_mapping(path)


def test_real_snapshot_uses_full_collection_position_not_subset(tmp_path):
    transcript = tmp_path / "source.json"
    transcript.write_text(json.dumps({"bvid": "BV152PMeEESE", "owner": {"name": "黄阳的学习分享", "mid": 291299472}}))
    result = route_input(str(transcript))
    assert result["collection_order"]["position"] == 2
    assert result["collection_order"]["prefix"] == "02_"
    assert result["archive"]["assets_dir"].endswith("黄阳的学习分享/assets")


def test_collection_pagination_preserves_display_order(monkeypatch):
    payloads = [
        {"code": 0, "data": {"archives": [{"bvid": "BVnew", "title": "new", "pubdate": 200}, {"bvid": "BVold", "title": "old", "pubdate": 100}], "page": {"total": 3}}},
        {"code": 0, "data": {"archives": [{"bvid": "BVmiddle", "title": "middle", "pubdate": 150}], "page": {"total": 3}}},
    ]
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs["params"])
        response = Mock()
        response.json.return_value = payloads[len(calls) - 1]
        return response
    monkeypatch.setattr("bilibili_transcript.collection_order.requests.get", get)
    result = fetch_collection_order("https://space.bilibili.com/1/lists/2?type=season")
    assert [v["bvid"] for v in result["videos"]] == ["BVnew", "BVold", "BVmiddle"]
    assert [v["position"] for v in result["videos"]] == [1, 2, 3]
    assert [c["page_num"] for c in calls] == [1, 2]
    assert all(c["sort_reverse"] == "false" for c in calls)


def test_archive_rewrites_flat_assets_and_keeps_html_portable(tmp_path):
    image_dir = tmp_path / "frames"
    image_dir.mkdir()
    (image_dir / "p1_000025.jpg").write_bytes(b"test-image")
    (image_dir / "frames.json").write_text(json.dumps([{"part": 1, "time": 750, "path": "p1_000025.jpg"}]))
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"bvid": "BV152PMeEESE", "title": "为什么要学习投资？", "owner": {"name": "黄阳的学习分享", "mid": 291299472}}))
    md = tmp_path / "final.md"
    md.write_text("# 为什么要学习投资？\n\n## 全文总结\n\n总结\n\n## 1. 课程讲解\n\n### 1.1 财富是什么\n\n![课件](frames/p1_000025.jpg)\n\n原字幕正文。\n", encoding="utf-8")
    mapping = load_mapping()
    entry = mapping["uploaders"][1]
    original_order = Path(__file__).resolve().parents[1] / entry["collection"]["order_file"]
    entry["collection"]["order_file"] = str(original_order)
    entry["archive"] = {"markdown_dir": str(tmp_path / "archive/md"), "assets_dir": str(tmp_path / "archive/md/assets"), "html_dir": str(tmp_path / "archive/html"), "refresh_index": True}
    config = tmp_path / "mapping.json"
    config.write_text(json.dumps(mapping), encoding="utf-8")
    plan = archive_notes(md, source, mapping_file=config, dry_run=True)
    assert not (tmp_path / "archive").exists()
    assert Path(plan["markdown"]).name == "02_黄阳_为什么要学习投资.md"
    assert Path(plan["staged_markdown"]).is_file()
    plan = archive_notes(md, source, mapping_file=config)
    archived_md = Path(plan["markdown"]).read_text(encoding="utf-8")
    assert "assets/BV152PMeEESE_P1_000750000.jpg" in archived_md
    assert (tmp_path / "archive/md/assets/BV152PMeEESE_P1_000750000.jpg").read_bytes() == b"test-image"
    assert "data:image/jpeg;base64," in Path(plan["html"]).read_text(encoding="utf-8")
    assert (tmp_path / "archive/html/index.html").exists()
    assert "frames/p1_000025.jpg" in md.read_text(encoding="utf-8")
