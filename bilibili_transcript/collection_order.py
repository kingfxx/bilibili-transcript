"""Snapshot a Bilibili season in its displayed order, including every page."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import requests

from bilibili_transcript.download import DEFAULT_UA


def fetch_collection_order(url: str) -> Dict[str, Any]:
    match = re.search(r"space\.bilibili\.com/(\d+)/lists/(\d+)", url)
    if not match or "type=series" in url:
        raise ValueError("请提供 B 站合集 URL：space.bilibili.com/UID/lists/合集ID?type=season")
    mid, season_id = map(int, match.groups())
    entries, seen = [], set()
    page = 1
    title = ""
    while True:
        response = requests.get(
            "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list",
            params={"mid": mid, "season_id": season_id, "sort_reverse": "false", "page_num": page, "page_size": 30},
            headers={"User-Agent": DEFAULT_UA, "Referer": f"https://space.bilibili.com/{mid}/"}, timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"合集顺序获取失败：{payload.get('code')} {payload.get('message')}")
        data = payload.get("data") or {}
        title = (data.get("meta") or {}).get("name") or title
        archives = data.get("archives") or []
        if not archives:
            raise RuntimeError("合集分页为空，未覆盖全部视频；不生成不完整编号。")
        for item in archives:
            bvid = item.get("bvid")
            if not bvid or bvid in seen:
                raise RuntimeError("合集分页缺少 BV 号或出现重复，请重新获取。")
            seen.add(bvid)
            entries.append({"position": len(entries) + 1, "bvid": bvid, "title": item.get("title", "")})
        total = int((data.get("page") or {}).get("total") or len(data.get("aids") or []) or len(entries))
        if len(entries) >= total:
            if len(entries) != total:
                raise RuntimeError("合集视频数量与分页总数不一致。")
            break
        page += 1
    return {"url": url, "mid": mid, "season_id": season_id, "title": title,
            "updated_at": datetime.now(timezone.utc).isoformat(), "videos": entries}


def collection_position(collection: Dict[str, Any], video_id: str, root: Path) -> Dict[str, Any]:
    path = Path(collection["order_file"])
    if not path.is_absolute():
        path = root / path
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if snapshot.get("url") != collection["url"]:
        raise ValueError("合集顺序文件与 mapping 中的合集 URL 不一致。")
    videos = snapshot.get("videos") or []
    ids = [v["bvid"] for v in videos]
    if len(ids) != len(set(ids)) or any(v["position"] != i for i, v in enumerate(videos, 1)):
        raise ValueError("合集顺序文件的序号必须从 1 连续递增且 BV 号不可重复。")
    item = next((v for v in videos if v["bvid"] == video_id), None)
    if item is None:
        return {"member": False, "url": collection["url"], "order_file": str(path)}
    return {"member": True, "url": collection["url"], "position": item["position"],
            "prefix": f"{item['position']:0{collection.get('number_width', 2)}d}_",
            "title": snapshot.get("title"), "order_file": str(path)}
