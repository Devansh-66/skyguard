# The station tier

Two things live here: the ESP32 firmware, and a Python node that speaks the same
wire protocol so the server half can be tested without any simulator at all.

```
firmware/
  skyguard_node/          ESP32 firmware (Wokwi or real hardware)
    skyguard_node.ino
    diagram.json          ESP32 + BME280 on I2C
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

**The firmware half — only in Wokwi for VS Code, or on hardware.**

Browser Wokwi at wokwi.com cannot reach a server on your machine. **Wokwi for
VS Code** bundles a private IoT gateway, and `host.wokwi.internal` resolves to
the host from inside the simulation — that is why the firmware posts there and
not to `127.0.0.1`, which inside the simulation is the ESP32 itself.

1. Install the **Wokwi Simulator** extension in VS Code and activate a licence
2. Build: `pio run` in `firmware/skyguard_node/` (paths in `wokwi.toml` point at
   `.pio/build/esp32dev/`)
3. Start the API on port 8000
4. F1 → **Wokwi: Start Simulator**
5. Watch readings arrive: `curl "http://127.0.0.1:8000/api/ingest/recent?station=Pune"`

### Not yet verified

The firmware has **not been run** — neither in Wokwi nor on hardware. It is
written against the protocol that `virtual_node.py` exercises, and the server
side of that protocol is tested, but nothing here establishes that the ESP32
build compiles, fits in flash, or keeps up at cadence. Treat the timing, memory
and radio behaviour as unmeasured until someone runs it.

The BME280 in Wokwi is a scripted part, not a physical sensor, so it cannot
reproduce the faults this project detects. Injecting a radiation-shield failure
or a slow calibration drift into a simulated probe would mean scripting the
values, at which point the simulator is testing the injector rather than the
sensor. **Fault detection is measured on the harness** (`evaluation/`), not here;
what the node tier is for is the physics screen, the frozen-baseline residual,
and the conditional uplink.

## Uplink policy

Radio TX dominates an AWS power budget, so a clean reading between heartbeats is
simply not sent. The node transmits when a reading is flagged or when the
heartbeat falls due — currently every 15 samples. The bytes-per-station-day
saving that implies has **not been measured**; it is a design intent, not a
result, until it is.
