import json
import re
import shutil
import subprocess

import pytest

from bilibili_transcript.cli import build_parser, merge_segment_lists
from bilibili_transcript.export_html import _body_html
from bilibili_transcript.screenshots import (
    build_illustrated_markdown, comparison_pixels, extract_frames, frames_similar,
    format_transcript_paragraphs, write_illustrated_notes,
)


def test_similarity_preserves_changed_content():
    assert frames_similar(bytes([100] * 100), bytes([101] * 100))
    assert not frames_similar(bytes([100] * 100), bytes([150] * 100))
    assert not frames_similar(bytes([100] * 100), bytes([100] * 95 + [200] * 5))
    assert not frames_similar(b"", b"")


def test_boundary_text_and_part_identity():
    data = {"title": "课堂", "segments": [
        {"part": 2, "start": 0, "end": 31, "text": "跨边界句子"},
        {"part": 2, "start": 30, "end": 40, "text": "下一句"},
        {"part": 2, "start": 60, "end": 70, "text": "重复画面讲解"},
    ]}
    frames = [{"part": 2, "time": 0, "path": "a.jpg"},
              {"part": 2, "time": 30, "path": "b.jpg"},
              {"part": 2, "time": 60, "path": "a.jpg", "duplicate_of": 0}]
    md = build_illustrated_markdown(data, frames, "图片")
    assert md.count("![") == 2
    assert md.count("跨边界句子") == 1
    assert md.count("下一句") == 1
    assert md.count("重复画面讲解") == 1
    assert "画面与第 1 节相同" in md
    assert not re.search(r"\d{2}:\d{2}", md)
    assert "%E5%9B%BE%E7%89%87/a.jpg" in md
    assert merge_segment_lists([data["segments"]], [2])[0]["part"] == 2


def test_paragraphs_preserve_words_and_existing_punctuation():
    segs = [{"start": i, "end": i + 1, "text": text} for i, text in enumerate([
        "学习投资之前", "先说明风险。", "能力不足", "可能损失本金",
    ])]
    assert format_transcript_paragraphs(segs) == ["学习投资之前，先说明风险。能力不足，可能损失本金。"]
    segs.append({"start": 10, "end": 11, "text": "另一个话题"})
    assert len(format_transcript_paragraphs(segs)) == 2
    assert format_transcript_paragraphs([]) == []


def test_reviewed_notes_rejoin_sentence_across_screenshot_boundary():
    frames = [{"part": 1, "time": 0, "path": "a.jpg"},
              {"part": 1, "time": 30, "path": "b.jpg"}]
    data = {"title": "课堂", "segments": [
        {"start": 29, "end": 30, "text": "而且很不幸的是"},
        {"start": 30, "end": 31, "text": "这还是一种比较差的投资选择"},
    ]}
    notes = {"summary": "货币与投资。", "sections": [
        {"part": 1, "time": 0, "heading": "回避投资也有风险", "paragraphs": ["持有现金同样面临风险。"]},
        {"part": 1, "time": 30, "heading": "通胀与购买力", "paragraphs": ["而且很不幸的是，这还是一种比较差的投资选择。"]},
    ]}
    md = build_illustrated_markdown(data, frames, "frames", notes)
    assert "### 1.2 通胀与购买力" in md
    assert "![通胀与购买力]" in md
    assert "而且很不幸的是，这还是一种比较差的投资选择。" in md
    assert "而且很不幸的是。" not in md
    assert "画面 1" not in md
    assert md.count("![") == 2
    notes["sections"][1]["time"] = 60
    with pytest.raises(ValueError, match="时间轴不匹配"):
        build_illustrated_markdown(data, frames, "frames", notes)


def test_sample_editorial_covers_all_twenty_slides():
    from bilibili_transcript.finalize_md import PRESETS_DIR
    notes = json.loads((PRESETS_DIR / "BV152PMeEESE_notes.json").read_text(encoding="utf-8"))
    frames = [{"part": s["part"], "time": s["time"], "path": f"{i}.jpg"}
              for i, s in enumerate(notes["sections"])]
    data = {"title": "为什么要学习投资？", "segments": [{"start": 0, "end": 1335, "text": "原始字幕"}]}
    md = build_illustrated_markdown(data, frames, "frames", notes)
    assert md.count("### ") == md.count("![") == 20
    assert "而且很不幸的是，这还是一种比较差的投资选择" in md
    assert "画面 1" not in md
    assert not re.search(r"(?:的是|因为|所以|如果)[。！？]$", md, re.MULTILINE)


def test_faithful_sample_keeps_all_source_ranges_and_wording():
    from bilibili_transcript.finalize_md import PRESETS_DIR
    notes = json.loads((PRESETS_DIR / "BV152PMeEESE_notes.json").read_text(encoding="utf-8"))
    assert notes["text_style"] == "source_faithful"
    ranges = [section["source_segment_range"] for section in notes["sections"]]
    assert ranges[0][0] == 0 and ranges[-1][1] == 630
    assert all(left[1] == right[0] for left, right in zip(ranges, ranges[1:]))
    assert "在跟大家讲解股票投资学习之前" in notes["sections"][0]["paragraphs"][0]
    assert "而且很不幸的是" not in "".join(notes["sections"][0]["paragraphs"])
    assert notes["sections"][1]["paragraphs"][0].startswith("而且很不幸的是，这还是一种比较差的投资选择")


