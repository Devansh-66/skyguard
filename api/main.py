"""FastAPI service. The dashboard's data source.

    uvicorn api.main:app --reload

The pipeline runs once at startup -- expect a minute or two before the first
request is served, and a /readyz that says so rather than a hang.

The response shapes here are the same ones dashboard/export.py writes to
snapshot.json, so the static build and the live service are interchangeable and
the frontend does not care which it is talking to.
"""
from __future__ import annotations
import os, time
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.engine import Engine, DEFAULT_DATA, DEFAULT_GRAPH
from api.tiles import router as tiles_router
from api.ingest import router as ingest_router
from api.ai import router as ai_router
from api.queue import router as queue_router

ENGINE: Engine | None = None
READY = False


@dataclass
class Clock:
    """Virtual time, derived from wall time rather than ticked.

    There is no background task advancing a counter. `now` is computed on read
    as origin + elapsed_wall x speed, which means the clock cannot drift, cannot
    be missed while a client is disconnected, and survives a client refresh
    without resyncing. Two browsers pointed at the same server see the same
    virtual instant because they are both reading the same arithmetic.

    Speed is virtual HOURS per real second. At 24 an hour of wall time replays
    about a hundred days, which is roughly the whole test window -- fast enough
    to watch a drift develop inside a demo slot.
    """
    origin: float = 0.0          # virtual seconds since the window start
    started: float = 0.0         # wall clock when play began
    speed: float = 24.0          # virtual hours per real second
    playing: bool = False
    span_seconds: float = 0.0

    def elapsed(self) -> float:
        if not self.playing:
            return self.origin
        return self.origin + (time.time() - self.started) * self.speed * 3600.0

    def now_seconds(self) -> float:
        return min(max(self.elapsed(), 0.0), self.span_seconds)

    def pause(self) -> None:
        self.origin = self.now_seconds()
        self.playing = False

    def play(self) -> None:
        if self.now_seconds() >= self.span_seconds:
            self.origin = 0.0            # replay from the start rather than stall
        else:
            self.origin = self.now_seconds()
        self.started = time.time()
        self.playing = True

    def seek(self, fraction: float) -> None:
        self.origin = max(0.0, min(1.0, fraction)) * self.span_seconds
        self.started = time.time()


CLOCK = Clock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ENGINE, READY
    ENGINE = Engine(
        data_path=os.environ.get("SKYGUARD_DATA", DEFAULT_DATA),
        graph_path=os.environ.get("SKYGUARD_GRAPH", DEFAULT_GRAPH),
        causal=os.environ.get("SKYGUARD_CAUSAL", "1") != "0",
    )
    ENGINE.build()
    lo, hi = ENGINE.span()
    import pandas as pd
    CLOCK.span_seconds = float(
        (pd.Timestamp(hi) - pd.Timestamp(lo)).total_seconds())
    # Starts at the END, paused. Opening at t=0 is defensible and makes a
    # terrible first impression: the clock has seen one hour of data, no
    # detector has enough history to say anything, and the console renders
    # completely empty. Anyone opening it concludes it is broken.
    #
    # Starting at the end means the page loads fully populated -- every station,
    # every alert, the whole window -- and Play then replays from the beginning,
    # because Clock.play() rewinds when it is already at the end. So the default
    # view is the finished state and the replay is a deliberate act.
    CLOCK.origin = CLOCK.span_seconds
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
# COMPRESS. Nothing was compressing anything, and the map datasets are mostly
# text: the grade strings are one character per station per step and almost
# every character is "0", so they go from 3.8 MB to about 3 kB. Serving them
# raw was throwing away a thousandfold for the sake of a missing line.
app.add_middleware(GZipMiddleware, minimum_size=1024)



app.include_router(tiles_router)
app.include_router(ingest_router)
app.include_router(ai_router)
app.include_router(queue_router)

# The map datasets the React app fetches instead of inlining. See api/mapdata.py
# for why the two frontends differ on this.
from api.mapdata import router as mapdata_router  # noqa: E402
app.include_router(mapdata_router)

# The static console used to be mounted here at /console. It is gone: the React
# app reached parity with it -- map, clock, station list, channel fields, alerts
# and the by-state summary -- and two frontends that must be kept in step is a
# guarantee that one of them is wrong. It was the older one that was wrong, in
# the end: its channel charts had collapsed to two pixels wide and nobody
# noticed, because nobody was looking at it.
#
# Its data now comes back through /api/map/* instead of being inlined, which is
# why that directory is still here.
_DASH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard")

