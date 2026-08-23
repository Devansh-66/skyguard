"""Inline the snapshot into the template and write a standalone dashboard.

    python -m dashboard.build

The published page must be self-contained -- the artifact CSP blocks fetch to
any external host, so a runtime request for snapshot.json would silently return
nothing and the console would render empty. Inlining is not a shortcut; it is
the only thing that works.
"""
from __future__ import annotations
import json
from pathlib import Path

TPL = Path("dashboard/template.html")
SNAP = Path("dashboard/snapshot.json")
OUT = Path("dashboard/console.html")

def main() -> None:
    data = SNAP.read_text(encoding="utf-8")
    html = TPL.read_text(encoding="utf-8")
    # The `null` is part of the token. Replacing only the comment would leave
    # `const DATA = {...}null;` -- a syntax error -- so the two must go together.
    TOKEN = "/*__DATA__*/null"
    if TOKEN not in html:
        raise SystemExit(f"template has no {TOKEN} placeholder")
    OUT.write_text(html.replace(TOKEN, data), encoding="utf-8")
    d = json.loads(data)
    print(f"{OUT}  {OUT.stat().st_size/1024:.0f} kB  "
          f"{len(d['stations'])} stations  {len(d['alerts'])} alerts")

if __name__ == "__main__":
    main()
