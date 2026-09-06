# The station tier

Two things live here: the ESP32 firmware, and a Python node that speaks the same
wire protocol so the server half can be tested without any simulator at all.

```
firmware/
  skyguard_node/          ESP32 firmware (Wokwi or real hardware)
    skyguard_node.ino
    diagram.json          ESP32 + DHT22 + pots (Wokwi has no barometer)
    weather-scenario.yaml GENERATED: drives the sensors from the simulated field
    wokwi.toml            includes the localhost route
    platformio.ini
  virtual_node.py         same protocol, plain Python, runs anywhere
```

## What the node does, and what it deliberately does not

| Tier | Runs | Why there |
|---|---|---|
| Station | Physics screen · residual against a **frozen** baseline · P² scale | O(1) state, no history, no ML runtime. Survives a dead link |
| Server | Neighbour differencing · learned stage · conformal p-values · signature naming | All of it needs neighbours |

A station has no neighbours — it has a radio. That is not a limitation to
engineer around; it is why the server tier exists.

## Why the node is *sent* its baseline instead of fitting one

Measured in `evaluation/run_edge_approx.py`: a baseline fitted on a window that
contains a 0.02 K/day drift absorbs essentially all of it. Fraction of the drift
still visible in the residual afterwards:

| Estimator | Fraction recovered |
|---|---|
| OLS | 0.035 |
| batch Huber | 0.008 |
| online Huber | 0.064 |

All near zero, and **the robust ones are no better** — batch Huber is the worst.
Robustness does not protect against a fault that grows slowly inside your own
training window, because a slow drift never looks like an outlier. A node that
refits on its own data goes blind to exactly the failure this project exists to
catch, and reports healthy while doing it.

So the server fits on an approved reference window and pushes nine coefficients
per variable; the node uses them and never refits. Nine floats is a baseline a
node can hold — which is also why the fit is harmonic.

## What the approximations cost

Also measured in `run_edge_approx.py`, against the batch computations they
replace:

| Approximation | Result |
|---|---|
| One-pass online IRLS vs batch IRLS | residual correlation 0.995–0.998, worst station 0.9892 |
| P² sketch vs exact 720-sample median/MAD | 3σ flag agreement 99.2–99.4 %, worst station 0.9805 |
| State | **20 floats** instead of 720 |

## Can you test it right now?

**The server half — yes, immediately, no simulator needed.**

```bash
python -m uvicorn api.main:app --port 8000
```

```bash
python -m firmware.virtual_node
```

That fetches the station's baseline, posts five readings covering the cases the
physics screen exists to catch, and asserts the server reached the specified
conclusion on each. It also checks that the node's screen and the server's agree
— the server re-runs the same checks rather than trusting the node's flags,
because a node with a corrupted screen is itself one of the faults we are
supposed to catch. A mismatch surfaces as `edge_screen_disagreement`.

**The firmware half — two ways, and only one of them needs anything installed.**

`SERVER` in the sketch points at the deployed Space, which is a public HTTPS
host. That is reachable from **wokwi.com in a browser**, so the simplest route
needs no extension, no licence and no local server:

1. Open the project at wokwi.com, paste in `skyguard_node.ino` and
   `diagram.json`
2. Start it; the node joins `Wokwi-GUEST`, fetches its baseline and begins
   posting
3. Watch them arrive:
   `curl "https://dev-66-skyguard-api.hf.space/api/ingest/recent?station=WOKWI-ESP32"`
   or open the network map and click the dashed marker

Verified from outside the simulator: `POST /api/ingest` as the node returns
`accepted` with a neighbour grade attached, and `GET /api/baseline/WOKWI-ESP32`
answers. The public path works; what has not been demonstrated here is the
firmware driving it.

**Against a server on your own machine**, swap `SERVER` for the commented
`host.wokwi.internal` line. That name resolves *only* under the Wokwi VS Code
extension, whose private gateway routes it to the host — from wokwi.com there
is no such route, and `localhost` there means Wokwi's own container.

1. Install the **Wokwi Simulator** extension in VS Code and activate a licence
2. Build: `pio run` in `firmware/skyguard_node/` (paths in `wokwi.toml` point at
   `.pio/build/esp32dev/`)
3. Start the API on port 8000
4. F1 → **Wokwi: Start Simulator**
5. `curl "http://127.0.0.1:8000/api/ingest/recent?station=WOKWI-ESP32"`

**The automation scenarios need the CLI or the extension.** `wokwi-cli` (with
`WOKWI_CLI_TOKEN`) or VS Code can drive `weather-scenario.yaml`; the browser
playground cannot, so there the sensors are sliders you move by hand. Real
weather in, or a browser with nothing installed — pick one.

### What is and is not established

