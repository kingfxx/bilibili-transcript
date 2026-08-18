"""Generate an index.html overview (总目) for a directory of Morandi transcript HTMLs.

Each file becomes one card: date badge + title link + intro paragraph
(summary 首段) + section-title chips + a ``<details>`` block with the rest of
the full summary. Cards are ordered by the 8-digit date in the filename,
newest first. Re-running :func:`build_index_html` refreshes the index.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from bilibili_transcript.export_html import _style_block

_DATE_RE = re.compile(r"(\d{8})")
_BV_RE = re.compile(r"BV[0-9A-Za-z]+")
_H1_RE = re.compile(r"<h1>(.*?)</h1>", re.DOTALL)
_SUBTITLE_RE = re.compile(r'class="subtitle">(.*?)</div>', re.DOTALL)
_H3_RE = re.compile(r"<h3>(.*?)</h3>", re.DOTALL)
_P_RE = re.compile(r"<p>(.*?)</p>", re.DOTALL)
_STRONG_RE = re.compile(r"<strong>.*?</strong>", re.DOTALL)
# 每个 summary-card 的内容：到下一个 section / 下一个 summary-card / 文末为止
_CARD_RE = re.compile(
    r'<div class="summary-card">(.*?)(?=<div class="section">|<div class="summary-card">|$)',
    re.DOTALL,
)

INDEX_CSS = """
  .index-container { max-width: 860px; }
  .index-grid { display: grid; gap: 22px; }
  .index-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 22px 26px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.03);
    text-align: left;
  }
  .card-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
  .date-badge {
    display: inline-block;
    font-size: 0.72rem;
    background: var(--tag-bg);
    color: var(--text-light);
    padding: 3px 12px;
    border-radius: 20px;
    font-family: "SF Mono", "Fira Code", monospace;
    white-space: nowrap;
  }
  .card-title {
    font-size: 1.2rem;
    font-weight: 600;
    color: var(--heading);
    text-decoration: none;
    letter-spacing: 0.3px;
  }
  .card-title:hover { color: var(--accent-1); text-decoration: underline; }
  .card-intro {
    font-size: 0.9rem;
    color: var(--text);
    line-height: 1.85;
    margin: 12px 0 8px;
  }
  .card-intro strong,
  .sum-para strong,
  .sum-item strong {
    color: var(--heading);
    font-weight: 600;
  }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 4px; }
  .chip {
    font-size: 0.72rem;
    background: var(--tag-bg);
    color: var(--text-light);
    padding: 2px 10px;
    border-radius: 20px;
  }
  details.full-summary { margin-top: 6px; }
  details.full-summary summary {
    cursor: pointer;
    font-size: 0.82rem;
    color: var(--accent-1);
    letter-spacing: 0.5px;
    user-select: none;
    display: inline-block;
  }
  details.full-summary summary:hover { text-decoration: underline; }
  details.full-summary[open] summary { margin-bottom: 10px; }
  .sum-para {
    font-size: 0.88rem;
    color: var(--text);
    line-height: 1.85;
    margin-bottom: 10px;
  }
  .sum-heading {
    display: block;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--heading);
    margin: 14px 0 6px;
    letter-spacing: 0.5px;
  }
  .sum-item {
    font-size: 0.88rem;
    color: var(--text);
    line-height: 1.85;
    padding-left: 14px;
    border-left: 2px solid var(--border);
    margin-bottom: 8px;
  }
