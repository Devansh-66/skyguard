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
      SkyScene.tsx      the generated hero sky
      ItemDetail.tsx    the evidence pane, used by the board
      BeliefChart.tsx   reading + belief on a shared time axis
      Async, Badge, Callout, Field
    routes/
      HomeRoute.tsx     landing page
      BoardRoute.tsx    maintenance board (list + detail)
    styles/
      tokens.css        two palettes; no hex codes anywhere else
      app.css           layout and component styles
```

Routes: `/` is the landing page, `/board` and `/board/<id>` are the maintenance
board. `/queue` and `/queue/<id>` redirect to the board, which is where they
lived before.

## The hero

`SkyScene` draws a mountain sky on a 2-D canvas: five ridgelines built by 1-D
midpoint displacement (seeded, so the skyline is stable across resizes), a sky
gradient keyed to the real local hour, stars, a sun or moon on an arc, drifting
cloud and valley fog. Far ridges are blended toward the horizon colour — aerial
perspective is what makes layered silhouettes read as distance.

It is driven by state, not chosen for looks: `unrest` is the share of stations
with a sensor on the board, and it raises cloud cover, wind speed and darkness.
A healthy network is a clear dawn; a failing one closes in. The caption under
the hero says which, because a visual signal nobody can decode is decoration.

Two things that will look wrong if you do not know why:

- **`VISUAL_UNREST_CAP = 0.55`.** Unrest is capped for *drawing only*; the
  caption reports the true figure. A fault archive puts every station on the
  board by construction, so the honest input sits pinned at 1.0 — uncapped, the
  sky would be permanently overcast, which is a status display stuck on one
  reading. The hero also carries the headline and must stay legible at the worst
  value the input can take.
- **Night is moonlit, not black.** Sampled off the canvas, the first pass put
  the sky at `rgb(10,17,40)` against ridges at `rgb(14,17,29)` — four points of
  luminance apart, invisible outside a dark room. The floor was lifted until the
  separation reached ~18.

`mediaSrc` is a slot for a real video to take over as the background layer
later, with no other change.

Motion respects `prefers-reduced-motion`: those visitors get one still frame,
not a paused loop burning a core.

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
