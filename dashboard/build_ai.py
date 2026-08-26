"""Inline the AI-view snapshot into a standalone page.

    python -m dashboard.build_ai

Same reasoning as dashboard/build.py: the page must be self-contained, because
the artifact CSP blocks external hosts and a runtime fetch of the JSON would
silently return nothing and render an empty page.
"""
from __future__ import annotations
from pathlib import Path

TPL = Path("dashboard/ai_view.html")
SNAP = Path("dashboard/ai_view.json")
OUT = Path("dashboard/ai_console.html")
TOKEN = "/*__DATA__*/null"


def main() -> None:
    html = TPL.read_text(encoding="utf-8")
    if TOKEN not in html:
        raise SystemExit(f"template has no {TOKEN} placeholder")
    if not SNAP.exists():
        raise SystemExit(f"missing {SNAP} -- run `python -m evaluation.export_ai_view` first")
    OUT.write_text(html.replace(TOKEN, SNAP.read_text(encoding="utf-8")),
                   encoding="utf-8")
    print(f"{OUT}  {OUT.stat().st_size/1024:.0f} kB")


if __name__ == "__main__":
    main()
