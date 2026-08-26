"""Work out which ARM periods are clean, and emit the download commands.

    python -m scripts.arm_clean_plan            # print the plan
    python -m scripts.arm_clean_plan --write    # also write run_clean_pull.ps1

WHY A PLAN RATHER THAN A DOWNLOAD

The corpus so far was deliberately pulled AROUND fault windows, which is right
for studying faults and wrong for studying the atmosphere: 89 % of the rows sat
inside a Data Quality Report and had to be discarded before the conservation
ratios could be measured, leaving about 60,000 clean minutes across four
stations. That is a thin base for a number the whole coordinate choice rests on.

This picks periods that touch NO human-flagged fault interval, spread across
seasons AND years so the ratios are not one year's weather at one site.

It does not download. The ARM Live endpoint needs credentials, which live only
in ARM_USER and ARM_TOKEN in the operator's own shell and are never handled
here, never logged, and never written to a file.
"""
from __future__ import annotations
import argparse
from pathlib import Path

import pandas as pd

# Seasonal anchors. Northern-hemisphere winter, spring, summer, autumn -- the
# ratio between the diurnal cycle and synoptic variability is itself seasonal,
# so a single season would give a number that does not generalise.
ANCHORS = [(1, 10), (4, 10), (7, 10), (10, 10)]   # (month, day-of-month)
WINDOW_D = 21


def clean_windows(dqr: pd.DataFrame, years: range, per_station: int
                  ) -> dict[str, list[tuple]]:
    out: dict[str, list[tuple]] = {}
    for ds, g in dqr.groupby("datastream"):
        bad = [(r.start, r.end) for r in g.itertuples()]
        picks = []
        # Advance the season AND the year together, so four windows are four
        # different seasons in four different years rather than one year's
        # weather sampled four times. Falling back to a later year keeps a
        # station that was faulty in the target year from dropping out.
        yrs = list(years)
        for i in range(per_station):
            mth, day = ANCHORS[i % len(ANCHORS)]
            wanted = yrs[min(i * 2, len(yrs) - 1)]
            for y in yrs[yrs.index(wanted):] + yrs[:yrs.index(wanted)]:
                try:
                    a = pd.Timestamp(year=y, month=mth, day=day)
                except ValueError:
                    continue
                b = a + pd.Timedelta(days=WINDOW_D)
                if any((a <= e) and (b >= s) for s, e in bad):
                    continue
                if (a.date(), b.date()) in picks:
                    continue
                picks.append((a.date(), b.date()))
                break
        out[ds] = picks
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dqr", default="data/arm/dqr_tprh.csv")
    ap.add_argument("--per-station", type=int, default=4)
    ap.add_argument("--from-year", type=int, default=2016)
    ap.add_argument("--to-year", type=int, default=2024)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    dqr = pd.read_csv(args.dqr, parse_dates=["start", "end"])
    plan = clean_windows(dqr, range(args.from_year, args.to_year + 1),
                         args.per_station)

    lines, days = [], 0
    for ds, picks in sorted(plan.items()):
        for a, b in picks:
            lines.append(f"python -m scripts.arm_download {ds} {a} {b}")
            days += WINDOW_D

    print(f"{len(lines)} windows, {days} station-days, "
          f"roughly {days * 0.25:.0f} MB\n")
    for ds, picks in sorted(plan.items()):
        seasons = ", ".join(f"{a}" for a, _ in picks)
        print(f"  {ds:16s} {len(picks)} windows: {seasons}")

    if args.write:
        p = Path("scripts/run_clean_pull.ps1")
        p.write_text(
            "# Clean-period ARM pull. Set your credentials first:\n"
            "#   $env:ARM_USER='your-arm-id'\n"
            "#   $env:ARM_TOKEN='token from https://adc.arm.gov/armlive/home'\n"
            "# Windows here touch NO human-flagged fault interval.\n"
            "if (-not $env:ARM_USER -or -not $env:ARM_TOKEN) {\n"
            "  Write-Error 'Set ARM_USER and ARM_TOKEN first'; exit 1\n}\n\n"
            + "\n".join(lines) + "\n",
            encoding="utf-8")
        print(f"\nwrote {p} -- run it after setting the two env vars")


if __name__ == "__main__":
    main()
