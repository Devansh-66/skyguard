"""Print the shape of every API response, so web/src/api/types.ts can be checked.

    python -m scripts.api_shapes

WHY THIS EXISTS

The routers build their responses inline with dict spreads -- api/queue.py
returns `{**it, "at": ..., "verdicts": [...]}` -- so reading the source tells you
the keys the author intended, not the keys that ship. The TypeScript interfaces
were written from the output of this script rather than from the source, and
they should be re-checked against it after any router change.

This calls the route functions directly instead of going over HTTP. That keeps
it runnable without a server, and the functions are plain callables returning
plain dicts, so there is nothing an HTTP round trip would add.
"""
from __future__ import annotations
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def shape(o, depth: int = 0, limit: int = 40) -> None:
    pad = "  " * depth
    if isinstance(o, dict):
        for k, v in list(o.items())[:limit]:
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}:")
                shape(v, depth + 1, limit)
            else:
                print(f"{pad}{k}: {type(v).__name__}")
    elif isinstance(o, list):
        print(f"{pad}[list n={len(o)}]")
        if o and isinstance(o[0], (dict, list)):
            shape(o[0], depth + 1, limit)
        elif o:
            print(f"{pad}  {type(o[0]).__name__}")


def main() -> None:
    from api.ai import catalog
    from api.queue import item, work_queue

    print("===== GET /api/ai/catalog =====")
    shape(catalog())

    print("\n===== GET /api/queue =====")
    q = work_queue()
    shape(q)

    if q["items"]:
        print("\n===== GET /api/queue/{id} =====")
        print(f"(id = {q['items'][0]['id']})")
        shape(item(q["items"][0]["id"]))


if __name__ == "__main__":
    main()
