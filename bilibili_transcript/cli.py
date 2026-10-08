#!/usr/bin/env python3
"""CLI: video URL → (prefer subtitles → fallback ASR) → JSON + optional Markdown."""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bilibili_transcript.draft_md import build_draft_transcript_markdown
from bilibili_transcript.finalize_md import write_eval_markdown_from_json
from bilibili_transcript.providers import detect_provider
from bilibili_transcript.providers.base import SourceRecord, VideoMeta
from bilibili_transcript.transcribe import save_transcript_json, transcribe_mp3

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def resolve_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def resolve_compute_type(compute_type: str, device: str) -> str:
    if compute_type != "default":
        return compute_type
    return "float16" if device == "cuda" else "int8"


def merge_segment_lists(part_segments: List[List[Dict[str, Any]]], part_indices: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    new_id = 0
    for part_idx, segs in zip(part_indices or list(range(1, len(part_segments) + 1)), part_segments):
        for s in segs:
            merged.append({
                "id": new_id,
                "start": float(s.get("start", 0)),
                "end": float(s.get("end", 0)),
                "text": (s.get("text") or "").strip(),
                "words": s.get("words"),
                "part": part_idx,
                "text_source": s.get("source") or s.get("text_source"),
            })
            new_id += 1
    return merged


def obtain_part_segments(
    *,
    meta: VideoMeta,
    part_index: int,
    cid: int,
    out_dir: Path,
    args: argparse.Namespace,
    device: str,
    compute_type: str,
    provider,
) -> Tuple[List[Dict[str, Any]], str, SourceRecord]:
    """Return (segments, full_text, source_record)."""
    result = provider.fetch_segments(meta, part_index, cid, args=args)
    if result is not None:
        return result

    if getattr(args, "no_asr", False):
        raise RuntimeError(
            f"Part {part_index} 官方字幕不可用且已禁用音频转写（--no-asr）。"
            "如需字幕，请确认 bili_cookie.txt 登录态有效、网页上确有 CC 字幕，"
            "或改用 --ytdlp-subs 尝试 yt-dlp 字幕；如需音频转写请去掉 --no-asr。"
        )

    # ASR fallback
    mp3 = out_dir / f"{meta.video_id}_p{part_index}.mp3"
    if args.skip_download and mp3.exists():
        logger.info("Using existing %s", mp3)
    else:
        mp3 = provider.download_audio(meta, part_index, cid, out_dir, args=args)

    tr = transcribe_mp3(
        mp3,
        model_size=args.whisper_model,
        device=device,
        compute_type=compute_type,
        language=args.language,
        vad_filter=not args.no_vad,
    )
    segs = tr.get("segments") or []
    text = tr.get("text") or ""
    return segs, text, SourceRecord(
        part=part_index,
        mode="asr",
        extra={"whisper_model": args.whisper_model},
    )


def default_cookies_file(root: Optional[Path] = None) -> Optional[str]:
    """项目根目录下的 bili_cookie.txt 作为默认 cookie 文件；不存在时返回 None。"""
    base = root or Path(__file__).resolve().parent.parent
    p = base / "bili_cookie.txt"
    return str(p) if p.is_file() else None


def resolve_cookies_file(cookies_file: Optional[str], root: Optional[Path] = None) -> Optional[str]:
    """显式 --cookies-file 优先；未指定时回退到默认 bili_cookie.txt。"""
    if cookies_file and str(cookies_file).strip():
        return cookies_file
    return default_cookies_file(root)


def run_pipeline(args: argparse.Namespace) -> int:
    if args.screenshots and args.json_only:
        logger.error("--screenshots 与 --json-only 不能同时使用。请用 screenshots 子命令给已有 JSON 补图。")
        return 2
    if args.screenshots and (not math.isfinite(args.screenshot_interval) or args.screenshot_interval <= 0):
        logger.error("截图间隔必须为大于 0 的有限数值。")
        return 2
    if getattr(args, "force_asr", False) and getattr(args, "no_asr", False):
        logger.error("--force-asr 与 --no-asr 互斥，不能同时使用。")
        return 2
    args.cookies_file = resolve_cookies_file(args.cookies_file)
    if args.cookies_file:
        logger.info("使用 Cookie 文件: %s", args.cookies_file)
        try:
            from bilibili_transcript.wbi import check_cookies_file_login
            login = check_cookies_file_login(args.cookies_file)
            if login is not None:
                if login.get("ok"):
                    logger.info("Cookie 登录态有效: %s (mid=%s)", login.get("uname"), login.get("mid"))
                elif login.get("code") == -101:
                    logger.warning(
                        "⚠ Cookie 已失效（账号未登录，code=-101）。"
                        "如需抓取仅登录可见的字幕，请更新 %s："
                        "在浏览器扩展（EditThisCookie/Cookie-Editor 等）重新导出 B 站 Cookie "
                        "（JSON 数组或 Netscape 格式）覆盖该文件后重试。",
                        args.cookies_file,
                    )
                else:
                    logger.warning(
                        "Cookie 登录态无法确认（接口异常 code=%s），按未登录处理。",
                        login.get("code"),
                    )
        except Exception as e:
            logger.warning("验证 Cookie 登录态失败: %s", e)
    provider = detect_provider(args.input)
    logger.info("Source: %s", provider.name)

    video_id = provider.extract_id(args.input)
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        meta = provider.fetch_metadata(video_id)
    except Exception as e:
        logger.error("Failed to fetch metadata: %s", e)
        return 5

    if not meta.aid and provider.name == "bilibili":
        logger.error("无法获取 aid，字幕接口需要 aid。请稍后重试或检查网络。")
        return 5

    try:
        pages_sel, page_indices = provider.page_indices(meta, args.part)
    except ValueError as e:
        logger.error("%s", e)
        return 2

    device = resolve_device(args.device)
    compute_type = resolve_compute_type(args.compute_type, device)

    all_seg_lists: List[List[Dict[str, Any]]] = []
    combined_text_parts: List[str] = []
    sources: List[Dict[str, Any]] = []

    for pi, page in zip(page_indices, pages_sel):
        cid = int(page.get("cid", 0))
        segs, text, src = obtain_part_segments(
            meta=meta,
            part_index=pi,
            cid=cid,
            out_dir=out_dir,
            args=args,
            device=device,
            compute_type=compute_type,
            provider=provider,
        )
        all_seg_lists.append(segs)
        combined_text_parts.append(text)
        sources.append(src.to_dict())
        logger.info("Part %s: %s", pi, src.mode)

    merged_segments = merge_segment_lists(all_seg_lists, page_indices)
    if not merged_segments:
        logger.error("No segments produced (subtitles and ASR both empty). Try --no-vad or check the video.")
        return 4

    full_text = "".join((s.get("text") or "") for s in merged_segments)
    transcript_json: Dict[str, Any] = {
        "source": provider.name,
        "video_id": video_id,
        "bvid": video_id,  # backward compat for bilibili
        "title": meta.title,
        "owner": meta.extra.get("owner") or {},
        "pubdate": meta.extra.get("pubdate"),
        "ctime": meta.extra.get("ctime"),
        "text": full_text,
        "segments": merged_segments,
        "part_sources": sources,
    }
    json_path = out_dir / f"{video_id}_transcript.json"
    save_transcript_json(transcript_json, json_path)
    logger.info("Wrote %s", json_path)

    if args.json_only:
        logger.info("JSON-only mode, skipping Markdown.")
        return 0

    md = build_draft_transcript_markdown(
        meta.title, merged_segments, max_span_seconds=args.chunk_span,
    )
    md_path = out_dir / f"{video_id}_transcript.md"
    md_path.write_text(md, encoding="utf-8")
    logger.info("Wrote %s (time-chunked draft)", md_path)

    try:
        ev_path = write_eval_markdown_from_json(json_path, num_buckets=args.buckets)
        logger.info("Wrote %s (structured draft for review)", ev_path)
    except Exception as e:
        logger.warning("Skipped eval markdown: %s", e)
    if args.screenshots:
        from bilibili_transcript.screenshots import write_illustrated_notes
        out = write_illustrated_notes(
            json_path, interval=args.screenshot_interval,
            subtitle_bottom_ratio=args.subtitle_bottom_ratio,
            notes_file=Path(args.notes_file) if args.notes_file else None,
            crop_subtitles=args.crop_subtitles,
            cookies_file=args.cookies_file, cookies_from_browser=args.cookies_from_browser,
        )
        logger.info("Wrote %s and %s", out, out.with_suffix(".html"))
    return 0


def run_screenshots(args: argparse.Namespace) -> int:
    from bilibili_transcript.screenshots import write_illustrated_notes
    out = write_illustrated_notes(
        Path(args.input).resolve(), interval=args.interval,
        subtitle_bottom_ratio=args.subtitle_bottom_ratio,
        notes_file=Path(args.notes_file) if args.notes_file else None,
        crop_subtitles=args.crop_subtitles,
        video_file=Path(args.video_file).resolve() if args.video_file else None,
        cookies_file=resolve_cookies_file(args.cookies_file),
        cookies_from_browser=args.cookies_from_browser,
    )
    logger.info("Wrote %s and %s", out, out.with_suffix(".html"))
    return 0


# ---------------------------------------------------------------------------
# merge-html subcommand: merge multiple Morandi HTML files (P1/P2/P3) into one
# ---------------------------------------------------------------------------

def run_merge_html(args: argparse.Namespace) -> int:
    from bilibili_transcript.merge_html import merge_html_paths

    try:
        out = merge_html_paths(args.inputs)
    except (FileNotFoundError, ValueError) as e:
        logger.error("%s", e)
        return 1
    logger.info("Wrote %s", out)
    return 0


# ---------------------------------------------------------------------------
# merge-parts subcommand: safely merge *_P{N} part groups in a mixed directory
# ---------------------------------------------------------------------------

def run_merge_parts(args: argparse.Namespace) -> int:
    from bilibili_transcript.merge_html import merge_part_groups

    directory = Path(args.directory)
    if not directory.is_dir():
        logger.error("Not a directory: %s", directory)
        return 1
    try:
        merged = merge_part_groups(directory)
    except Exception as e:
        logger.error("%s", e)
        return 1
    if not merged:
        logger.info("没有分P文件，跳过合并")
    else:
        for m in merged:
            logger.info("Wrote %s", m)
        logger.info("分P原件已移入 _分P原件备份 子目录")
    return 0


# ---------------------------------------------------------------------------
# export-html subcommand (formerly tools/export_morandi_html.py)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# index-html subcommand: generate an index.html overview (总目) for a directory
# ---------------------------------------------------------------------------

def run_index_html(args: argparse.Namespace) -> int:
    from bilibili_transcript.index_html import build_index_html

    directory = Path(args.directory)
    if not directory.is_dir():
        logger.error("Not a directory: %s", directory)
        return 1
    try:
        out = build_index_html(directory, directory / "index.html")
    except Exception as e:
        logger.error("%s", e)
        return 1
    logger.info("Wrote %s", out)
    return 0


def run_export_html(args: argparse.Namespace) -> int:
    from bilibili_transcript.export_html import export_morandi_html

    target = Path(args.input)
    if target.is_dir():
        mds = list(target.glob("*_transcript_成稿.md"))
        if not mds:
            logger.error("No *_transcript_成稿.md found in %s", target)
            return 1
        target = mds[0]
    if not target.is_file():
        logger.error("Not found: %s", target)
        return 1

    out = export_morandi_html(target)
    logger.info("Wrote %s", out)

    if not args.no_open:
        import platform
        import subprocess
        opener = {"Darwin": "open", "Linux": "xdg-open", "Windows": "start"}.get(platform.system(), "open")
        try:
            subprocess.Popen([opener, str(out)])
        except Exception:
            pass
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Video transcript pipeline: subtitles-first, ASR-fallback, local-only.",
    )
    sub = root.add_subparsers(dest="command")

    # Default: transcript pipeline (also works without subcommand for backward compat)
    p = sub.add_parser("transcript", help="Fetch transcript from video URL")
    _add_transcript_args(p)

    route = sub.add_parser("route", help="Resolve UP-owner processing mode and archive paths")
    route.add_argument("input", nargs="?", help="Video URL/ID or existing transcript JSON")
    route.add_argument("--uploader", help="UP-owner name for offline lookup")
    route.add_argument("--mid", type=int, help="UP-owner UID")
    route.add_argument("--mapping-file", help="Editable uploader mapping JSON")

    collection = sub.add_parser("sync-collection", help="Save the complete season order for numbered notes")
    collection.add_argument("url", help="Bilibili season collection URL")
    collection.add_argument("-o", "--output", required=True, help="Order snapshot JSON path")

    archive = sub.add_parser("archive-notes", help="Stage/archive finalized MD, attachments and embedded HTML by uploader")
    archive.add_argument("input", help="Finalized Markdown")
    archive.add_argument("--transcript", required=True, help="Source transcript JSON with video ID and owner")
    archive.add_argument("--uploader", help="Explicit UP-owner name for legacy JSON without owner")
    archive.add_argument("--name", help="Document basename override without extension or collection prefix (e.g. part suffix)")
    archive.add_argument("--mapping-file", help="Editable uploader mapping JSON")
    archive.add_argument("--dry-run", action="store_true", help="Build local publish package and show plan without writing archive directories")

    sc = sub.add_parser("screenshots", help="Create deduplicated illustrated MD/HTML from transcript JSON")
    sc.add_argument("input", help="Existing transcript JSON")
    sc.add_argument("--interval", type=float, default=30.0, help="Screenshot sampling interval in seconds (default: 30)")
    sc.add_argument("--video-file", help="Local video matching a single-part transcript")
    sc.add_argument("--notes-file", help="Reviewed JSON headings and paragraphs for these frames")
    sc.add_argument("--subtitle-bottom-ratio", type=float, default=0.2, help="Bottom subtitle fraction cropped/ignored (default: 0.2; use 0 for no subtitles)")
    sc.add_argument("--crop-subtitles", action=argparse.BooleanOptionalAction, default=True, help="Crop bottom subtitles from displayed frames (default: on)")
    sc.add_argument("--cookies-file", default=None)
    sc.add_argument("--cookies-from-browser", default=None)

    # export-html subcommand
    h = sub.add_parser("export-html", help="Convert 成稿.md to Morandi HTML")
    h.add_argument("input", help="Path to *_transcript_成稿.md or a directory containing one")
    h.add_argument("--no-open", action="store_true", help="Don't auto-open in browser")

    # merge-html subcommand
    m = sub.add_parser("merge-html", help="Merge Morandi HTML files (P1/P2/P3) into one")
    m.add_argument("inputs", nargs="+", help="Path(s) to *_成稿.html, or a directory containing them")

    # merge-parts subcommand: 安全合并混装目录里的 *_P{N} 分P组
    mp = sub.add_parser("merge-parts", help="Merge *_P{N}[_成稿].html part groups in a directory")
    mp.add_argument("directory", help="Directory containing part HTML files")

    # index-html subcommand
    idx = sub.add_parser("index-html", help="Generate an index.html overview for a directory of Morandi HTMLs")
    idx.add_argument("directory", help="Directory containing *_成稿.html files")

    return root


