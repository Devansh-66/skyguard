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

**Read this before creating anything: the SDK depends on the account plan.**

| Plan | What it can create for free |
| --- | --- |
| Free personal | Static Spaces, and up to 2 ZeroGPU Gradio Spaces |
| PRO | Docker and Gradio Spaces on `cpu-basic` (2 vCPU / 16 GB) |

`cpu-basic` costs nothing per hour but is gated behind a paid plan, so "the
free tier gives 16 GB" is only true with PRO. Run `hf auth whoami` and read the
`isPro` and `canPay` flags before choosing.

### If PRO — Docker Space

```bash
hf repos create <user>/skyguard-api --type space --space-sdk docker --public
```

Push this repository to it; the root `Dockerfile` builds it. Space front matter:

```yaml
---
title: SkyGuard API
emoji: 🌡️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
short_description: AWS sensor fault detection API
---
```

### If free — Gradio Space on ZeroGPU, running the same FastAPI app

This is not a GPU workload. ZeroGPU is simply the only free way to get a Python
Space, and the documented pattern is a no-op `@spaces.GPU` function (the SDK
requires at least one) with all real work outside it — so no GPU is ever
requested and no quota is burned.

```bash
hf repos create <user>/skyguard-api --type space --space-sdk gradio --flavor zero-a10g --public
```

A **Static Space** is free for everyone but can only serve the frozen export:
no ingest, no detector. A link, not the system.

### Then, either way

```
SKYGUARD_ORIGINS = https://<frontend>.vercel.app,https://<frontend>.pages.dev
```

Without it the browser fetches successfully and throws the response away, which
looks like a broken API and is a missing CORS origin.

### What the image does not contain

Neither the 138 MB ARM netCDF archive nor the 455 MB `data/` directory. The ARM
board is served from `dashboard/queue.json` and `queue_items.json` — 204 kB of
answer standing in for a closed archive — and the CSV replay behind
`/api/stations`, `/api/alerts` and `/api/clock` is simply not loaded, so those
three return 503 and nothing else notices. The dashboard calls none of them.

Regenerate the frozen queue on a machine that has the archive:

```bash
python -m scripts.export_queue
```

**The simulated network is not frozen this way.** It is graded on every request,
and it is the path live readings will arrive on over MQTT.

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
