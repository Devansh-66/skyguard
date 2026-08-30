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
API answers on `/api/*` either way, and `/` redirects to the app.

## Layout

```
web/
  vite.config.ts        base=/app/, dev proxy to uvicorn
  src/
    main.tsx            entry: QueryClient, router basename
    App.tsx             top bar + routes (no sidebar)
    api/
      types.ts          TypeScript mirrors of real API responses
      sites.ts          what the ARM station codes mean, read from the files
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
      NetworkRoute.tsx  map + validation sites (code-split: Leaflet)
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


- **Live ingest.** When readings arrive over MQTT, that path needs its own hook
  with its own staleness. The archive and the live network are different data
  with different clocks; one refresh policy would be wrong for both.

## Two networks, one map, and why they are never mixed

`sgpmetE37` decodes as **site · platform · facility**: `sgp` is ARM's Southern
Great Plains observatory, `met` the surface meteorology system carrying
temperature/pressure/humidity, `E37` Extended Facility 37 — a mast at
**Waukomis, Oklahoma**. `api/sites.ts` holds the decoding for all nine, with
place names and coordinates read out of the `.cdf` files' own global attributes
(`location_description`, `lat`, `lon`) rather than looked up.

The UI leads with the place, not the code. Nobody can be dispatched to
"sgpmetE37".

`/network` shows **one map and two tables**, deliberately:

- **The map is the deployment network** — ten simulated Indian stations. That is
  what SkyGuard is built to watch.
- **The table below is the validation set** — nine real ARM instruments in
  Oklahoma, Alaska and the Azores. They are used because ARM publishes fault
  reports written by engineers who physically inspected the hardware, and no
  Indian network publishes an equivalent answer key.

Plotting the ARM masts on the India map would claim this network monitors
Oklahoma, which it does not. Omitting them entirely leaves the board's station
names unexplained. So both appear, fully named, and clearly separated.

## A class-name collision worth not repeating

`.plate` was both the engraved-label utility *and* the section wrapper class, so
`<section className="plate">` inherited mono, 10px, uppercase and letter-spacing
into everything below it — body copy rendered as `TEN STATIONS ACROSS ASSAM AND
MAHARASHTRA`. The utility is now `.engraved`; `.plate` is layout only. A utility
class and a layout class must never share a name.

It is worth noting how this was caught: `textContent` returns the raw string and
hid it completely. Only `innerText`, which reflects `text-transform`, showed it.
Verify rendered text with `innerText`.

## Building from a fresh clone

Two things the server needs are generated and not in the repository: the
React bundle in `web/dist`, and the simulated network in
`dashboard/sim_map.json`. Without them the app 404s and the network page
comes up empty, which looks like a bug and is a missing build step.

```bash
python -m scripts.build_site
```

That simulates the network, injects and grades the faults, and builds the
frontend — about eighty seconds, almost all of it in the grader. Then serve
both from one process:

```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

`dashboard/wdqms.json` — the real IMD station list everything else is derived
from — **is** committed, because rebuilding it needs a fetch from WMO and a
build host may not have one.

## Hosting

Nothing this app serves is live. There is no ingest yet: the queue is a survey
of a fixed ARM archive and the maps are files a build step produced, so every
endpoint is a deterministic function of data that does not change. A server
that only ever returns the same bytes does not need to exist, so the whole site
can be static.

```bash
python -m scripts.build_site      # simulate, grade, export sim_map.json
python -m scripts.export_static   # freeze every API response into web/public/api
cd web && VITE_STATIC=1 VITE_BASE=/ npm run build
```

`web/dist` is then a complete site — about 6.5 MB, 1.6 MB over the wire — that
needs no Python anywhere.

| Host | `VITE_BASE` | SPA fallback | Notes |
| --- | --- | --- | --- |
| Cloudflare Pages | `/` | `public/_redirects` | build `npm run build`, output `dist` |
| Vercel | `/` | `vercel.json` | root directory `web` |
| GitHub Pages | `/<repo>/` | `dist/404.html` (written by the build) | project sites are not served from the root |

### What is not static

The tile proxy. It fetches Esri imagery, caches it, and turns the NCMRWF
boundary WMS into tiles — none of which can be frozen into a file. The static
export points the basemap straight at Esri (tiles are `<img>`, so no CORS grant
is needed) and draws the boundary from the vendored NCMRWF geometry instead:
same source, different form.

### Why not "host the frontend, run the backend locally"

Because the hosted page would fetch `http://localhost:8000`, which only
resolves on the machine running uvicorn. Everyone else gets an empty site. It
is hosting that nobody but you can use — and the static export gives the same
result with none of that.

When live ingest lands over MQTT, that changes: the archive can stay static,
the live network cannot. `VITE_STATIC` is the switch between them.
