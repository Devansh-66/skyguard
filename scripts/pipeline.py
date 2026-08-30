"""Run the whole chain end to end, in order, with a clear failure message.

    python -m scripts.pipeline

Each stage writes files the next one reads, so they must run in this order the
first time. After that any stage can be re-run alone.
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

RAW = Path("skyguard_master_era5.csv")

STAGES = [
    ("prepare  audit the raw export, add solar time and q, build the "
     "neighbour graph", [sys.executable, "-m", "scripts.prepare"]),
    ("realism  degrade ERA5 to AWS realism and re-measure the graph",
     [sys.executable, "-m", "scripts.realism"]),
    ("inject   add the seven fault types with ground truth",
     [sys.executable, "-m", "inject.faults"]),
    ("evaluate baselines, learned layer and signature classifier",
     [sys.executable, "-m", "evaluation.run_full"]),
    ("export   write the dashboard snapshot from real output",
     [sys.executable, "-m", "dashboard.export"]),
    # The "build" step used to inline everything into a standalone
    # console.html. The React app replaced that page, and it fetches the same
    # data from /api/map/* instead of carrying it, so there is nothing to
    # inline. Build the frontend with `cd web && npm run build`.
]


def main() -> None:
    if not RAW.exists():
        sys.exit(
            f"\n{RAW} not found.\n\n"
            "It is deliberately not in git -- 8.8 MB of station data does not\n"
            "belong in a repo. Ask a teammate for it and drop it in the repo\n"
            "root, or point the first two stages at your own copy with --raw.\n")

    for i, (label, cmd) in enumerate(STAGES, 1):
        print(f"\n{'='*72}\n[{i}/{len(STAGES)}] {label}\n{'='*72}")
        r = subprocess.run(cmd)
        if r.returncode != 0:
            sys.exit(f"\nstage {i} failed ({' '.join(cmd)}); stopping here.")

    print("\nDone. Build the frontend with `cd web && npm run build`, then "
          "serve both with `uvicorn api.main:app`.")


if __name__ == "__main__":
    main()
