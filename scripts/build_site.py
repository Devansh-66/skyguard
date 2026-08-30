"""Build everything the served site needs, from a fresh clone.

    python -m scripts.build_site

WHY THIS EXISTS

The site is served by api/main.py, which needs two things that are not in the
repository because they are generated: the React bundle in web/dist, and the
simulated network in dashboard/sim_map.json. Without them the app 404s and the
network page comes up empty, which looks like a bug and is a missing build
step.

The one input that IS committed is dashboard/wdqms.json -- the real IMD station
list -- (266 kB) because producing it needs a fetch from WMO and a build host may not
have one.

    wdqms.json  (committed)
        -> simulate.network          synthetic readings at those locations
        -> simulate.faults_and_export  inject, grade, export sim_map.json

Takes about eighty seconds, almost all of it in the grader.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(label: str, cmd: list[str], cwd: Path | None = None) -> None:
    print(f"\n=== {label} ===\n    {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=cwd or ROOT)
    if r.returncode != 0:
        sys.exit(f"\n{label} failed ({r.returncode}); stopping.")


def main() -> None:
    seed = ROOT / "dashboard" / "wdqms.json"
    if not seed.exists():
        sys.exit(f"missing {seed}, which should be committed. "
                 "Rebuild it with: python -m scripts.wdqms && "
                 "python -m dashboard.export_wdqms")

    sim = ROOT / "dashboard" / "sim_map.json"
    if sim.exists():
        print(f"{sim.name} already built ({sim.stat().st_size // 1024} kB); "
              "delete it to force a rebuild.")
    else:
        run("simulate the network", [sys.executable, "-m", "simulate.network"])
        run("inject, grade and export",
            [sys.executable, "-m", "simulate.faults_and_export"])

    web = ROOT / "web"
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        sys.exit("npm is not on PATH; install Node to build the frontend.")
    if not (web / "node_modules").exists():
        run("install frontend dependencies", [npm, "install"], cwd=web)
    run("build the frontend", [npm, "run", "build"], cwd=web)

    print("\nBuilt. Serve it with:  uvicorn api.main:app --host 0.0.0.0 --port 8000")


if __name__ == "__main__":
    main()