@pytest.mark.parametrize("ratio", [-0.1, 0.5, float("nan"), float("inf")])
def test_invalid_subtitle_region(tmp_path, ratio):
    with pytest.raises(ValueError, match="字幕区域"):
        write_illustrated_notes(tmp_path / "missing.json", subtitle_bottom_ratio=ratio)


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_invalid_interval_before_reading_files(tmp_path, interval):
    with pytest.raises(ValueError, match="截图间隔"):
        write_illustrated_notes(tmp_path / "missing.json", interval=interval)


def test_multiple_parts_local_video_rejected(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"segments": [{"part": 1}, {"part": 2}]}))
    with pytest.raises(ValueError, match="单个分 P"):
        write_illustrated_notes(source, video_file=tmp_path / "video.mp4")


def test_html_image_escape_and_path_boundary(tmp_path):
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"image")
    html = _body_html('![<script>](frame.jpg)', tmp_path)
    assert "data:image/jpeg;base64," in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    with pytest.raises(ValueError, match="截图必须"):
        _body_html("![frame](../outside.jpg)", tmp_path)


def test_cli_defaults():
    parser = build_parser()
    assert parser.parse_args(["screenshots", "transcript.json"]).interval == 30
    args = parser.parse_args(["transcript", "BV152PMeEESE", "--screenshots"])
    assert args.screenshots and args.screenshot_interval == 30
    assert args.crop_subtitles
    assert not parser.parse_args(["screenshots", "transcript.json", "--no-crop-subtitles"]).crop_subtitles


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires ffmpeg")
def test_real_video_deduplication_and_offline_html(tmp_path):
    video = tmp_path / "slides.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=white:s=320x240:r=2:d=2",
        "-f", "lavfi", "-i", "color=blue:s=320x240:r=2:d=1",
        "-f", "lavfi", "-i", "color=white:s=320x240:r=2:d=1",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[out]",
        "-map", "[out]", "-c:v", "libx264", str(video),
    ], check=True, capture_output=True)
    source = tmp_path / "lesson.json"
    data = {"title": "测试课堂", "segments": [
        {"part": 3, "start": i, "end": i + 1, "text": f"句子{i}"} for i in range(4)
    ]}
    source.write_text(json.dumps(data), encoding="utf-8")
    out = write_illustrated_notes(source, interval=1, video_file=video)
    frames = json.loads((tmp_path / "lesson_frames/frames.json").read_text())
    assert [f["time"] for f in frames] == [0, 2, 3]
    assert frames[-1]["duplicate_of"] == 0
    assert len(list((tmp_path / "lesson_frames").glob("*.jpg"))) == 2
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json",
        str(tmp_path / "lesson_frames" / frames[0]["path"]),
    ], check=True, capture_output=True, text=True)
    assert json.loads(probe.stdout)["streams"][0]["height"] == 192
    md = out.read_text(encoding="utf-8")
    html = out.with_suffix(".html").read_text(encoding="utf-8")
    assert md.count("![") == html.count("<img ") == 2
    for i in range(4):
        assert md.count(f"句子{i}") == html.count(f"句子{i}") == 1
    assert html.count("data:image/jpeg;base64,") == 2
    assert json.loads(source.read_text(encoding="utf-8")) == data
    with pytest.raises(ValueError, match="超出"):
        extract_frames(video, tmp_path / "bad", 3, 10, 1)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="requires ffmpeg")
def test_subtitle_changes_merge_but_slide_changes_remain(tmp_path):
    images = []
    for index, (body, caption) in enumerate([("white", "black"), ("white", "blue"), ("red", "blue")]):
        image = tmp_path / f"{index}.png"
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            f"color={body}:s=320x240,drawbox=x=0:y=192:w=320:h=48:color={caption}:t=fill",
            "-frames:v", "1", str(image),
        ], check=True, capture_output=True)
        images.append(image)
    assert frames_similar(comparison_pixels(images[0]), comparison_pixels(images[1]))
    assert not frames_similar(comparison_pixels(images[0]), comparison_pixels(images[2]))
    assert not frames_similar(comparison_pixels(images[0], 0), comparison_pixels(images[1], 0))


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires ffmpeg")
def test_video_subtitle_strip_is_removed_without_cropping_slide_twice(tmp_path):
    video = tmp_path / "caption.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=white:s=320x240:d=1,drawbox=x=0:y=192:w=320:h=48:color=yellow:t=fill",
        "-c:v", "libx264", str(video),
    ], check=True, capture_output=True)
    frames = extract_frames(video, tmp_path / "cropped", 1, 1, 1)
    image = tmp_path / "cropped" / frames[0]["path"]
    pixels = comparison_pixels(image, 0)
    assert min(pixels) >= 245  # Only the white slide remains; yellow would have blue near zero.
    full = extract_frames(video, tmp_path / "full", 1, 1, 1, crop_subtitles=False)
    assert min(comparison_pixels(tmp_path / "full" / full[0]["path"], 0)) < 50
