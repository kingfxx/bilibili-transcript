"""--cookies-file 支持：JSON 数组 / Netscape 两种格式解析与注入。"""

import json
import os
from pathlib import Path

from bilibili_transcript.cli import default_cookies_file, resolve_cookies_file
from bilibili_transcript.wbi import (
    load_cookies_file,
    session_with_cookies_file,
    to_netscape_cookie_file,
    verify_cookie_login,
    check_cookies_file_login,
)


def _json_cookie(name: str, value: str = "v", domain: str = ".bilibili.com") -> dict:
    return {
        "domain": domain,
        "expirationDate": 1900000000,
        "hostOnly": False,
        "httpOnly": True,
        "name": name,
        "path": "/",
        "sameSite": "no_restriction",
        "secure": True,
        "session": False,
        "storeId": "0",
        "value": value,
    }


def _write_json_cookies(tmp_path: Path, cookies: list) -> Path:
    f = tmp_path / "cookies.json"
    f.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")
    return f


class TestLoadCookiesFile:
    def test_json_array_format(self, tmp_path):
        f = _write_json_cookies(
            tmp_path,
            [_json_cookie("SESSDATA", "abc123"), _json_cookie("bili_jct", "xyz")],
        )
        jar = load_cookies_file(str(f))
        assert jar.get("SESSDATA") == "abc123"
        assert jar.get("bili_jct") == "xyz"

    def test_netscape_format(self, tmp_path):
        f = tmp_path / "cookies.txt"
        f.write_text(
            "# Netscape HTTP Cookie File\n"
            ".bilibili.com\tTRUE\t/\tTRUE\t1900000000\tSESSDATA\tabc123\n"
            ".bilibili.com\tTRUE\t/\tFALSE\t1900000000\tbili_jct\txyz\n",
            encoding="utf-8",
        )
        jar = load_cookies_file(str(f))
        assert jar.get("SESSDATA") == "abc123"
        assert jar.get("bili_jct") == "xyz"

    def test_missing_file_returns_empty_jar(self, tmp_path):
        jar = load_cookies_file(str(tmp_path / "nope.txt"))
        assert dict(jar) == {}


class TestSessionWithCookiesFile:
    def test_injects_cookies_into_session(self, tmp_path):
        f = _write_json_cookies(tmp_path, [_json_cookie("SESSDATA", "abc123")])
        s = session_with_cookies_file("BV1xxx", str(f))
        assert s.cookies.get("SESSDATA") == "abc123"


class TestToNetscapeCookieFile:
    def test_json_to_netscape(self, tmp_path):
        f = _write_json_cookies(
            tmp_path,
            [
                _json_cookie("SESSDATA", "abc123", domain=".bilibili.com"),
                _json_cookie("bili_jct", "xyz", domain="www.bilibili.com"),
            ],
        )
        out = to_netscape_cookie_file(str(f))
        try:
            text = Path(out).read_text(encoding="utf-8")
            lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
            assert len(lines) == 2
            for ln, name, value in zip(lines, ["SESSDATA", "bili_jct"], ["abc123", "xyz"]):
                parts = ln.split("\t")
                assert len(parts) == 7
                assert parts[5] == name
                assert parts[6] == value
        finally:
            os.unlink(out)


class TestDefaultCookiesFile:
    def test_uses_default_file_when_present(self, tmp_path):
        (tmp_path / "bili_cookie.txt").write_text("[]", encoding="utf-8")
        assert default_cookies_file(tmp_path) == str(tmp_path / "bili_cookie.txt")

    def test_returns_none_when_default_missing(self, tmp_path):
        assert default_cookies_file(tmp_path) is None


class TestVerifyCookieLogin:
    """verify_cookie_login / check_cookies_file_login：登录态判定。"""

    def test_verify_ok_when_logged_in(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "code": 0,
                    "message": "0",
                    "data": {"isLogin": True, "uname": "老木匠", "mid": 12345},
                }

        class FakeSession:
            def get(self, url, timeout=15.0):
                return FakeResp()

        r = verify_cookie_login(FakeSession())
        assert r["ok"] is True
        assert r["is_login"] is True
        assert r["uname"] == "老木匠"
        assert r["mid"] == 12345

    def test_verify_expired_when_not_logged_in(self, monkeypatch):
        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"code": -101, "message": "账号未登录", "data": {"isLogin": False}}

        class FakeSession:
            def get(self, url, timeout=15.0):
                return FakeResp()

        r = verify_cookie_login(FakeSession())
        assert r["ok"] is False
        assert r["is_login"] is False
        assert r["code"] == -101

    def test_verify_network_error_not_treated_as_expired(self, monkeypatch):
        class FakeSession:
            def get(self, url, timeout=15.0):
                raise RuntimeError("timeout")

        r = verify_cookie_login(FakeSession())
        assert r["ok"] is False
        assert r["code"] is None

    def test_check_cookies_file_login_none_when_missing(self, tmp_path):
        assert check_cookies_file_login(None) is None
        assert check_cookies_file_login("") is None
        assert check_cookies_file_login(str(tmp_path / "nope.txt")) is None


class TestResolveCookiesFile:
    def test_explicit_cookie_file_wins(self, tmp_path):
        (tmp_path / "bili_cookie.txt").write_text("[]", encoding="utf-8")
        explicit = str(tmp_path / "other.txt")
        assert resolve_cookies_file(explicit, root=tmp_path) == explicit

    def test_falls_back_to_default_when_not_given(self, tmp_path):
        (tmp_path / "bili_cookie.txt").write_text("[]", encoding="utf-8")
        assert resolve_cookies_file(None, root=tmp_path) == str(tmp_path / "bili_cookie.txt")

    def test_none_when_nothing_given_and_default_missing(self, tmp_path):
        assert resolve_cookies_file(None, root=tmp_path) is None
