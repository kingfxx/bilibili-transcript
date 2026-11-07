import pytest

from bilibili_transcript import charged_posts as charged


def post(post_id="1", timestamp="1793935693", text="完整正文"):
    return {
        "id_str": post_id,
        "basic": {"is_only_fans": True},
        "modules": {
            "module_author": {"mid": 123, "name": "测试 UP", "pub_ts": timestamp},
            "module_dynamic": {"major": {"opus": {
                "summary": {"text": text, "has_more": False},
                "pics": [{"url": "https://example.com/pic.png"}],
                "paywall": None,
            }}},
        },
    }


def test_pagination_filters_public_posts_and_deduplicates(monkeypatch):
    public = post("public")
    public["basic"]["is_only_fans"] = False
    calls = []

    def fake_get(session, route, **params):
        calls.append((route, params))
        if route == "detail":
            return {"item": post(params["id"])}
        if not params["offset"]:
            return {"items": [post(), public], "has_more": True, "offset": "next"}
        return {"items": [post(), post("2")], "has_more": False}

    monkeypatch.setattr(charged, "api_get", fake_get)
    name, posts = charged.collect_posts(None, "123", interval=0)
    assert name == "测试 UP"
    assert [item["id_str"] for item in posts] == ["1", "2"]
    assert sum(route == "detail" for route, _ in calls) == 2


def test_stalled_pagination_raises(monkeypatch):
    monkeypatch.setattr(charged, "api_get", lambda *a, **k: {
        "items": [], "has_more": True, "offset": "same",
    })
    with pytest.raises(RuntimeError, match="游标"):
        charged.collect_posts(None, "123", interval=0)


@pytest.mark.parametrize("field,value", [("paywall", {"visible": True}), ("has_more", True)])
def test_incomplete_or_locked_content_rejected(field, value):
    item = post()
    opus = item["modules"]["module_dynamic"]["major"]["opus"]
    if field == "has_more":
        opus["summary"][field] = value
    else:
        opus[field] = value
    with pytest.raises(RuntimeError):
        charged.post_body(item)


def test_markdown_dates_are_body_headings_and_newest_first():
    markdown = charged.render_markdown("测试 UP", "123", [post(), post("2", "1794046493", "较新正文")])
    assert markdown.startswith("# 测试 UP · 充电专属\n")
    assert "## 2026-11-07 18:14" in markdown
    assert "## 2026-11-06 11:28" in markdown
    assert markdown.index("较新正文") < markdown.index("完整正文")
    assert "![图片 1](<https://example.com/pic.png>)" in markdown


def test_extract_mid():
    assert charged.extract_mid("https://space.bilibili.com/123/dynamic?x=1") == "123"
    assert charged.extract_mid("123") == "123"
