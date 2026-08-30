# Deploying SkyGuard

Two pieces, deployed separately, because they have different needs.

```
  Vercel / Cloudflare Pages          Hugging Face Space (Docker)
  ─────────────────────────          ───────────────────────────
  web/dist                    ──▶    api/  detect/  physics/  learn/
  React bundle, static files         FastAPI, the belief engine,
  VITE_API_BASE points here          the simulated network
                                     SKYGUARD_ORIGINS names the frontend
```

There is a third piece that is deployed by neither: the model that runs **on
the ESP32**. It is a different, much smaller model with a different job — a
single station judging its own readings with no neighbours to compare against.
The server's belief engine and the edge model are not the same artefact and
should not be confused in the writeup.

## 1. Backend — Hugging Face Space

Free Spaces give 2 vCPU and 16 GB, which is far more than this needs. Create a
**Docker** Space and give its `README.md` this front matter:

```yaml
---
title: SkyGuard API
emoji: 🌡️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
---
```

Push this repository to it. The `Dockerfile` at the root builds the simulated
network at image build time — about eighty seconds — so the Space does not
spend that on every cold start.

Then set one Space secret:

```
SKYGUARD_ORIGINS = https://<your-frontend>.vercel.app,https://<your-frontend>.pages.dev
```

Without it the browser will fetch successfully and then throw the response
away, which looks like a broken API and is actually a missing CORS origin.

### What the image does not contain

The 138 MB ARM netCDF archive. Building the maintenance board reads 591 files
to produce 200 kB of answer, and that answer cannot change: the archive is
closed and the analyst reports are written. So `dashboard/queue.json` and
`dashboard/queue_items.json` ship instead, regenerated on a machine that has
the archive with:

```bash
python -m scripts.export_queue
```

The API detects the archive's absence and serves those, marking the response
`"source": "precomputed"`. **The simulated network is not frozen this way** —
it is graded on every request, and it is the path live readings will arrive on
over MQTT.

## 2. Frontend — Vercel or Cloudflare Pages

```bash
cd web
VITE_API_BASE=https://<user>-<space>.hf.space npm run build
```

| | Vercel | Cloudflare Pages |
| --- | --- | --- |
| Root directory | `web` | `web` |
| Build command | `npm run build` | `npm run build` |
| Output | `dist` | `dist` |
| SPA fallback | `web/vercel.json` | `web/public/_redirects` |
| Env | `VITE_API_BASE` | `VITE_API_BASE` |

Leave `VITE_BASE` unset for the root; set it to `/<repo>/` only for GitHub
Pages, which serves project sites from a subpath.

## 3. Local — which is what the demo runs on

One process serves both, same origin, no CORS and no API base to configure:

```bash
python -m scripts.build_site
python -m uvicorn api.main:app --port 8000
```

The blueprint's advice on this still holds: run the finals demo locally. Venue
Wi-Fi failing mid-demo is a documented way to lose, and hosting is for
teammates and the pre-round link.

## Not built yet

`POST /api/ingest` accepts a reading and screens it against WMO limits, but
nothing pushes the verdict to the dashboard — there is no WebSocket, so the map
replays a file rather than watching a stream. Closing that is what makes the
real-time claim demonstrable, and it is the same code path the ESP32 will use.