"""


def _normalize_inner_html(inner: str) -> str:
    """Unescape entities (also inside ``<strong>`` tags), then re-escape
    ``& < >`` so the fragment stays safe when embedded in the index page."""
    parts: List[str] = []
    pos = 0
    for m in _STRONG_RE.finditer(inner):
        parts.append(html.escape(html.unescape(inner[pos:m.start()]), quote=False))
        strong_inner = m.group(0)[len("<strong>"):-len("</strong>")]
        parts.append(
            "<strong>"
            + html.escape(html.unescape(strong_inner), quote=False)
            + "</strong>"
        )
        pos = m.end()
    parts.append(html.escape(html.unescape(inner[pos:]), quote=False))
    return "".join(parts).strip()


def _classify(inner: str) -> Dict[str, str]:
    """Map a summary-card <p> to (kind, display html).

    Markdown literals produced by the exporter are lightly converted:
    ``### `` → heading, ``- `` → item; everything else stays a paragraph.
    """
    if inner.startswith("### "):
        return {"kind": "heading", "html": _normalize_inner_html(inner[4:])}
    if inner.startswith("- "):
        return {"kind": "item", "html": _normalize_inner_html(inner[2:])}
    return {"kind": "para", "html": _normalize_inner_html(inner)}


def parse_transcript_html(path: Path) -> Dict[str, Any]:
    """Extract {title, bvid, summary_paras, section_titles} from a Morandi HTML.

    - ``title``: first ``<h1>``, with a trailing " · 第N部分" suffix stripped
      (20260815 合并版 has 3 h1s).
    - ``bvid``: ``BV…`` found in the ``.subtitle`` div.
    - ``summary_paras``: list of ``{"kind", "html"}`` from all ``<p>`` in the
      summary card(s) (merged files carry several cards before the sections).
    - ``section_titles``: all ``<h3>`` titles (one per ``.section``).
    """
    text = Path(path).read_text(encoding="utf-8")

    h1s = _H1_RE.findall(text)
    title = html.unescape(h1s[0]).strip() if h1s else ""
    title = re.sub(r"\s*·\s*第\d+部分\s*$", "", title).strip()

    sub_m = _SUBTITLE_RE.search(text)
    bvid = ""
    if sub_m:
        bv_m = _BV_RE.search(sub_m.group(1))
        if bv_m:
            bvid = bv_m.group(0)

    # 合并版每部分各带一个 summary-card（与各自 section 交错出现），全部收集
    summary_paras = [
        _classify(p)
        for card in _CARD_RE.findall(text)
        for p in _P_RE.findall(card)
    ]

    section_titles = [
        html.unescape(t).strip() for t in _H3_RE.findall(text)
    ]

    return {
        "title": title,
        "bvid": bvid,
        "summary_paras": summary_paras,
        "section_titles": section_titles,
    }


def _format_badge(date: str) -> str:
    if len(date) == 8:
        return f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    return date


def _render_sum_para(p: Dict[str, str]) -> str:
    kind = p["kind"]
    if kind == "heading":
        return f'    <span class="sum-heading">{p["html"]}</span>'
    if kind == "item":
        return f'    <div class="sum-item">{p["html"]}</div>'
    return f'    <p class="sum-para">{p["html"]}</p>'


def _render_card(entry: Dict[str, Any]) -> str:
    filename = entry["path"].name
    title = entry["title"] or filename
    badge = _format_badge(entry["date"])

    intro_html = ""
    details_html = ""
    paras = entry["summary_paras"]
    if paras:
        intro_html = f'    <p class="card-intro">{paras[0]["html"]}</p>'
        rest = [_render_sum_para(p) for p in paras[1:]]
        if rest:
            details_html = (
                "    <details class=\"full-summary\">\n"
                "      <summary>查看完整总结</summary>\n"
                + "\n".join(rest)
                + "\n    </details>"
            )

    chips = ""
    if entry["section_titles"]:
        chip_html = "".join(
            f'<span class="chip">{html.escape(t)}</span>'
            for t in entry["section_titles"]
        )
        chips = f'    <div class="chips">{chip_html}</div>'

    return f"""    <article class="index-card">
      <div class="card-head">
        <span class="date-badge">{badge}</span>
        <a class="card-title" href="{html.escape(filename)}">{html.escape(title)}</a>
      </div>
{intro_html}
{chips}
{details_html}
    </article>"""


def build_index_html(directory: Path, out_path: Path) -> Path:
    """Scan ``directory`` for Morandi HTMLs (excluding ``index.html``) and
    write a date-descending overview to ``out_path``; returns ``out_path``."""
    directory = Path(directory)
    entries: List[Dict[str, Any]] = []
    for f in sorted(directory.glob("*.html")):
        if f.name == "index.html":
            continue
        parsed = parse_transcript_html(f)
        m = _DATE_RE.search(f.name)
        entries.append({
            "path": f,
            "date": m.group(1) if m else "",
            **parsed,
        })
    entries.sort(key=lambda e: e["date"], reverse=True)

    n = len(entries)
    cards = "\n".join(_render_card(e) for e in entries)

    style = _style_block()
    style = style.replace("</style>", INDEX_CSS + "\n  </style>")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>老木匠直播回放 · 总目</title>
{style}
</head>
<body>
<div class="container index-container">
  <header>
    <h1>老木匠直播回放 · 总目</h1>
    <div class="subtitle">共 {n} 场 · 生成于 {now}</div>
  </header>
  <div class="index-grid">
{cards}
  </div>
  <footer>
    <p>由 bilibili_transcript 自动生成 · 有新成稿放入目录后重跑 index-html 命令即可刷新</p>
  </footer>
</div>
</body>
</html>
"""
    out_path = Path(out_path)
    out_path.write_text(doc, encoding="utf-8")
    return out_path
