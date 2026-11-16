"""Reuse Bilibili login from a dedicated persistent browser profile."""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import time

from bilibili_transcript.wbi import session_with_headers, verify_cookie_login


logger = logging.getLogger(__name__)
HOME_URL = "https://www.bilibili.com/"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
BROWSER_PROFILE = Path(__file__).resolve().parents[1] / ".bilibili_browser_profile"
LOGIN_MARKER = ".login_checked"


def browser_login_ready():
    return (BROWSER_PROFILE / LOGIN_MARKER).is_file()


def windows_browser():
    for channel, relative_path in (
        ("chrome", "Google/Chrome/Application/chrome.exe"),
        ("msedge", "Microsoft/Edge/Application/msedge.exe"),
    ):
        for root in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            directory = os.environ.get(root)
            if directory:
                executable = Path(directory) / relative_path
                if executable.is_file():
                    return channel, executable
    raise RuntimeError("未找到 Chrome 或 Edge，请先安装其中一个浏览器")


def session_from_browser(profile_dir, referer, *, interactive=False):
    """Open the site and validate the current session without exporting credentials."""
    try:
        from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout, sync_playwright
    except ImportError as exc:
        raise RuntimeError('浏览器模式需要 Playwright，请运行 pip install -e ".[browser]"') from exc

    channel = "chrome"
    wait_for_login = interactive
    if os.name == "nt":
        channel, executable = windows_browser()
        if interactive:
            logger.info("请在打开的专用窗口登录 B 站，确认登录后关闭该窗口，脚本会重新打开浏览器验证会话。")
            try:
                subprocess.run([str(executable), f"--user-data-dir={profile_dir}", "--new-window", HOME_URL], check=True)
            except (OSError, subprocess.CalledProcessError) as exc:
                raise RuntimeError("无法打开专用登录窗口，请检查 Chrome 或 Edge") from exc
            wait_for_login = False

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch_persistent_context(
                str(profile_dir), channel=channel, headless=False,
            )
            try:
                page = browser.pages[0] if browser.pages else browser.new_page()
                response = page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30_000)
                if response is None or not response.ok:
                    raise RuntimeError("B 站网页加载失败，请检查网络后重试")
                # Give the site's login and renewal requests time to settle before
                # taking a copy of the cookies. Background requests may keep running.
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeout:
                    pass
                deadline = time.monotonic() + (180 if wait_for_login else 10)
                prompted = False
                while True:
                    cookies = browser.cookies([NAV_URL])
                    if any(cookie["name"] == "SESSDATA" for cookie in cookies):
                        session = session_with_headers("")
                        session.headers["Referer"] = referer
                        for cookie in cookies:
                            session.cookies.set(cookie["name"], cookie["value"],
                                                domain=cookie["domain"], path=cookie["path"],
                                                secure=cookie["secure"])
                        login = verify_cookie_login(session, timeout=10)
                        if login.get("ok"):
                            if interactive:
                                try:
                                    (profile_dir / LOGIN_MARKER).touch()
                                except OSError:
                                    session.close()
                                    raise
                            logger.info("已从专用浏览器取得有效的 B 站登录态。")
                            return session
                        session.close()
                        if login.get("code") != -101:
                            raise RuntimeError("B 站登录校验接口不可用，请检查网络后重试")
                    if time.monotonic() >= deadline:
                        raise RuntimeError("专用浏览器未登录 B 站，请运行 python -m bilibili_transcript browser-login")
                    if wait_for_login and not prompted:
                        logger.info("请在已打开的专用浏览器中登录 B 站。登录成功后会自动继续（最多等待 3 分钟）。")
                        prompted = True
                    time.sleep(2)
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise RuntimeError("专用浏览器无法启动或网页加载中断，请检查 Chrome/Edge、网络及是否已有更新在运行") from exc


def setup_browser_login():
    with session_from_browser(BROWSER_PROFILE, HOME_URL, interactive=True):
        pass


@contextmanager
def browser_cookie_file(referer):
    """Bridge browser cookies to the existing subtitle and yt-dlp file inputs."""
    with session_from_browser(BROWSER_PROFILE, referer) as session:
        cookies = [
            {"name": cookie.name, "value": cookie.value, "domain": cookie.domain, "path": cookie.path}
            for cookie in session.cookies
        ]
    with tempfile.TemporaryDirectory(prefix="bili-browser-") as directory:
        path = Path(directory) / "cookies.json"
        path.write_text(json.dumps(cookies), encoding="utf-8")
        yield str(path)
