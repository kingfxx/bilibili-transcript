import json
import tempfile
from pathlib import Path

from bilibili_transcript.finalize_md import (
    split_segments_into_n_buckets,
    load_preset,
    write_eval_markdown_from_json,
    resolve_num_buckets,
    MIN_BUCKETS,
    MAX_BUCKETS,
)


def _seg(i, text="hello"):
    return {"id": i, "start": i * 10.0, "end": (i + 1) * 10.0, "text": text}


def _segs_upto(end_seconds, text="hello"):
    """Build segments whose last one ends at end_seconds."""
    segs = []
    t = 0.0
    i = 0
    while t < end_seconds:
        segs.append({"id": i, "start": t, "end": min(t + 10.0, end_seconds), "text": text})
        t += 10.0
        i += 1
    return segs


class TestSplitBuckets:
    def test_empty(self):
        assert split_segments_into_n_buckets([], 5) == []

    def test_fewer_than_n(self):
        segs = [_seg(0), _seg(1), _seg(2)]
        buckets = split_segments_into_n_buckets(segs, 5)
        assert len(buckets) == 3

    def test_exact_split(self):
        segs = [_seg(i) for i in range(10)]
        buckets = split_segments_into_n_buckets(segs, 5)
        assert len(buckets) == 5
        assert all(len(b) == 2 for b in buckets)


class TestResolveNumBuckets:
    def test_empty_returns_default(self):
        assert resolve_num_buckets([]) == 5

    def test_short_video_floors_at_3(self):
        # 30 分钟：ceil(1800/1500)=2 → clamp 到 3
        assert resolve_num_buckets(_segs_upto(1800)) == 3

    def test_two_hour_video_around_5(self):
        # 约 2 小时（7300s）：ceil(7300/1500)=5
        assert resolve_num_buckets(_segs_upto(7300)) == 5

    def test_long_livestream_caps_at_8(self):
        # 6 小时：ceil(21600/1500)=15 → clamp 到 8
        assert resolve_num_buckets(_segs_upto(21600)) == 8

    def test_bounds_are_respected(self):
        assert MIN_BUCKETS == 3 and MAX_BUCKETS == 8


class TestLoadPreset:
    def test_known_preset(self):
        preset = load_preset("BV1f3DYBDE9h")
        assert preset is not None
        assert len(preset["headings"]) == 5

    def test_unknown_returns_none(self):
        assert load_preset("BV_nonexistent") is None


class TestWriteEvalMarkdown:
    def test_generic_video(self):
        segs = [_seg(i, f"text{i}") for i in range(10)]
        data = {
            "video_id": "BV_test12345",
            "bvid": "BV_test12345",
            "title": "Test Video Title",
            "text": "".join(s["text"] for s in segs),
            "segments": segs,
        }
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "BV_test12345_transcript.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            out = write_eval_markdown_from_json(json_path)
            assert out.exists()
            content = out.read_text(encoding="utf-8")
            assert "# Test Video Title" in content
            assert "## 全文总结" in content
            assert "### 1.1" in content

    def test_output_filename_is_title_only(self):
        """文件名精简：{标题}_成稿.md，不含 video_id 与 transcript。"""
        segs = [_seg(i, f"text{i}") for i in range(10)]
        data = {
            "video_id": "BV_test12345",
            "bvid": "BV_test12345",
            "title": "老木匠20260816直播",
            "text": "".join(s["text"] for s in segs),
            "segments": segs,
        }
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / "BV_test12345_transcript.json"
            json_path.write_text(json.dumps(data), encoding="utf-8")
            out = write_eval_markdown_from_json(json_path)
            assert out.name == "老木匠20260816直播_成稿.md"
            assert "BV_test12345" not in out.name
            assert "transcript" not in out.name
