#!/usr/bin/env python3
"""Dump a transcript JSON with timestamps, for finalize review."""
import json
import sys
from pathlib import Path


def fmt(t: float) -> str:
    t = int(t)
    return f"{t // 60:02d}:{t % 60:02d}"


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python tools/dump_transcript.py <transcript.json>")
        return
    d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(f"title: {d['title']}")
    print(f"total_segments: {len(d['segments'])}")
    print(f"part_sources: {json.dumps(d['part_sources'], ensure_ascii=False)}")
    print("----")
    for s in d["segments"]:
        print(f"[{fmt(s['start'])}-{fmt(s['end'])}] {s['text']}")


if __name__ == "__main__":
    main()