def _add_transcript_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("input", help="Video URL or ID (e.g. BV号, YouTube URL)")
    p.add_argument("-o", "--out-dir", default=".", help="Output directory (default: current)")
    p.add_argument("--part", type=int, default=None, help="Process only part N (1-based)")
    p.add_argument("--skip-download", action="store_true", help="Reuse existing MP3 (ASR path only)")
    p.add_argument("--ytdlp", action="store_true", help="Force yt-dlp for audio download")
    p.add_argument("--ytdlp-subs", action="store_true", help="Try yt-dlp for subtitles when official API has none")
    p.add_argument(
        "--cookies-from-browser", default=None, metavar="BROWSER",
        help="Read cookies from local browser for authenticated requests (e.g. chrome)",
    )
    p.add_argument(
        "--cookies-file", default=None, metavar="PATH",
        help="Load cookies from a file (JSON array or Netscape format) for authenticated requests",
    )
    p.add_argument(
        "--prefer-subtitles", action=argparse.BooleanOptionalAction, default=True,
        help="Prefer official subtitles over ASR (default: on)",
    )
    p.add_argument("--force-asr", action="store_true", help="Skip subtitle check, force local ASR")
    p.add_argument("--no-asr", action="store_true",
                   help="Disable ASR fallback: fail when official subtitles unavailable (no audio download, no transcription)")
    p.add_argument("--whisper-model", default="large-v3-turbo", help="faster-whisper model (small/medium/large-v3/large-v3-turbo)")
    p.add_argument("--device", default="auto", help="cpu / cuda / auto")
    p.add_argument("--compute-type", default="default", help="default / int8 / float16 / float32")
    p.add_argument("--language", default="zh", help="Whisper language code (default: zh)")
    p.add_argument("--no-vad", action="store_true", help="Disable VAD filter (try for music/BGM)")
    p.add_argument("--json-only", action="store_true", help="Output JSON only, skip Markdown")
    p.add_argument("--screenshots", action="store_true", help="Also generate deduplicated illustrated MD and offline HTML")
    p.add_argument("--notes-file", help="Reviewed JSON headings and paragraphs (with --screenshots)")
    p.add_argument("--screenshot-interval", type=float, default=30.0, metavar="SEC", help="Screenshot sampling interval (default: 30)")
    p.add_argument("--subtitle-bottom-ratio", type=float, default=0.2, help="Bottom subtitle fraction cropped/ignored (default: 0.2; use 0 for no subtitles)")
    p.add_argument("--crop-subtitles", action=argparse.BooleanOptionalAction, default=True, help="Crop bottom subtitles from displayed frames (default: on)")
    p.add_argument("--buckets", type=int, default=None, metavar="N",
                   help="Override 成稿 section count (default: auto 3-8 by video length)")
    p.add_argument("--chunk-span", type=float, default=300.0, metavar="SEC", help="Draft section span in seconds (default: 300)")


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args, remaining = parser.parse_known_args(argv)

    # Backward compat: `python -m bilibili_transcript "BV..."` without subcommand
    if args.command is None:
        if remaining:
            fallback = argparse.ArgumentParser()
            _add_transcript_args(fallback)
            args = fallback.parse_args(remaining)
            args.command = "transcript"
        else:
            parser.print_help()
            return 0

    try:
        if args.command == "archive-notes":
            from bilibili_transcript.archive_notes import archive_notes
            plan = archive_notes(Path(args.input), Path(args.transcript), uploader=args.uploader,
                                 mapping_file=Path(args.mapping_file) if args.mapping_file else None,
                                 dry_run=args.dry_run, name=args.name)
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        if args.command == "sync-collection":
            from bilibili_transcript.collection_order import fetch_collection_order
            snapshot = fetch_collection_order(args.url)
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            logger.info("Wrote %s (%s videos, collection display order)", output, len(snapshot["videos"]))
            return 0
        if args.command == "route":
            from bilibili_transcript.uploader_mapping import route_input
            result = route_input(args.input, uploader=args.uploader, mid=args.mid,
                                 mapping_file=Path(args.mapping_file) if args.mapping_file else None)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "screenshots":
            return run_screenshots(args)
        if args.command == "export-html":
            return run_export_html(args)
        if args.command == "merge-html":
            return run_merge_html(args)
        if args.command == "merge-parts":
            return run_merge_parts(args)
        if args.command == "index-html":
            return run_index_html(args)
        return run_pipeline(args)
    except KeyboardInterrupt:
        logger.error("Interrupted")
        return 130
    except RuntimeError as e:
        logger.error("%s", e)
        return 3
    except Exception as e:
        logger.exception("%s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
