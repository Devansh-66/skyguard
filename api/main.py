"""FastAPI service. The dashboard's data source.

    uvicorn api.main:app --reload

The pipeline runs once at startup -- expect a minute or two before the first
request is served, and a /readyz that says so rather than a hang.

The response shapes here are the same ones dashboard/export.py writes to
snapshot.json, so the static build and the live service are interchangeable and
the frontend does not care which it is talking to.
"""
from __future__ import annotations
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.engine import Engine, DEFAULT_DATA, DEFAULT_GRAPH

ENGINE: Engine | None = None
READY = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ENGINE, READY
    ENGINE = Engine(
        data_path=os.environ.get("SKYGUARD_DATA", DEFAULT_DATA),
        graph_path=os.environ.get("SKYGUARD_GRAPH", DEFAULT_GRAPH),
        causal=os.environ.get("SKYGUARD_CAUSAL", "1") != "0",
    )
    ENGINE.build()
    READY = True
    yield


app = FastAPI(title="SkyGuard", version="1.0.0", lifespan=lifespan,
              description="AWS anomaly detection for SIH 2026 PS26073")

# The dashboard is served from a file or a static host, so it is always
# cross-origin in development. Locked to localhost rather than "*": a wide-open
# CORS policy that ships to production is a habit worth not forming.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "SKYGUARD_ORIGINS",
        "http://localhost:5173,http://localhost:8000,http://127.0.0.1:5500").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# Serve the console from the API itself. Same origin, so the browser's fetch
# needs no CORS grant at all -- and a demo is one command and one URL instead
# of a static server, a port, and an origin list that has to match.
_DASH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard")
if os.path.isdir(_DASH):
    app.mount("/console", StaticFiles(directory=_DASH), name="console")


@app.get("/")
def root():
    """Land on the console if it has been built, otherwise say how to build it."""
    f = os.path.join(_DASH, "console.html")
    if os.path.exists(f):
        return FileResponse(f)
    return JSONResponse({
        "message": "console not built",
        "fix": "python -m dashboard.build",
        "api": "/docs",
    }, status_code=404)


def engine() -> Engine:
    if ENGINE is None or not READY:
        raise HTTPException(503, "engine still building; poll /readyz")
    return ENGINE


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """204 rather than a 404 in every browser console. A log full of harmless
    errors trains people to ignore the log."""
    from fastapi import Response
    return Response(status_code=204)


@app.get("/healthz")
def healthz():
    """Liveness. Answers even while the pipeline is still building."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness. Separate from liveness on purpose -- the first build takes
    minutes, and an orchestrator that cannot tell 'starting' from 'broken'
    will restart it forever."""
    if not READY:
        return JSONResponse({"status": "building"}, status_code=503)
    return {"status": "ready", "build_seconds": ENGINE.build_seconds}


@app.get("/api/meta")
def meta():
    return engine().meta()


@app.get("/api/stations")
def stations(state: str | None = None,
             budget: float = Query(1 / 7, gt=0, le=24,
                                   description="alerts per station per day")):
    return engine().stations(state=state, budget=budget)


@app.get("/api/stations/{station}/series")
def series(station: str, step: int = Query(3, ge=1, le=24),
           start: str | None = None, end: str | None = None):
    e = engine()
    if station not in set(e.live.station_name):
        raise HTTPException(404, f"unknown station {station!r}")
    return e.series(station, step=step, start=start, end=end)


@app.get("/api/alerts")
def alerts(budget: float = Query(1 / 7, gt=0, le=24),
           state: str | None = None, station: str | None = None,
           min_confidence: float = Query(0.0, ge=0.0, le=1.0)):
    """Re-thresholded on every request.

    The budget is the operator's dial and the only knob that should move
    without a re-score: it trades recall against how many engineers get
    dispatched. Changing it re-thresholds precomputed scores, which is
    milliseconds -- it does not re-run a detector.
    """
    return engine().alerts(budget=budget, state=state, station=station,
                           min_confidence=min_confidence)


@app.get("/api/alerts/{alert_id}")
def alert_detail(alert_id: int, budget: float = Query(1 / 7, gt=0, le=24)):
    found = engine().alerts(budget=budget)
    if alert_id < 0 or alert_id >= len(found):
        raise HTTPException(404, "no such alert at this budget")
    return found[alert_id]


@app.get("/api/explain")
def explain(station: str, variable: str, timestamp: str):
    """Exact Shapley values for one observation, computed on demand.

    64 coalitions at d=6 -- cheap for one point, absurd for a million, which is
    why it is a request rather than a column.
    """
    try:
        return engine().shapley(station, variable, timestamp)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/snapshot")
def snapshot(budget: float = Query(1 / 7, gt=0, le=24), step: int = 3):
    """The whole console in one call, shaped exactly like snapshot.json.

    Kept so the static build and the live service stay interchangeable: the
    frontend can point at a file or at this endpoint with no other change.
    """
    e = engine()
    sts = e.stations(budget=budget)
    return {
        **e.meta(),
        "generated_from": e.data_path,
        "alert_budget_per_station_day": budget,
        "neighbours": {s["name"]: s["neighbours"] for s in sts},
        "stations": [{**s, "series": e.series(s["name"], step=step)} for s in sts],
        "alerts": e.alerts(budget=budget),
    }


@app.post("/api/rescore")
def rescore(causal: bool = True):
    """Re-run the detectors. MINUTES, not milliseconds.

    Its own endpoint precisely so it cannot happen by accident on a page
    refresh. The only setting worth exposing is causal-vs-centred, and the
    centred variant exists only to demonstrate how much the lookahead was
    worth -- it is not a mode anyone should serve from.
    """
    global READY
    READY = False
    try:
        ENGINE.rescore(causal=causal)
        return {"status": "rescored", "causal": causal,
                "build_seconds": ENGINE.build_seconds}
    finally:
        READY = True
