"""Extract timed frames and produce illustrated study notes from transcript JSON."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from bilibili_transcript.utils import fmt_ts


def frames_similar(left: bytes, right: bytes) -> bool:
    """Compare slide content after excluding the configured subtitle strip."""
    if not left or len(left) != len(right):
        return False
    differences = [abs(a - b) for a, b in zip(left, right)]
    return sum(differences) / len(left) <= 2 and sum(d > 20 for d in differences) / len(left) <= 0.01


def comparison_pixels(image: Path, subtitle_bottom_ratio: float = 0.2) -> bytes:
    """Exclude subtitles only from matching; keep the original displayed frame."""
    if not math.isfinite(subtitle_bottom_ratio) or not 0 <= subtitle_bottom_ratio < 0.5:
        raise ValueError("底部字幕区域比例必须在 0（含）到 0.5（不含）之间。")
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(image), "-vf",
         f"crop=iw:ih*{1 - subtitle_bottom_ratio}:0:0,scale=192:108",
         "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True,
    ).stdout


def format_transcript_paragraphs(segments: List[Dict[str, Any]]) -> List[str]:
    """Join caption fragments with punctuation and readable paragraph breaks."""
    paragraphs = []
    paragraph = ""
    previous_end = None
    for seg in segments:
        text = re.sub(r"\s+", " ", (seg.get("text") or "").strip())
        if not text:
            continue
        if paragraph and (len(paragraph) >= 220 or (
            previous_end is not None and float(seg.get("start", 0)) - previous_end >= 2
        )):
            paragraphs.append(paragraph if paragraph[-1] in "。！？.!?" else paragraph + "。")
            paragraph = ""
        if paragraph and paragraph[-1] not in "，。！？；：、,.!?;:…—\"”’）)":
            paragraph += "，"
        paragraph += text
        previous_end = float(seg.get("end", 0))
    if paragraph:
        paragraphs.append(paragraph if paragraph[-1] in "。！？.!?" else paragraph + "。")
    return paragraphs


def extract_frames(
    video: Path, output_dir: Path, part: int, end: float, interval: float,
    subtitle_bottom_ratio: float = 0.2,
    crop_subtitles: bool = True,
) -> List[Dict[str, Any]]:
    """Sample from zero through the transcript, excluding the video endpoint."""
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("截图间隔必须为大于 0 的有限数值。")
    if not math.isfinite(subtitle_bottom_ratio) or not 0 <= subtitle_bottom_ratio < 0.5:
        raise ValueError("底部字幕区域比例必须在 0（含）到 0.5（不含）之间。")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        check=True, capture_output=True, text=True,
    )
    duration = float(probe.stdout.strip())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("无法读取有效视频时长。")
    if not math.isfinite(end) or end <= 0 or end > duration + 1:
        raise ValueError("转录时间轴超出本地视频时长，请确认视频和分 P 对应。")
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    unique = []
    previous_path = None
    frame_filter = "scale='min(1600,iw)':-2"
    if crop_subtitles and subtitle_bottom_ratio:
        frame_filter = f"crop=iw:ih*{1 - subtitle_bottom_ratio}:0:0," + frame_filter
    for index in range(math.ceil(min(end, duration) / interval)):
        timestamp = index * interval
        image = output_dir / f"p{part}_{index:06d}.jpg"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(timestamp), "-i", str(video), "-frames:v", "1",
             "-vf", frame_filter, "-q:v", "2", str(image)],
            check=True, capture_output=True,
        )
        if not image.is_file() or not image.stat().st_size:
            raise RuntimeError(f"未能截取 P{part} {fmt_ts(timestamp)} 的画面。")
        thumbnail = comparison_pixels(image, 0 if crop_subtitles else subtitle_bottom_ratio)
        match = next((f for pixels, f in unique if frames_similar(pixels, thumbnail)), None)
        if match is not None:
            image.unlink()
            if previous_path == match["path"]:
                continue
            frame = {"part": part, "time": timestamp, "path": match["path"], "duplicate_of": match["time"]}
        else:
            frame = {"part": part, "time": timestamp, "path": image.name}
            unique.append((thumbnail, frame))
        frames.append(frame)
        previous_path = frame["path"]
    return frames


def build_illustrated_markdown(
    data: Dict[str, Any], frames: List[Dict[str, Any]], asset_dir: str,
    editorial_notes: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a draft, or render reviewed headings and naturally connected prose."""
    edits = {}
    if editorial_notes is not None:
        sections = editorial_notes.get("sections", [])
        expected = {(int(f["part"]), float(f["time"])) for f in frames}
        for section in sections:
            key = (int(section["part"]), float(section["time"]))
            if key in edits or not isinstance(section.get("heading"), str) or not section["heading"].strip():
                raise ValueError("编辑稿小节须有唯一的分 P / 截图时间及非空标题。")
            if not isinstance(section.get("paragraphs"), list) or not all(isinstance(p, str) and p.strip() for p in section["paragraphs"]):
                raise ValueError("编辑稿正文必须为非空段落字符串的列表。")
            edits[key] = section
        if set(edits) != expected:
            raise ValueError("编辑稿与截图时间轴不匹配，请使用制作编辑稿时的截图间隔和去重设置。")
    lines = [f"# {data.get('title') or data.get('video_id') or '图文笔记'}", "",
             "## 全文总结", "", (editorial_notes or {}).get("summary") or "以下按课件画面整理讲解正文。", "",
             "## 1. 课程讲解", ""]
    segments = data.get("segments") or []
    number = 0
    first_occurrences = {}
    for part in sorted({int(f["part"]) for f in frames}):
        part_frames = sorted((f for f in frames if int(f["part"]) == part), key=lambda f: f["time"])
        part_segs = sorted((s for s in segments if int(s.get("part", 1)) == part), key=lambda s: s["start"])
        for index, frame in enumerate(part_frames):
            number += 1
            start = frame["time"]
            end = part_frames[index + 1]["time"] if index + 1 < len(part_frames) else max(float(s["end"]) for s in part_segs)
            label = f"P{part} · 画面 {number}"
            edit = edits.get((part, float(start)))
            if edit:
                label = edit["heading"].strip()
            url = quote(f"{asset_dir}/{frame['path']}", safe="/")
            lines.extend([f"### 1.{number} {label}", ""])
            if "duplicate_of" in frame:
                lines.extend([f"画面与第 {first_occurrences[(part, frame['path'])]} 节相同，参见前面的截图。", ""])
            else:
                first_occurrences[(part, frame['path'])] = number
                lines.extend([f"![{label}]({url})", ""])
            selected = [s for s in part_segs if start <= float(s["start"]) < end]
            paragraphs = edit["paragraphs"] if edit else format_transcript_paragraphs(selected)
            for paragraph in paragraphs:
                lines.extend([paragraph, ""])
    from bilibili_transcript.meta import with_upload_time
    return with_upload_time("\n".join(lines).rstrip() + "\n", data)


