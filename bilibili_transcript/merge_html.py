"""Merge multiple Morandi transcript HTML files (e.g. P1/P2/P3) into one.

Keeps a single <head>/<style> skeleton, concatenates each file's
``<div class="container">`` block in order, with a divider label between parts.
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
  }"""

# 分P文件：老木匠20260815直播_P1_成稿.html（也兼容 老木匠20260815直播_P1.html）
_PART_FILE_RE = re.compile(r"^(.*)_P(\d+)(_成稿)?\.html$")


def _extract_container(text: str) -> str:
    start = text.index('<div class="container">')
    end = text.index("</body>")
    chunk = text[start:end]
    return chunk[: chunk.rindex("</div>") + len("</div>")]


def merge_morandi_html(html_paths: Sequence[Path], out_path: Path) -> Path:
    """Merge Morandi HTML files into out_path; returns out_path."""
    texts = [Path(p).read_text(encoding="utf-8") for p in html_paths]
    if not texts:
        raise ValueError("No HTML files to merge")

    containers = [_extract_container(t) for t in texts]

    head = texts[0][: texts[0].index("</head>")]
    head = head.replace("</style>", _DIVIDER_CSS + "\n  </style>") + "</head>"

    lines = [head, "<body>"]
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
