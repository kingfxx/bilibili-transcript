"""Bilibili video metadata (title, etc.)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests

from bilibili_transcript.bvid import video_page_url
from bilibili_transcript.download import DEFAULT_UA

logger = logging.getLogger(__name__)


def with_upload_time(markdown: str, data: Dict[str, Any]) -> str:
    """Add Bilibili's public upload timestamp, never the document creation time."""
    timestamp = data.get("pubdate")
    if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool) or timestamp <= 0:
        return markdown
    date = datetime.fromtimestamp(timestamp, timezone(timedelta(hours=8)))
    line = f"视频上传时间：{date:%Y-%m-%d %H:%M:%S}（北京时间）"
    header, separator, rest = markdown.partition("## 全文总结")
    header = re.sub(r"^视频上传时间：[^\n]*\n?", "", header, flags=re.MULTILINE)
    first, _, remaining = header.partition("\n")
    return first + "\n\n" + line + "\n\n" + remaining.lstrip("\n") + separator + rest

VIEW_URL = "https://api.bilibili.com/x/web-interface/view"


def fetch_video_meta(bvid: str, timeout: float = 30.0) -> Dict[str, Any]:
    r = requests.get(
        VIEW_URL,
        params={"bvid": bvid},
        headers={
            "User-Agent": DEFAULT_UA,
            "Referer": video_page_url(bvid),
        },
        timeout=timeout,
    )
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"view API failed: {j}")
    return j.get("data") or {}


def video_title(bvid: str) -> Optional[str]:
    try:
        data = fetch_video_meta(bvid)
        return data.get("title")
    except Exception as e:
        logger.warning("Could not fetch video title: %s", e)
        return None