def write_illustrated_notes(
    json_path: Path, *, interval: float = 30.0, video_file: Optional[Path] = None,
    cookies_file: Optional[str] = None, cookies_from_browser: Optional[str] = None,
    subtitle_bottom_ratio: float = 0.2,
    notes_file: Optional[Path] = None,
    crop_subtitles: bool = True,
) -> Path:
    """Enrich existing JSON without altering its source transcript."""
    from bilibili_transcript.download import download_part_video
    from bilibili_transcript.export_html import export_morandi_html

    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("截图间隔必须为大于 0 的有限数值。")
    if not math.isfinite(subtitle_bottom_ratio) or not 0 <= subtitle_bottom_ratio < 0.5:
        raise ValueError("底部字幕区域比例必须在 0（含）到 0.5（不含）之间。")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    segments = data.get("segments") or []
    if not segments:
        raise ValueError("转录 JSON 没有字幕片段。")
    parts = sorted({int(s.get("part", 1)) for s in segments})
    if video_file and len(parts) != 1:
        raise ValueError("--video-file 仅适用于单个分 P 的转录 JSON。")
    if video_file and not video_file.is_file():
        raise FileNotFoundError(video_file)
    if not video_file and data.get("source", "bilibili") != "bilibili":
        raise ValueError("此来源请用 --video-file 提供本地视频。")
    video_id = data.get("video_id") or data.get("bvid")
    if not video_file:
        from bilibili_transcript.bvid import extract_bvid
        video_id = extract_bvid(video_id or "")
    asset_dir = json_path.parent / f"{json_path.stem}_frames"
    frames = []
    for part in parts:
        video = video_file or download_part_video(
            video_id, part, json_path.parent,
            cookies_file=cookies_file, cookies_from_browser=cookies_from_browser,
        )
        end = max(float(s["end"]) for s in segments if int(s.get("part", 1)) == part)
        frames.extend(extract_frames(video, asset_dir, part, end, interval, subtitle_bottom_ratio, crop_subtitles))
    # Manifest keeps frame timestamps and paths available to later AI polishing.
    (asset_dir / "frames.json").write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding="utf-8")
    out = json_path.with_name(f"{json_path.stem}_图文笔记.md")
    editorial_notes = json.loads(notes_file.read_text(encoding="utf-8")) if notes_file else None
    out.write_text(build_illustrated_markdown(data, frames, asset_dir.name, editorial_notes), encoding="utf-8")
    export_morandi_html(out)
    return out
