"""Stage/ archive finalized notes using the UP mapping and collection position."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote, unquote

from bilibili_transcript.export_html import export_morandi_html
from bilibili_transcript.text_post import sanitize_filename_title
from bilibili_transcript.uploader_mapping import route_input


def archive_notes(md_path: Path, transcript_path: Path, *, uploader: Optional[str] = None,
                  mapping_file: Optional[Path] = None, dry_run: bool = False,
                  name: Optional[str] = None) -> Dict[str, Any]:
    md_path = md_path.resolve()
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    route = route_input(str(transcript_path), uploader=uploader, mapping_file=mapping_file)
    archive = route.get("archive")
    if not archive:
        raise ValueError("该 UP 主未配置归档路径，请先更新 uploader_mapping.json。")
    video_id = data.get("video_id") or data.get("bvid")
    from bilibili_transcript.bvid import extract_bvid
    video_id = extract_bvid(video_id or "")
    stem = md_path.stem
    if route.get("filename_style") == "title":
        title = (data.get("title") or md_path.stem).rstrip("？?！!。.")
        stem = sanitize_filename_title(f"{route.get('document_prefix') or route['name']}_{title}", max_len=120)
    if name:
        stem = sanitize_filename_title(name, max_len=120)
    order = route.get("collection_order") or {}
    if order.get("member"):
        stem = order["prefix"] + stem
    md_dir = Path(archive["markdown_dir"]).resolve()
    html_dir = Path(archive["html_dir"]).resolve()
    assets_dir = Path(archive["assets_dir"]).resolve() if archive.get("assets_dir") else None
    stage = md_path.parent / "publish" / stem
    from bilibili_transcript.meta import with_upload_time
    text = with_upload_time(md_path.read_text(encoding="utf-8"), data)
    copies = {}
    archived_refs = {}

    def rewrite(match):
        if assets_dir is None:
            raise ValueError("图文稿需要配置 assets_dir。")
        src = (md_path.parent / unquote(match[2])).resolve()
        try:
            src.relative_to(md_path.parent)
        except ValueError as exc:
            raise ValueError("待归档图片必须位于源 Markdown 的目录或子目录中。") from exc
        if not src.is_file():
            raise FileNotFoundError(src)
        manifest_path = src.parent / "frames.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        frame = next((f for f in manifest if f["path"] == src.name), None)
        if frame is None:
            raise ValueError(f"截图缺少对应时间记录：{src}")
        ms = round(float(frame["time"]) * 1000)
        name = f"{video_id}_P{int(frame['part'])}_{ms:09d}{src.suffix.lower()}"
        if name in copies and copies[name] != src:
            raise ValueError(f"不同图片使用了相同截图时间：{name}")
        copies[name] = src
        staged_ref = quote(f"assets/{name}", safe="/")
        archived_refs[staged_ref] = quote(os.path.relpath(assets_dir / name, md_dir).replace(os.sep, "/"), safe="/")
        return f"![{match[1]}]({staged_ref})"

    # All checks are performed before writing staged or external outputs.
    text = re.sub(r"^!\[([^\]]*)\]\(([^\n]+)\)$", rewrite, text, flags=re.MULTILINE)
    stage.mkdir(parents=True, exist_ok=True)
    for name, src in copies.items():
        (stage / "assets").mkdir(exist_ok=True)
        shutil.copy2(src, stage / "assets" / name)
    staged_md = stage / f"{stem}.md"
    staged_md.write_text(text, encoding="utf-8")
    staged_html = export_morandi_html(staged_md)
    archived_text = text
    for old, new in archived_refs.items():
        archived_text = archived_text.replace(f"]({old})", f"]({new})")
    plan = {"dry_run": dry_run, "uploader": route.get("name"), "mode": route["mode"],
            "collection_order": order, "staged_markdown": str(staged_md), "staged_html": str(staged_html),
            "markdown": str(md_dir / staged_md.name), "html": str(html_dir / staged_html.name),
            "assets_dir": str(assets_dir) if assets_dir else None, "image_count": len(copies)}
    (stage / "archive_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    if dry_run:
        return plan
    md_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)
    if copies:
        assets_dir.mkdir(parents=True, exist_ok=True)
    for name in copies:
        shutil.copy2(stage / "assets" / name, assets_dir / name)
    (md_dir / staged_md.name).write_text(archived_text, encoding="utf-8")
    shutil.copy2(staged_html, html_dir / staged_html.name)
    if archive.get("refresh_index"):
        from bilibili_transcript.index_html import build_index_html
        build_index_html(html_dir, html_dir / "index.html",
                         sort_order="sequence" if route.get("collection") else "date",
                         uploader_name=route["name"])
    return plan