The server side of this protocol is tested: `virtual_node.py` exercises it,
`weather-scenario.yaml` replays through `/api/ingest` end to end, and the
neighbour grading, the episode hysteresis and the board are measured against
those runs.

**Whether the ESP32 build compiles, fits in flash and keeps up at cadence is
not established by anything in this repository.** Treat the timing, memory and
radio behaviour as unmeasured until someone runs it and says so here. If you
have run it, the boot banner prints `FW_VERSION` — record which build it was,
because that string is the only way to tell from the outside.

The sensors in Wokwi are scripted parts, not physical ones. That is not an
objection any more, it is the mechanism: `make_wokwi_scenario.py` scripts them
from the same field the 344 simulated stations are drawn from, so what is being
tested is the pipeline that judges a reading — the screen, the uplink decision,
the ingest path, the neighbour comparison — rather than the sensor. **Fault
detection accuracy is measured on the harness** (`evaluation/`), not here.

## Real weather, not a knob

The DHT22 and the pressure pot are controls. Left alone they sit at 24 C and
40 %, which is furniture rather than weather -- and a residual against
neighbours means nothing when the "sensor" is a slider nobody touched.

`scripts/make_wokwi_scenario.py` writes a Wokwi automation that steps those
controls through the **same field the 344 simulated stations are drawn from**,
sampled at the node's own location (Pune: ten simulated neighbours inside
120 km). One sample per frame, thirty simulated minutes each.

```bash
python -m scripts.make_wokwi_scenario --fault drift
cd firmware/skyguard_node
wokwi-cli --scenario weather-scenario.yaml --timeout 900000 .
```

The fault is applied **to the sensor, not to the message**. The firmware is
told nothing: it reads a probe that has started lying, screens it, and decides
on its own whether to transmit. That is what a failing instrument looks like
from the board's point of view.

Measured by replaying the generated scenarios through `/api/ingest`, 240
samples each:

| Scenario | Result |
|---|---|
| clean | 200 graded readings, **no false alarms** |
| drift, 1.0 K/simulated day | WATCH at sample 172, FAULT after, final z = 11.5 |
| offset, +2.0 K | FAULT at sample 120, the first reading after onset |
| stuck | FAULT at sample 123 |
| spike, +12 K | FAULT at the spike, z = 54.9 |

Screen disagreements between node and server across all five runs: **0**.

### Two clocks, and why the node must report the right one

A sample takes two seconds of wall clock and represents thirty minutes of
weather. The uplink now declares `dt_min = SIM_MINUTES_PER_SAMPLE`, and the
node's own rate screen uses the same value.

It used to send `SAMPLE_MS / 60000` = 0.033 min, so the server's rate check
allowed a change of 3.0 C/min x 0.033 min = 0.1 C between samples against
sensor noise of 0.25 C. Every ordinary reading looked like an impossible jump,
and because the node screened against one clock and the server against another,
`edge_screen_disagreement` fired constantly -- a marker that is supposed to mean
"this node's screen has failed" meaning "the demo is compressed".

The node also sends the `frame` it is reporting for, which is what lets the
server difference it against what its neighbours were doing **at that moment**
and draw it on the same axis as the other 344.

## Uplink policy

Radio TX dominates an AWS power budget, so a clean reading between heartbeats is
simply not sent. The node transmits when a reading is flagged or when the
heartbeat falls due — currently every 15 samples. The bytes-per-station-day
saving that implies has **not been measured**; it is a design intent, not a
result, until it is.

## The Wokwi CLI and the Wokwi simulator disagree about this diagram

Measured, both directions, on 4 Sep 2026:

| Part / pin | `wokwi-cli lint` | the simulator (web and VS Code) |
|---|---|---|
| `wokwi-bme280` | rejects: "unknown part type" | **runs** |
| `board-bme280` | accepts | rejects: "Board not found" |
| `esp:TX0` / `esp:RX0` | rejects: "invalid pin" | **runs**, and the serial monitor needs them |

`diagram.json` is written for the SIMULATOR, because that is what actually
executes the firmware. `wokwi-cli lint` will therefore report two errors on this
file and both are false. Do not "fix" them: taking the CLI's advice removes the
sensor and the serial monitor at the same time, which is how an afternoon
disappears.

The CLI is still worth running -- it found two real defects here first, and
`test-scenario.yaml` turns the boot self-test into an assertion. Its part
catalogue simply is not the simulator's.

## Building

`pio run` from `skyguard_node/`. The sketch sits at the project root rather
than in `src/`, because Wokwi's web IDE and the Arduino IDE both expect it
beside `diagram.json`; `src_dir = .` in platformio.ini is what makes that work.

Keep every user-defined type above the first function. The Arduino builder
inserts generated prototypes ahead of the first function definition, so a type
declared below it produces an error pointing at an unrelated line.