# The React app, built by `npm run build` in web/.
#
# WHY A SUBCLASS AND NOT A PLAIN MOUNT
#
# The app routes on the client: /app/queue/sgpmetE37/D160923.11/rh is a real
# URL a user can bookmark or reload, but there is no file at that path. A plain
# StaticFiles mount 404s it, so the app works until someone presses F5 and then
# appears broken. Falling back to index.html for anything that is not a real
# file is what makes deep links survive a reload.
#
# The fallback is deliberately NOT applied to /app/assets/*: a missing bundle
# there is a broken build, and answering it with index.html would hand the
# browser HTML where it asked for JavaScript, producing a blank page and a MIME
# error instead of an honest 404.
class _SPAFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        # Starlette RAISES HTTPException(404) here rather than returning a 404
        # response, so catching the exception is the only thing that works --
        # inspecting `response.status_code` looks correct and never fires.
        # OSError is caught alongside the 404 because queue item ids contain
        # colons (sgpmetE37:D160930.5:rh). A colon is illegal in a Windows
        # filename, so the lookup raises OSError instead of 404 and every deep
        # link to an item returned a bare 500. On Linux the same URL 404s and
        # falls through correctly -- so this bug is invisible on the deploy box
        # and fatal on a developer's machine.
        try:
            return await super().get_response(path, scope)
        except (StarletteHTTPException, OSError, ValueError) as exc:
            # normpath: StaticFiles hands this path back through
            # os.path.normpath, so on Windows it arrives as
            # "assets\index.js" and a startswith("assets/") test
            # silently never matches -- the guard would work on the Linux
            # deploy box and quietly not on a developer's machine, which
            # is the worst way for a check to fail.
            guard = path.replace("\\", "/").startswith("assets/")
            if getattr(exc, "status_code", 404) != 404 or guard:
                raise
            return await super().get_response("index.html", scope)


_APP = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
if os.path.isdir(_APP):
    app.mount("/app", _SPAFiles(directory=_APP), name="app")
    # NOTE: no html=True. StaticFiles' own html mode does its own fallback
    # BEFORE the override above can run, which silently defeated the
    # assets/ guard -- a missing bundle answered 200 text/html. The
    # subclass handles the index.html fallback itself instead.


@app.get("/")
def root():
    """Land on the app if it has been built, otherwise say how to build it."""
    if os.path.isdir(_APP):
        return RedirectResponse("/app/")
    return JSONResponse({
        "message": "the web app has not been built",
        "fix": "cd web && npm install && npm run build",
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


def virtual_now() -> str:
    import pandas as pd
    lo, _ = engine().span()
    return str(pd.Timestamp(lo) + pd.Timedelta(seconds=CLOCK.now_seconds()))


@app.get("/api/clock")
def get_clock():
    lo, hi = engine().span()
    return {"now": virtual_now(), "start": lo, "end": hi,
            "speed_hours_per_second": CLOCK.speed, "playing": CLOCK.playing,
            "progress": (CLOCK.now_seconds() / CLOCK.span_seconds
                         if CLOCK.span_seconds else 1.0)}


@app.post("/api/clock")
def set_clock(playing: bool | None = None, speed: float | None = None,
              seek: float | None = Query(None, ge=0.0, le=1.0)):
    """Play, pause, change speed, or scrub.

    Seeking is a real seek: the server recomputes what it can see at that
    virtual instant, so scrubbing backwards genuinely un-detects the alerts
    that had not happened yet.
    """
    engine()
    if speed is not None:
        CLOCK.pause()
        CLOCK.speed = max(0.1, min(speed, 2000.0))
    if seek is not None:
        was = CLOCK.playing
        CLOCK.pause()
        CLOCK.seek(seek)
        if was:
            CLOCK.play()
    if playing is not None:
        CLOCK.play() if playing else CLOCK.pause()
    return get_clock()


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
           min_confidence: float = Query(0.0, ge=0.0, le=1.0),
           follow_clock: bool = True):
    """Re-thresholded on every request.

    The budget is the operator's dial and the only knob that should move
    without a re-score: it trades recall against how many engineers get
    dispatched. Changing it re-thresholds precomputed scores, which is
    milliseconds -- it does not re-run a detector.
    """
    return engine().alerts(budget=budget, state=state, station=station,
                           min_confidence=min_confidence,
                           until=virtual_now() if follow_clock else None)


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
def snapshot(budget: float = Query(1 / 7, gt=0, le=24), step: int = 3,
             window_hours: int = Query(336, ge=24, le=4000),
             follow_clock: bool = True):
    """The whole console in one call, shaped exactly like snapshot.json.

    Kept so the static build and the live service stay interchangeable: the
    frontend can point at a file or at this endpoint with no other change.
    """
    e = engine()
    until = virtual_now() if follow_clock else None
    sts = e.stations(budget=budget, until=until)
    return {
        **e.meta(),
        "generated_from": e.data_path,
        "alert_budget_per_station_day": budget,
        "clock": get_clock(),
        "window_hours": window_hours,
        "neighbours": {s["name"]: s["neighbours"] for s in sts},
        "stations": [{**s, "series": e.series(s["name"], step=step, until=until,
                                              window_hours=window_hours)}
                     for s in sts],
        "alerts": e.alerts(budget=budget, until=until),
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
