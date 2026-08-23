# Running SkyGuard

Python 3.11 or 3.12, CPU only. Two dependencies.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
```

## The one thing you need that is not in the repo

`skyguard_master_era5.csv` (8.8 MB, 87,600 rows, 10 stations, calendar 2023).
It is gitignored on purpose — station data does not belong in a repo. Get it
from a teammate and put it in the repo root.

## Everything, in order

```bash
python -m scripts.pipeline
```

Roughly 10–20 minutes. Then open `dashboard/console.html` in any browser. It is
fully self-contained — **no server, no `python -m http.server`**. Double-click
it.

## Or one stage at a time

Each stage reads what the previous one wrote, so the first run must be in order.
After that any stage can be re-run alone.

| # | Command | Reads | Writes |
|---|---|---|---|
| 1 | `python -m scripts.prepare` | `skyguard_master_era5.csv` | `data/skyguard_prepared.csv`, `data/neighbours.json`, `data/audit_report.json` |
| 2 | `python -m scripts.realism` | the raw export | `data/skyguard_realistic.csv`, `data/neighbours_realistic.json`, `data/realism_comparison.json` |
| 3 | `python -m inject.faults` | `data/skyguard_realistic.csv` | `data/skyguard_injected.csv`, `data/injected_events.csv` |
| 4 | `python -m evaluation.run` | injected data | `evaluation/results.json` — baselines only, fast |
| 5 | `python -m evaluation.run_full` | injected data | the full comparison table + confusion matrix, printed |
| 6 | `python -m dashboard.export` | injected data | `dashboard/snapshot.json` |
| 7 | `python -m dashboard.build` | snapshot + template | `dashboard/console.html` |

Stage 4 is the fast loop while you are working on a detector. Stage 5 is the
one that produces the numbers worth quoting.

## Useful flags

```bash
python -m inject.faults --rate 3 --replicates 20     # more events, same prevalence
python -m evaluation.run_full --budget 0.0714        # 1 alert per station per fortnight
python -m evaluation.run_full --runs 10              # all replicates, slower
python -m dashboard.export --budget 0.5              # a noisier console, for demos
```

Everything is seeded. Re-running a stage with the same flags reproduces the same
files byte for byte.

## Editing the dashboard

Edit `dashboard/template.html`, then `python -m dashboard.build`. Never edit
`console.html` — it is generated and every rebuild overwrites it.

The palette is six CSS custom properties at the top of the template. Changing
the ground, ink and accent there changes the whole page.

## If something breaks

- **`skyguard_master_era5.csv not found`** — see above, it is not in the repo.
- **`ModuleNotFoundError: detect`** — run from the repo root with `python -m`,
  not `python detect/baseline.py`.
- **Console opens blank** — you are looking at `template.html` rather than
  `console.html`. The template has a `/*__DATA__*/` placeholder, not data.
- **`All-NaN slice` warnings** — expected. Dropout windows are genuinely all
  NaN; the warning is numpy being loud, not a failure.
