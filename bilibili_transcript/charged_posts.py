"""Export an uploader's accessible charging-exclusive dynamics to one Markdown file."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
import time

import requests

from bilibili_transcript.browser_login import BROWSER_PROFILE, browser_login_ready, session_from_browser
from bilibili_transcript.text_post import sanitize_filename_title
from bilibili_transcript.wbi import session_with_cookies_file, verify_cookie_login


API = "https://api.bilibili.com/x/polymer/web-dynamic/v1"
FEATURES = "itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,decorationCard"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


def api_get(session, route, **params):
    response = session.get(
        f"{API}/{route}", params={**params, "features": FEATURES}, timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 0:
        raise RuntimeError(f"{route}: {result.get('code')} {result.get('message')}")
    return result.get("data") or {}


def is_charged(item):
    author = (item.get("modules") or {}).get("module_author") or {}
    badge = author.get("icon_badge") or {}
    return bool((item.get("basic") or {}).get("is_only_fans")) or badge.get("text") == "充电专属"


def collect_posts(session, mid, interval=1.0):
    """Visit every space page; reject stalled pagination instead of silently truncating."""
    offset = ""
    offsets = set()
    posts = {}
    name = ""
    page = 0
    while True:
        data = api_get(session, "feed/space", host_mid=mid, offset=offset, timezone_offset=-480)
        page += 1
        for item in data.get("items") or []:
            author = (item.get("modules") or {}).get("module_author") or {}
            if str(author.get("mid")) != str(mid):
                continue
            name = author.get("name") or name
            if is_charged(item):
                post_id = item["id_str"]
                if post_id not in posts:
                    time.sleep(interval)
                    detail = api_get(session, "detail", id=post_id).get("item")
                    if not detail:
                        raise RuntimeError(f"动态 {post_id} 详情为空")
                    posts[post_id] = detail
        logger.info("第 %d 页，累计 %d 条充电专属动态", page, len(posts))
        if not data.get("has_more"):
            break
        offset = data.get("offset")
        if not offset or offset in offsets:
            raise RuntimeError("动态分页游标未前进，停止导出以免遗漏历史内容")
        offsets.add(offset)
        time.sleep(interval)
    if not name:
        raise RuntimeError("未取得 UP 主信息，请检查 UID 或访问权限")
    return name, list(posts.values())


def post_body(item):
    post_id = item["id_str"]
    dynamic = (item.get("modules") or {}).get("module_dynamic") or {}
    major = dynamic.get("major") or {}
    opus = major.get("opus") or {}
    summary = opus.get("summary") or {}
    if major.get("blocked") or opus.get("paywall"):
        raise RuntimeError(f"动态 {post_id} 存在权限限制，未导出预览内容")
    if summary.get("has_more"):
        raise RuntimeError(f"动态 {post_id} 正文被截断，未导出不完整内容")
    text = summary.get("text") or (dynamic.get("desc") or {}).get("text") or ""
    parts = []
    if opus.get("title"):
        parts.append(f"**{opus['title']}**")
    if text:
        # Bilibili uses single newlines for paragraphs; Markdown treats them as
        # soft wraps. Keep the author's boundaries as Markdown paragraphs.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        parts.append(re.sub(r"\n(?:[ \t]*\n)*", "\n\n", text))
    pictures = opus.get("pics") or (major.get("draw") or {}).get("items") or []
    for index, pic in enumerate(pictures, 1):
        url = pic.get("url") or pic.get("src")
        if url:
            if url.startswith("//"):
                url = "https:" + url
            parts.append(f"![图片 {index}](<{url}>)")
    archive = major.get("archive")
    if archive:
        parts.append(f"[视频：{archive['title']}](https://www.bilibili.com/video/{archive['bvid']})")
        parts.append("（本条为视频动态，仅归档动态文字与视频链接，未转录视频正文。）")
    if not parts:
        raise RuntimeError(f"动态 {post_id} 未返回正文、图片或视频，可能无访问权限")
    return "\n\n".join(parts)


def render_markdown(name, mid, posts):
    lines = [f"# {name} · 充电专属", "", f"UP 主主页：https://space.bilibili.com/{mid}/dynamic", "",
             f"共 {len(posts)} 条充电专属动态，按发布时间倒序。图片使用原站链接。", ""]
    ordered = sorted(posts, key=lambda item: int(item["modules"]["module_author"]["pub_ts"]), reverse=True)
    for item in ordered:
        author = item["modules"]["module_author"]
        published = datetime.fromtimestamp(int(author["pub_ts"]), timezone(timedelta(hours=8)))
        lines.extend([f"## {published:%Y-%m-%d %H:%M}", "",
                      f"[原动态](https://www.bilibili.com/opus/{item['id_str']})", "",
                      post_body(item), "", "---", ""])
    return "\n".join(lines)


def extract_mid(value):
    match = re.fullmatch(r"(?:https?://space\.bilibili\.com/)?(\d+)(?:[/?].*)?", value.strip())
    if not match:
        raise argparse.ArgumentTypeError("请输入 UP 主 UID 或 space.bilibili.com 主页链接")
    return match.group(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("uploader", type=extract_mid, help="UP 主 UID 或主页链接")
    parser.add_argument("-o", "--output-dir", type=Path, required=True, help="输出目录，一个 UP 主一个 MD")
    login_options = parser.add_mutually_exclusive_group()
    login_options.add_argument("--cookies-file", help="指定 Cookie 文件，直接使用文件登录态")
    login_options.add_argument("--browser-login", action="store_true", help="打开专用浏览器，等待首次登录或重新登录")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        referer = f"https://space.bilibili.com/{args.uploader}/dynamic"
        if args.browser_login or (args.cookies_file is None and browser_login_ready()):
            session = session_from_browser(BROWSER_PROFILE, referer, interactive=args.browser_login)
        else:
            session = session_with_cookies_file("", args.cookies_file or str(PROJECT_ROOT / "bili_cookie.txt"))
            session.headers["Referer"] = referer
            if not verify_cookie_login(session).get("ok"):
                session.close()
                raise RuntimeError("Cookie 登录态无效或无法验证，请运行 python -m bilibili_transcript browser-login")
        with session:
            name, posts = collect_posts(session, args.uploader)
        if not posts:
            raise RuntimeError("未找到充电专属动态，未创建或覆盖文件")
        markdown = render_markdown(name, args.uploader, posts)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output = args.output_dir / f"{sanitize_filename_title(name)}_充电.md"
        # Finish validation before touching an existing export; replace atomically.
        pending = output.with_suffix(".md.tmp")
        try:
            with pending.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(markdown)
        except FileExistsError:
            raise RuntimeError(f"临时文件已存在，请先检查：{pending}") from None
        try:
            pending.replace(output)
        finally:
            pending.unlink(missing_ok=True)
        logger.info("已导出 %d 条：%s", len(posts), output)
    except (requests.RequestException, ValueError, RuntimeError, OSError) as exc:
        logger.error("导出失败：%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
