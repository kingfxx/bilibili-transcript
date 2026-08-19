"""Bilibili WBI 签名（与站方算法一致，参考 yt-dlp bilibili extractor）。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from bilibili_transcript.download import DEFAULT_UA

logger = logging.getLogger(__name__)

_WBI_KEY: Optional[str] = None
_WBI_TS: float = 0.0
_WBI_TTL = 300.0

_MIXIN_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


def _fetch_mixin_key(session: requests.Session) -> str:
    r = session.get(
        "https://api.bilibili.com/x/web-interface/nav",
        timeout=30.0,
    )
    r.raise_for_status()
    j = r.json()
    data = j.get("data") or {}
    wbi = data.get("wbi_img") or {}
    img = (wbi.get("img_url") or "").rsplit("/", 1)[-1].partition(".")[0]
    sub = (wbi.get("sub_url") or "").rsplit("/", 1)[-1].partition(".")[0]
    lookup = f"{img}{sub}"
    if len(lookup) < 64:
        raise RuntimeError("Unexpected wbi_img format from /nav")
    return "".join(lookup[i] for i in _MIXIN_TAB)[:32]


def get_wbi_key(session: requests.Session) -> str:
    global _WBI_KEY, _WBI_TS
    now = time.time()
    if _WBI_KEY and now - _WBI_TS < _WBI_TTL:
        return _WBI_KEY
    _WBI_KEY = _fetch_mixin_key(session)
    _WBI_TS = now
    return _WBI_KEY


def sign_wbi(params: Dict[str, Any], session: requests.Session) -> Dict[str, Any]:
    p = dict(params)
    p["wts"] = int(time.time())
    p = {
        k: "".join(c for c in str(v) if c not in "!'()*")
        for k, v in sorted(p.items())
    }
    query = urllib.parse.urlencode(p)
    w_rid = hashlib.md5((query + get_wbi_key(session)).encode()).hexdigest()
    p["w_rid"] = w_rid
    return p


def session_with_headers(bvid: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": DEFAULT_UA,
            "Referer": f"https://www.bilibili.com/video/{bvid}",
        }
    )
    return s


def session_with_browser_cookies(bvid: str, browser: Optional[str]) -> requests.Session:
    """
    在 session_with_headers 基础上注入本机浏览器里 bilibili.com 的 Cookie，
    使 x/player/wbi/v2 在「需登录才返回字幕」的稿件上与网页行为一致。
    """
    s = session_with_headers(bvid)
    if not browser or not str(browser).strip():
        return s
    try:
        import browser_cookie3
    except ImportError:
        logger.warning(
            "已指定 --cookies-from-browser，但未安装 browser-cookie3，"
            "无法向官方字幕接口注入登录态。请执行: pip install browser-cookie3"
        )
        return s
    name = str(browser).strip().lower()
    loaders: Dict[str, Any] = {
        "chrome": browser_cookie3.chrome,
        "chromium": browser_cookie3.chromium,
        "brave": browser_cookie3.brave,
        "edge": browser_cookie3.edge,
        "firefox": browser_cookie3.firefox,
        "safari": browser_cookie3.safari,
        "opera": browser_cookie3.opera,
    }
    if hasattr(browser_cookie3, "vivaldi"):
        loaders["vivaldi"] = browser_cookie3.vivaldi  # type: ignore[attr-defined]
    loader = loaders.get(name)
    if loader is None:
        logger.warning(
            "不支持的浏览器名: %s（可选: %s）",
            name,
            ", ".join(sorted(loaders)),
        )
        return s
    try:
        cj = loader(domain_name="bilibili.com")
        s.cookies.update(cj)
        logger.info("已从本机 %s 注入 bilibili.com Cookie（用于官方字幕接口）。", name)
    except Exception as e:
        logger.warning("读取浏览器 Cookie 失败（官方字幕可能仍为空）: %s", e)
    return s


def load_cookies_file(path: str) -> "requests.cookies.RequestsCookieJar":
    """
    读取 cookie 文件（JSON 数组或 Netscape 格式），返回 cookie jar。
    文件不存在或解析失败时返回空 jar（不抛错，让调用方按匿名请求处理）。
    """
    jar = requests.cookies.RequestsCookieJar()
    p = Path(path)
    if not p.is_file():
        logger.warning("Cookie 文件不存在: %s", p)
        return jar
    try:
        raw = p.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("读取 Cookie 文件失败: %s", e)
        return jar
    stripped = raw.lstrip()
    try:
        if stripped.startswith("["):
            for c in json.loads(raw):
                jar.set(
                    c.get("name", ""),
                    c.get("value", ""),
                    domain=c.get("domain", ""),
                    path=c.get("path", "/"),
                )
        else:
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain, _flag, path, _secure, _expires, name, value = parts[:7]
                jar.set(name, value, domain=domain, path=path)
        logger.info("已从 %s 加载 %d 个 Cookie。", p.name, len(jar))
    except Exception as e:
        logger.warning("解析 Cookie 文件失败: %s", e)
        jar.clear()
    return jar


def session_with_cookies_file(bvid: str, cookies_file: Optional[str]) -> requests.Session:
    """在 session_with_headers 基础上注入 cookie 文件里的登录态。"""
    s = session_with_headers(bvid)
    if not cookies_file or not str(cookies_file).strip():
        return s
    jar = load_cookies_file(str(cookies_file))
    if jar:
        s.cookies.update(jar)
    return s


def verify_cookie_login(session: requests.Session, timeout: float = 15.0) -> Dict[str, Any]:
    """验证注入 cookie 的 session 是否处于登录态。

    返回 {ok, is_login, uname, mid, code, message}：
    - ok=True 表示请求成功且 isLogin=True
    - ok=False 但 code != -101 表示网络/接口异常（无法判定，按匿名处理）
    - ok=False 且 code == -101 表示 cookie 失效（SESSDATA 过期等）
    """
    try:
        r = session.get(
            "https://api.bilibili.com/x/web-interface/nav",
            timeout=timeout,
        )
        r.raise_for_status()
        j = r.json()
    except Exception as e:
        logger.warning("验证 Cookie 登录态失败（网络/接口异常）: %s", e)
        return {"ok": False, "is_login": False, "code": None, "message": str(e)}
    data = j.get("data") or {}
    is_login = bool(data.get("isLogin"))
    result = {
        "ok": is_login,
        "is_login": is_login,
        "uname": data.get("uname"),
        "mid": data.get("mid"),
        "code": j.get("code"),
        "message": j.get("message"),
    }
    return result


def check_cookies_file_login(cookies_file: Optional[str], bvid: str = "") -> Optional[Dict[str, Any]]:
    """便捷入口：加载 cookie 文件并用独立 session 验证登录态。

    返回 verify_cookie_login 的字典；cookie 文件缺失/为空时返回 None（跳过验证）。
    """
    if not cookies_file or not str(cookies_file).strip():
        return None
    jar = load_cookies_file(str(cookies_file))
    if not jar:
        return None
    s = session_with_headers(bvid)
    s.cookies.update(jar)
    return verify_cookie_login(s)


def to_netscape_cookie_file(cookies_file: str) -> Optional[str]:
    """
    把 JSON 数组 / Netscape 格式的 cookie 文件统一转成 Netscape 临时文件，
    供 yt-dlp 的 --cookies 使用。返回临时文件路径（调用方负责清理），失败返回 None。
    """
    jar = load_cookies_file(cookies_file)
    if not jar:
        return None
    lines: List[str] = ["# Netscape HTTP Cookie File"]
    for c in jar:
        domain = c.domain or ""
        path = c.path or "/"
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        secure = "TRUE" if c.secure else "FALSE"
        expires = str(int(c.expires)) if c.expires else "0"
        lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{c.name}\t{c.value}")
    try:
        fd, tmp_path = tempfile.mkstemp(prefix="bili_cookies_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return tmp_path
    except Exception as e:
        logger.warning("写出 Netscape cookie 临时文件失败: %s", e)
        return None
