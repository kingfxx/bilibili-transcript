"""Merge multiple Morandi transcript HTML files (e.g. P1/P2/P3) into one.

Keeps a single <head>/<style> skeleton, concatenates each file's
``<div class="container">`` block in order, with a divider label between parts.
The merged file keeps the left-side TOC: every part's anchors are prefixed
(``p1-sec-1``, ``p2-sec-1`` …) so section ids never collide across parts.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_DIVIDER_CSS = """
  .part-divider {
    border: none;
    border-top: 2px solid var(--border);
    margin: 0 0 8px;
  }
  .part-divider-label {
    text-align: center;
    color: var(--text-light);
    font-size: 14px;
    letter-spacing: 0.3em;
    padding: 14px 0 6px;
  }
  .toc-part {
    font-size: 0.7rem;
    letter-spacing: 1px;
    color: var(--accent-1);
    font-weight: 600;
    margin: 14px 6px 4px;
    text-transform: uppercase;
  }"""

# 分P文件：老木匠20260815直播_P1_成稿.html（也兼容 老木匠20260815直播_P1.html）
_PART_FILE_RE = re.compile(r"^(.*)_P(\d+)(_成稿)?\.html$")

# 目录条目：<a class="toc-item[ toc-summary]" href="#summary|#sec-N">...</a>
_TOC_ITEM_RE = re.compile(
    r'<a class="toc-item[^"]*" href="#(summary|sec-\d+)">'
    r'<span class="toc-num">(.*?)</span>(.*?)</a>',
    re.DOTALL,
)


def _extract_container(text: str) -> str:
    start = text.index('<div class="container"')
    end = text.index("</body>")
    chunk = text[start:end]
    return chunk[: chunk.rindex("</div>") + len("</div>")]


def _prefix_container(container: str, part_idx: int) -> str:
    """Prefix section/summary anchors inside one part's container so that
    merged files never have colliding ids (sec-1 in P1 vs sec-1 in P2)."""
    c = re.sub(r'id="sec-(\d+)"', r'id="p{0}-sec-\1"'.format(part_idx), container)
    c = re.sub(r'id="summary"', r'id="p{0}-summary"'.format(part_idx), c)
    if part_idx > 1:
        c = re.sub(r'id="top"', "", c)  # 只保留第一部分 #top 回顶锚点
    return c


def _collect_toc_entries(text: str, part_idx: int) -> List[str]:
    """Re-emit the part's TOC items with prefixed hrefs for the merged nav."""
    entries: List[str] = []
    m = re.search(r'<nav class="toc">(.*?)</nav>', text, re.DOTALL)
    if not m:
        return entries
    for href, num, label in _TOC_ITEM_RE.findall(m.group(1)):
        if href == "summary":
            entries.append(
                '      <a class="toc-item toc-summary" href="#p{0}-summary">'
                '<span class="toc-num">✦</span>第 {0} 部分 · 全文总结</a>'.format(part_idx)
            )
        else:
            n = href.split("-")[1]
            entries.append(
                '      <a class="toc-item" href="#p{0}-sec-{1}">'
                '<span class="toc-num">{0}.{1}</span>{2}</a>'.format(part_idx, n, label)
            )
    return entries


def merge_morandi_html(html_paths: Sequence[Path], out_path: Path) -> Path:
    """Merge Morandi HTML files into out_path; returns out_path."""
    texts = [Path(p).read_text(encoding="utf-8") for p in html_paths]
    if not texts:
        raise ValueError("No HTML files to merge")

    containers = [_prefix_container(_extract_container(t), i + 1) for i, t in enumerate(texts)]

    head = texts[0][: texts[0].index("</head>")]
    head = head.replace("</style>", _DIVIDER_CSS + "\n  </style>") + "</head>"

    toc_entries: List[str] = []
    for i, t in enumerate(texts, 1):
        toc_entries.append(f'      <div class="toc-part">第 {i} 部分</div>')
        toc_entries.extend(_collect_toc_entries(t, i))

    lines = [
        head,
        "<body>",
        '<nav class="toc">',
        '  <div class="toc-head">',
        '    <span class="toc-title">目录</span>',
        '    <a class="toc-top" href="#top">回到顶部 ↑</a>',
        "  </div>",
    ]
    lines.extend(toc_entries)
    lines.append("</nav>")
    for i, c in enumerate(containers):
        if i > 0:
            lines.append('<hr class="part-divider">')
            lines.append(f'<div class="part-divider-label">— 第 {i + 1} 部分 —</div>')
        lines.append(c)
    lines += ["</body>", "</html>"]

    out_path = Path(out_path)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def merge_html_paths(paths: List[str]) -> Path:
    """CLI helper: accept file paths or a directory (glob *_成稿.html)."""
    if len(paths) == 1:
        p = Path(paths[0])
        if p.is_dir():
            files = sorted(
                f for f in p.glob("*_成稿.html") if "_成稿_合并.html" not in f.name
            )
            if not files:
                raise FileNotFoundError(f"No *_成稿.html found in {p}")
            stem = re.sub(r"_P\d+", "", files[0].stem)
            out = p / f"{stem}_合并.html"
            return merge_morandi_html(files, out)
    files = [Path(x) for x in paths]
    out = files[0].with_name(f"{files[0].stem}_合并.html")
    return merge_morandi_html(files, out)


def merge_part_groups(directory: Path, backup_dir: Optional[Path] = None) -> List[Path]:
    """Merge each group of part files (``*_P{N}`` sharing one prefix) into
    ``{prefix}_成稿_合并.html``, then move the part files into ``backup_dir``
    (default: ``directory/_分P原件备份``) so the index keeps one entry per day.

    Non-part HTML files are left untouched. Returns the merged output paths
    (empty when no part files exist).
    """
    directory = Path(directory)
    if backup_dir is None:
        backup_dir = directory / "_分P原件备份"
    backup_dir = Path(backup_dir)

    groups: Dict[str, List[Tuple[int, Path]]] = {}
    for f in sorted(directory.glob("*.html")):
        m = _PART_FILE_RE.match(f.name)
        if not m:
            continue
        prefix = m.group(1).rstrip()
        if prefix.endswith("_成稿"):
            prefix = prefix[: -len("_成稿")]
        groups.setdefault(prefix, []).append((int(m.group(2)), f))

    if not groups:
        return []

    backup_dir.mkdir(parents=True, exist_ok=True)
    merged: List[Path] = []
    for prefix, items in sorted(groups.items()):
        items.sort(key=lambda t: t[0])
        out = directory / f"{prefix}_成稿_合并.html"
        merge_morandi_html([p for _, p in items], out)
        merged.append(out)
        for _, p in items:
            p.replace(backup_dir / p.name)
    return merged
