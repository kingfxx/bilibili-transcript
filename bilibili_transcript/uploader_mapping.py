"""Resolve the editable UP-owner mapping; unknown owners never inherit an archive."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_MAPPING = Path(__file__).resolve().parent.parent / "uploader_mapping.json"


def load_mapping(path: Optional[Path] = None) -> Dict[str, Any]:
    if path is None and not DEFAULT_MAPPING.is_file():
        raise FileNotFoundError("缺少本地 uploader_mapping.json；请先复制 uploader_mapping.sample.json 为 uploader_mapping.json，并修改归档路径。")
    data = json.loads((path or DEFAULT_MAPPING).read_text(encoding="utf-8-sig"))
    if data.get("version") != 1 or not isinstance(data.get("uploaders"), list):
        raise ValueError("UP 主映射需要 version: 1 和 uploaders 列表。")
    names, mids = set(), set()
    for entry in [data.get("unmatched", {}), *data["uploaders"]]:
        if entry.get("mode") not in ("text", "illustrated"):
            raise ValueError("映射 mode 必须是 text 或 illustrated。")
        archive = entry.get("archive")
        if archive is not None:
            if not isinstance(archive, dict) or not all(isinstance(archive.get(k), str) and archive[k].strip() for k in ("markdown_dir", "html_dir")):
                raise ValueError("归档配置须包含 markdown_dir 和 html_dir。")
            if archive.get("assets_dir") is not None and not isinstance(archive["assets_dir"], str):
                raise ValueError("assets_dir 必须为路径字符串或 null。")
            if not isinstance(archive.get("refresh_index", False), bool):
                raise ValueError("refresh_index 必须为 true 或 false。")
        if "screenshots" in entry:
            settings = entry["screenshots"]
            interval = settings.get("interval", 30)
            ratio = settings.get("subtitle_bottom_ratio", 0.2)
            if not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
                raise ValueError("映射截图 interval 必须为正数。")
            if not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or not 0 <= ratio < 0.5:
                raise ValueError("映射 subtitle_bottom_ratio 必须在 0 到 0.5 之间。")
            if not isinstance(settings.get("crop_subtitles", True), bool):
                raise ValueError("crop_subtitles 必须为 true 或 false。")
    for entry in data["uploaders"]:
        if not isinstance(entry.get("name"), str) or not entry["name"].strip():
            raise ValueError("每个 UP 主需要非空 name。")
        aliases = entry.get("aliases", [])
        if not isinstance(aliases, list) or not all(isinstance(n, str) and n.strip() for n in aliases):
            raise ValueError("aliases 必须为非空名称字符串的列表。")
        for name in [entry["name"], *aliases]:
            name = name.strip()
            if name in names:
                raise ValueError(f"UP 主名称/别名重复：{name}")
            names.add(name)
        mid = entry.get("mid")
        if mid is not None:
            if type(mid) is not int or mid <= 0 or mid in mids:
                raise ValueError("mid 必须为唯一的正整数或 null。")
            mids.add(mid)
        if entry.get("filename_style") not in ("title", "livestream"):
            raise ValueError("filename_style 必须为 title 或 livestream。")
        if "collection" in entry:
            collection = entry["collection"]
            if not all(isinstance(collection.get(k), str) and collection[k].strip() for k in ("url", "order_file")):
                raise ValueError("collection 需要 url 和 order_file。")
            if type(collection.get("number_width", 2)) is not int or not 1 <= collection.get("number_width", 2) <= 8:
                raise ValueError("合集 number_width 必须为 1 到 8 的整数。")
    return data


def resolve_uploader(owner: Dict[str, Any], mapping: Dict[str, Any]) -> Dict[str, Any]:
    name = str(owner.get("name") or "").strip()
    mid = owner.get("mid")
    entries = mapping["uploaders"]
    match = next((entry for entry in entries if entry.get("mid") is not None and str(entry["mid"]) == str(mid)), None)
    # A configured UID is authoritative: a different account with the same name must not match it.
    if match is None:
        match = next((entry for entry in entries if (not mid or entry.get("mid") is None) and name in [entry["name"].strip(), *(n.strip() for n in entry.get("aliases", []))]), None)
    result = copy.deepcopy(match if match else mapping["unmatched"])
    result.update({"matched": match is not None, "owner": owner})
    return result


def route_input(input_value: Optional[str], *, uploader: Optional[str] = None,
                mid: Optional[int] = None, mapping_file: Optional[Path] = None) -> Dict[str, Any]:
    mapping = load_mapping(mapping_file)
    data = {}
    video_id = None
    if input_value:
        from bilibili_transcript.bvid import extract_bvid
        path = Path(input_value)
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        video_id = data.get("video_id") or data.get("bvid") or extract_bvid(input_value)
    if uploader or mid:
        owner = {"name": uploader or "", "mid": mid}
    else:
        from bilibili_transcript.meta import fetch_video_meta
        if not input_value:
            raise ValueError("请提供视频链接/ID、转录 JSON，或 --uploader。")
        owner = data.get("owner") or fetch_video_meta(video_id).get("owner") or {}
        if not owner.get("name") and not owner.get("mid"):
            raise ValueError("无法获取视频 UP 主信息，请用 --uploader 指定，不能凭标题猜测。")
    result = resolve_uploader(owner, mapping)
    if result.get("collection") and video_id:
        from bilibili_transcript.collection_order import collection_position
        result["collection_order"] = collection_position(result["collection"], video_id, (mapping_file or DEFAULT_MAPPING).resolve().parent)
    result.update({"video_id": video_id, "mapping_file": str((mapping_file or DEFAULT_MAPPING).resolve())})
    return result
