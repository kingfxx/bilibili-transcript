from contextlib import contextmanager
from pathlib import Path

import pytest
import requests

from bilibili_transcript import browser_login, cli
from bilibili_transcript.wbi import load_cookies_file


@pytest.mark.parametrize("options", [[], ["--cookies-file", "explicit.json"]])
def test_transcript_selects_shared_profile_unless_cookies_are_explicit(monkeypatch, options):
    monkeypatch.setattr(cli, "browser_login_ready", lambda: True)
    handles = []

    @contextmanager
    def snapshot(referer):
        handles.append(referer)
        yield "browser-cookies.json"
        handles.append("closed")

    def pipeline(args, provider, *, browser_verified=False):
        assert provider.name == "bilibili"
        assert args.cookies_file == ("explicit.json" if options else "browser-cookies.json")
        assert browser_verified is (not options)
        return 0

    monkeypatch.setattr(cli, "browser_cookie_file", snapshot)
    monkeypatch.setattr(cli, "_run_pipeline", pipeline)
    assert cli.main(["transcript", "BV1f3DYBDE9h", *options]) == 0
    assert handles == ([] if options else ["https://www.bilibili.com/", "closed"])


def test_cookie_snapshot_works_with_existing_loader_and_is_removed_on_failure(monkeypatch):
    session = requests.Session()
    session.cookies.set("SESSDATA", "dummy", domain=".bilibili.com", path="/")
    monkeypatch.setattr(browser_login, "session_from_browser", lambda *args: session)

    with pytest.raises(RuntimeError, match="downstream failure"):
        with browser_login.browser_cookie_file(browser_login.HOME_URL) as snapshot:
            assert load_cookies_file(snapshot).get("SESSDATA", domain=".bilibili.com") == "dummy"
            raise RuntimeError("downstream failure")

    assert not Path(snapshot).exists()
