# SkyGuard web

The operator-facing app: React + TypeScript, built by Vite, served by the same
FastAPI process that serves the API.

## Running it

Two modes. Both put the browser on **one origin**, so the CORS policy in
`api/main.py` behaves identically in each — a rule that only ever runs in one
mode is a rule nobody has tested.

**Development** (hot reload; Vite proxies `/api` to uvicorn):

```bash
python -m uvicorn api.main:app --port 8000
```

```bash
cd web && npm run dev
```

Then open <http://localhost:5173/app/>.

**Production** (one process, one URL):

```bash
cd web && npm run build
```

```bash
python -m uvicorn api.main:app --port 8000
```

Then open <http://localhost:8000/app/>. FastAPI mounts `web/dist` at `/app`;
`dist/` is gitignored, so a fresh clone must build before the route exists. The
API answers on `/api/*` either way, and the older static pages remain at
`/console/`.

## Layout

```
web/
  vite.config.ts        base=/app/, dev proxy to uvicorn
  src/
    main.tsx            entry: QueryClient, router basename
    App.tsx             top bar + routes (no sidebar)
    api/
      types.ts          TypeScript mirrors of real API responses
      client.ts         the only place fetch() is called
      queries.ts        one TanStack Query hook per endpoint
    components/
      Barograph.tsx     one ruled plot: paper, pen, tolerance band
      chart.ts          plot geometry (no JSX, so it is testable)
      ItemDetail.tsx    the evidence pane, used by the board
      BeliefChart.tsx   two plates on one time axis
      Async, Badge, Callout, Field
    routes/
      HomeRoute.tsx     landing page
      BoardRoute.tsx    maintenance board (list + detail)
    styles/
      tokens.css        paper, ink, and the four marks; no hex codes elsewhere
      app.css           layout and component styles
```

Routes: `/` is the landing page, `/board` and `/board/<id>` are the maintenance
board. `/queue` and `/queue/<id>` redirect to the board, which is where they
lived before.

## The material: barograph chart paper

The instruments this product watches have been drawing on ruled paper for a
century and a half — barographs, thermographs, hygrographs; a clockwork drum
turning under an ink pen, with the observer's note in the margin. That is not a
theme picked to look nice. It is what this data has always looked like, and a
chart recorder is already a time-series display, so the borrowed language does
real work instead of sitting on top of the interface.

Consequences, all deliberate:

- **The ground is warm paper, not a dark dashboard.** Every competing tool is
  dark with a neon accent. Ruled cream is more distinctive and easier to read
  for the hours an operator actually spends here.
- **Colour is scarce.** Real chart stock is cream, brown ruling and one ink.
  Oxide red is reserved for a trace that has left tolerance, so it means
  something the instant it appears rather than being one hue among nine.
- **IBM Plex throughout** — drawn for technical documentation, with a true mono
  carrying tabular figures and a serif that reads as an instrument nameplate.
- **Everything sits on a 9px grid**, the minor ruling, so panels and rows align
  with the lines behind them rather than floating at arbitrary offsets.

The landing page hero is not an illustration: it is the worst fault currently on
the board, drawn as the recorder would have drawn it, with the analyst's own
note pinned in the margin. It costs no extra request — the board uses the same
query. Further plates (the network map, per-station insight plots) drop in below
it without disturbing anything above.

## Plot bias in sigma, never raw

`Barograph` takes a `threshold` and colours the pen oxide beyond it. **Feed it
`inSigma(bias, noise)`, not `series.bias`.**

The estimator's test is `|bias| <= BIAS_TOLERANCE * noise`, and severity on an
item is `|bias| / noise` — so a constant ±2 band against *raw* bias draws some
instruments sitting calmly inside a threshold they have in fact crossed. This
shipped briefly and was caught by measurement: `nsametC1:pres` showed severity
3.0 on its card beside a trace whose raw bias never passed 1.21, and rendered
with no red at all. `/api/queue/{id}` returns the `noise` series precisely so
the client never has to assume a constant band. Normalised, the end of the trace
equals the card's severity by construction rather than by luck.

The pen also **lifts at gaps** rather than joining across them. A null is a
missing observation, and a straight line through a dropout reads as data where
there is none — and dropouts are a fault class this product detects.

## Conventions

**Components never call `fetch`.** They call a hook from `api/queries.ts`, which
calls `api/client.ts`. Keeping query keys in one file is what will make cache
invalidation possible when live ingest arrives — the board will need to be
invalidated from outside the component that renders it.

**`types.ts` is generated from real responses, not read off the routers.** The
routers build responses with dict spreads, so the source shows intended keys
rather than shipped ones. Re-check after any router change:

```bash
python -m scripts.api_shapes
```

**Caveats from the API are rendered, never dropped.** `scorecard.caveat`,
`reference.warning` and `action_note` are prose the backend returns *because it
must be shown*: the precision figure is a lower bound, and an estimate whose
reference sits inside its own fault is compromised. `Callout` exists to make
these hard to quietly delete.

**`null` is not `0`.** A recall of 0% and a recall that cannot be computed are
different claims. Nullable numbers render as an em dash.

**Colour is never chosen at the call site.** Components take a semantic `tone`;
`tokens.css` decides what that looks like. Severity thresholds live in
`severityTone` alone, and come from `BIAS_TOLERANCE` in `detect/belief.py`. The
severity spine on a board card is a redundant encoding of the number beside it —
never the only one.

## Two platform traps, both already hit

Both live in `_SPAFiles` in `api/main.py` and both behave *differently on
Windows and Linux*, which is the reason they are written down:

1. `StaticFiles` **raises** `HTTPException(404)`; it does not return a 404
   response. Checking `response.status_code` looks right and never fires.
2. Board item ids contain colons (`sgpmetE37:D160930.5:rh`). A colon is illegal
   in a Windows filename, so the lookup raises `OSError` rather than 404, and
   every deep link returned a bare 500. On Linux the same URL 404s and falls
   through correctly.

The fallback deliberately does **not** apply to `/app/assets/*`: a missing
bundle is a broken build, and answering it with `index.html` yields a blank page
and a MIME error instead of an honest 404.

## Not built yet

- The **network map** is still the static page at `/console/console.html`, which
  plots the simulated Indian network. It is linked from the top bar rather than
  stubbed as a route. When it is ported, note that the map is Indian and the AI
  results are validated on real foreign ARM instruments — those two datasets
  must not be plotted on one map.
- **Live ingest.** When readings arrive over MQTT, that path needs its own hook
  with its own staleness. The archive and the live network are different data
  with different clocks; one refresh policy would be wrong for both.
