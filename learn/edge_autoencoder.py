"""Does a TinyML autoencoder on the node earn its place? Measure it.

THE CLAIM UNDER TEST

The deck says an 8-bit 1D-CNN autoencoder on the ESP32 evaluates 1 Hz readings
and "instantly detects high-frequency transient faults" that a 15-minute poll
would miss. Nothing of the kind exists in the firmware. Before building it into
a microcontroller, the question that decides whether to bother is simpler:

    On the transients it is meant to catch, does a CNN autoencoder beat the
    rules the node ALREADY runs -- at the same false-alarm rate?

If it does not, it is a slower, larger, less explainable way of doing what a
rate-of-change check and a flatness counter already do, and the honest deck
line is "we tested it and the rules won". If it does, this file is the
training script and the numbers are the reason to ship it.

WHAT THE DATA IS, AND WHAT IT IS NOT

There is no 1 Hz AWS record anywhere in this project -- the simulated network
is 15-minute. The stream here is synthesised: a real station's 15-minute
series interpolated to 1 Hz, with sensor noise added as white plus an AR(1)
slow component at the magnitudes the feeder uses. That gives the right
low-frequency shape (a diurnal cycle) and a plausible noise floor. It does NOT
give the true spectrum of a real probe, and every number below inherits that
caveat. It is the best test available without a physical sensor.

Faults are the transient family only -- the ones the 15-minute server tier
genuinely cannot see: noise bursts, single-sample spikes, stiction (a value
that sticks for tens of seconds), and a step inside the window. Slow drift is
NOT here; it is a server-tier problem and a node cannot see it by design.

    python -m learn.edge_autoencoder
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

CLEAN = Path("data/sim/network_15min.npz")
OUT = Path("models/edge")

CH = ("temp", "rh", "pres")
NOISE = {"temp": 0.25, "rh": 1.2, "pres": 0.15}    # same as api/live.py
WIN = 60                                             # seconds per window
HZ = 1


# --------------------------------------------------------------- the stream
def stream_1hz(vals15: np.ndarray, rng: np.random.Generator,
               sigma: float) -> np.ndarray:
    """A 15-minute series made into a 1 Hz one, with sensor noise.

    Linear interpolation for the slow shape, then white noise plus an AR(1)
    term with a ~60 s memory so the noise is not implausibly flat between
    samples. Half the budget in each.
    """
    n15 = vals15.shape[0]
    t15 = np.arange(n15) * 900.0
    t1 = np.arange(0, (n15 - 1) * 900, 1.0 / HZ)
    base = np.interp(t1, t15, vals15)
    white = rng.normal(0, sigma * 0.7, t1.shape[0])
    ar = np.zeros(t1.shape[0])
    phi = np.exp(-1.0 / 60.0)
    e = rng.normal(0, sigma * 0.7 * np.sqrt(1 - phi * phi), t1.shape[0])
    for i in range(1, t1.shape[0]):
        ar[i] = phi * ar[i - 1] + e[i]
    return base + white + ar


def windows(x: np.ndarray, win: int = WIN, stride: int = WIN // 2) -> np.ndarray:
    n = (x.shape[0] - win) // stride + 1
    idx = np.arange(win)[None, :] + stride * np.arange(n)[:, None]
    return x[idx]                                     # (n, win)


# --------------------------------------------------------------- the faults
def inject(w: np.ndarray, kind: str, sigma: float, rng,
           amp: float | None = None) -> np.ndarray:
    """One transient fault into one window. Amplitudes are stated in units of
    the channel's own sensor noise so 'x8' means the same thing everywhere.

    `amp` overrides the default amplitude so a sweep can ask the only question
    that matters for a detector: at what signal-to-noise does it stop working,
    and does that point differ between the two detectors.
    """
    w = w.copy()
    n = w.shape[0]
    if kind == "noise_burst":
        a, b = sorted(rng.integers(5, n - 5, 2))
        if b - a < 10:
            a, b = 20, 45
        w[a:b] += rng.normal(0, sigma * (amp if amp is not None else 6.0), b - a)
    elif kind == "spike":
        i = rng.integers(3, n - 3)
        w[i] += sigma * (amp if amp is not None else 12.0) * rng.choice([-1, 1])
    elif kind == "stiction":
        a = rng.integers(0, n - 25)
        w[a:a + 25] = w[a]
    elif kind == "step":
        i = rng.integers(10, n - 10)
        w[i:] += sigma * (amp if amp is not None else 5.0) * rng.choice([-1, 1])
    elif kind == "dropout_hold":
        # samples missed and the last value held -- what a logger does
        a = rng.integers(5, n - 20)
        w[a:a + 15] = w[a - 1]
    return w


# ------------------------------------------------------ the rules on the node
def rule_score(W: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """What the firmware can already compute in a window, as one score.

    Three things it already tracks or trivially could: the largest one-step
    jump (the rate-of-change rail), the longest run of identical values (the
    flatness counter behind flat_pct), and the window's spread against the
    channel's known noise (the P-square sketch). Max over channels, each in
    its own noise units, so no channel dominates by its scale.
    """
    n, win, c = W.shape
    jump = np.abs(np.diff(W, axis=1)).max(axis=1) / sigma            # (n, c)
    # longest run of exactly-equal consecutive samples
    eq = (np.diff(W, axis=1) == 0)
    run = np.zeros((n, c))
    for j in range(c):
        cur = np.zeros(n)
        for t in range(eq.shape[1]):
            cur = np.where(eq[:, t, j], cur + 1, 0)
            run[:, j] = np.maximum(run[:, j], cur)
    run = run / 10.0                                                  # 10 s = 1 unit
    spread = W.std(axis=1) / sigma                                    # (n, c)
    spread_dev = np.abs(np.log(np.maximum(spread, 1e-6)))             # far from 1 either way
    return np.maximum.reduce([jump / 4.0, run, spread_dev * 2.0]).max(axis=1)


# ----------------------------------------------------------------- the CNN
def make_model():
    """3 channels x 60 s in, the same out. 1,143 parameters, so the int8
    weights are ~1 KB and the tensor arena fits an ESP32 with room to spare.

    Built in Keras rather than PyTorch for one reason: the .tflite the node
    would run is converted FROM this object, so the model that is measured and
    the model that is deployed are the same model. A first version trained in
    PyTorch and copied weights across; Keras and PyTorch disagree on
    transposed-convolution padding at stride 2, the rebuilt network differed
    from the trained one by up to 3.39 in output, and the int8 numbers it gave
    described a network nobody had evaluated.
    """
    import tensorflow as tf
    inp = tf.keras.Input(shape=(WIN, 3))
    x = tf.keras.layers.Conv1D(8, 5, padding="same", activation="relu")(inp)
    x = tf.keras.layers.Conv1D(8, 5, strides=2, padding="same", activation="relu")(x)
    x = tf.keras.layers.Conv1D(4, 5, strides=2, padding="same", activation="relu")(x)
    x = tf.keras.layers.Conv1DTranspose(8, 4, strides=2, padding="same", activation="relu")(x)
    x = tf.keras.layers.Conv1DTranspose(8, 4, strides=2, padding="same", activation="relu")(x)
    out = tf.keras.layers.Conv1D(3, 5, padding="same")(x)
    return tf.keras.Model(inp, out)


def train_ae(Wtr: np.ndarray, epochs: int, seed: int):
    import tensorflow as tf
    tf.keras.utils.set_random_seed(seed)
    model = make_model()
    model.compile(optimizer=tf.keras.optimizers.Adam(2e-3), loss="mse")
    X = Wtr.astype(np.float32)
    hist = model.fit(X, X, epochs=epochs, batch_size=256, shuffle=True, verbose=0)
    for ep, l in enumerate(hist.history["loss"], 1):
        print(f"    epoch {ep:2d}  mse {l:.4f}")
    return model


def ae_score(model, W: np.ndarray) -> np.ndarray:
    X = W.astype(np.float32)
    out = model.predict(X, batch_size=2048, verbose=0)
    return ((out - X) ** 2).mean(axis=(1, 2))


# ---------------------------------------------------------------- the test
def auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """Rank-based AUC, no sklearn needed."""
    from scipy.stats import rankdata
    s = np.concatenate([pos, neg])
    r = rankdata(s)
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2)
                 / (len(pos) * len(neg)))


def run(stations: int, epochs: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    z = np.load(CLEAN, allow_pickle=True)
    # A handful of stations, spread out, so the model sees several diurnal
    # shapes rather than one.
    pick = rng.choice(z["temp"].shape[1], size=stations, replace=False)

    # ---- build clean windows, normalised per channel by the sensor noise
    sig = np.array([NOISE[c] for c in CH])
    tr_w, te_w = [], []
    for s in pick:
        chans = []
        for c in CH:
            v = np.asarray(z[c][:, s], dtype=np.float64)
            v = v[np.isfinite(v)]
            chans.append(stream_1hz(v[:8 * 96], rng, NOISE[c]))   # 8 days at 1 Hz
        x = np.stack(chans, axis=1)                                  # (t, 3)
        # centre each window on its own mean: the CNN must judge SHAPE, not
        # level, or it learns the diurnal cycle and calls dawn a fault
        Wn = windows(x)
        Wn = Wn - Wn.mean(axis=1, keepdims=True)
        Wn = Wn / sig                                                 # noise units
        cut = int(Wn.shape[0] * 0.7)
        tr_w.append(Wn[:cut]); te_w.append(Wn[cut:])
    Wtr = np.concatenate(tr_w)
    Wte = np.concatenate(te_w)
    print(f"  windows: train {Wtr.shape[0]}, test {Wte.shape[0]}, "
          f"{WIN} s x {len(CH)} ch at {HZ} Hz")

    # ---- faulted test windows, one channel at a time
    kinds = ("noise_burst", "spike", "stiction", "step", "dropout_hold")
    faulted = {k: [] for k in kinds}
    for k in kinds:
        for w in Wte:
            j = rng.integers(0, len(CH))
            f = w.copy()
            f[:, j] = inject(w[:, j], k, 1.0, rng)     # already in noise units
            faulted[k].append(f)
        faulted[k] = np.stack(faulted[k])

    # ---- the two detectors
    print("  training the autoencoder on clean windows only")
    t0 = time.time()
    model = train_ae(Wtr, epochs, seed)
    fit_s = time.time() - t0
    n_params = int(model.count_params())

    unit = np.ones(len(CH))                      # windows are already in noise units
    s_clean_ae = ae_score(model, Wte)
    s_clean_rule = rule_score(Wte, unit)

    # thresholds at a 1% false-alarm rate on clean, for both
    thr_ae = float(np.percentile(s_clean_ae, 99))
    thr_rule = float(np.percentile(s_clean_rule, 99))

    res = {"windows_train": int(Wtr.shape[0]), "windows_test": int(Wte.shape[0]),
           "cnn_params": int(n_params), "cnn_fit_s": round(fit_s, 1),
           "false_alarm_rate": 0.01, "faults": {}}
    print(f"\n  {'fault':<14} {'CNN AUC':>8} {'rules AUC':>10} {'CNN det@1%':>11} {'rules det@1%':>13}")
    for k in kinds:
        a = ae_score(model, faulted[k]); r = rule_score(faulted[k], unit)
        row = {"cnn_auc": round(auc(a, s_clean_ae), 3),
               "rules_auc": round(auc(r, s_clean_rule), 3),
               "cnn_detect": round(float((a > thr_ae).mean()), 3),
               "rules_detect": round(float((r > thr_rule).mean()), 3)}
        res["faults"][k] = row
        print(f"  {k:<14} {row['cnn_auc']:>8.3f} {row['rules_auc']:>10.3f} "
              f"{row['cnn_detect']:>11.1%} {row['rules_detect']:>13.1%}")

    # ---- THE FAIR TEST: how faint can the fault be before each detector
    # loses it. The default amplitudes above are large enough that rules are
    # trivially perfect; a learned detector could only justify itself by
    # holding on longer as the signal shrinks.
    sweep = {"noise_burst": (1.5, 2.0, 3.0), "spike": (3.0, 4.0, 6.0),
             "step": (1.0, 2.0, 3.0)}
    print("\n  amplitude sweep (x sensor noise), detection at 1% false alarms")
    print(f"  {'fault':<14} {'amp':>5} {'CNN AUC':>8} {'rules AUC':>10} {'CNN det':>8} {'rules det':>10}")
    res["sweep"] = {}
    for k, amps in sweep.items():
        for amp in amps:
            F = []
            for w in Wte[:20000]:
                j = rng.integers(0, len(CH)); f = w.copy()
                f[:, j] = inject(w[:, j], k, 1.0, rng, amp=amp); F.append(f)
            F = np.stack(F)
            a = ae_score(model, F); r = rule_score(F, unit)
            row = {"amp": amp, "cnn_auc": round(auc(a, s_clean_ae), 3),
                   "rules_auc": round(auc(r, s_clean_rule), 3),
                   "cnn_detect": round(float((a > thr_ae).mean()), 3),
                   "rules_detect": round(float((r > thr_rule).mean()), 3)}
            res["sweep"][f"{k}@{amp}"] = row
            print(f"  {k:<14} {amp:>5.1f} {row['cnn_auc']:>8.3f} {row['rules_auc']:>10.3f} "
                  f"{row['cnn_detect']:>8.1%} {row['rules_detect']:>10.1%}")

    # ---- cost on the microcontroller
    # MACs per window, counted layer by layer from the architecture.
    macs = 0
    L = WIN
    for cin, cout, k, stride in ((3, 8, 5, 1), (8, 8, 5, 2), (8, 4, 5, 2)):
        L = (L + 2 * 2 - k) // stride + 1
        macs += L * cout * cin * k
    for cin, cout, k, stride in ((4, 8, 4, 2), (8, 8, 4, 2)):
        L = (L - 1) * stride - 2 + k
        macs += L * cout * cin * k
    macs += WIN * 3 * 8 * 5
    res["cnn_macs_per_window"] = int(macs)
    res["cnn_int8_weights_bytes"] = int(n_params)
    # TFLM int8 conv on a 240 MHz ESP32 without vector extensions runs in the
    # low tens of MMAC/s. Stated as a range, not a measurement.
    res["esp32_latency_ms_estimate"] = [round(macs / 20e6 * 1e3, 1),
                                        round(macs / 5e6 * 1e3, 1)]

    OUT.mkdir(parents=True, exist_ok=True)
    model.save(OUT / "ae_1dcnn.keras")
    try:
        res["tflite"] = export_tflite_int8(model, Wtr, Wte, faulted, s_clean_ae)
        t = res["tflite"]
        print(f"\n  int8 .tflite: {t['tflite_bytes']:,} bytes, int8/float score "
              f"correlation {t['int8_float_score_corr']}, tensor arena ~{t['tensor_arena_est_bytes']:,} B")
        print(f"  {'fault':<14} {'float det':>10} {'int8 det':>9}")
        for k, v in t["int8_vs_float_detect"].items():
            print(f"  {k:<14} {v['float_detect']:>10.1%} {v['int8_detect']:>9.1%}")
    except Exception as e:                                   # noqa: BLE001
        res["tflite"] = {"error": f"{type(e).__name__}: {e}"}
        print(f"\n  tflite export skipped: {res['tflite']['error']}")
    (OUT / "report.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


def export_tflite_int8(model, Wtr: np.ndarray, Wte: np.ndarray,
                       faulted: dict, s_clean_ae: np.ndarray) -> dict:
    """The trained network as an 8-bit .tflite -- what TFLM would run.

    Full integer quantisation, int8 weights AND activations, with clean
    windows as the representative dataset. Then the only question that
    matters: does the int8 model still score the faults the way the float one
    did? A quantisation that changes the verdict is not a deployment of the
    model, it is a different model.
    """
    import tensorflow as tf

    def rep():
        for i in range(0, min(2000, Wtr.shape[0])):
            yield [Wtr[i:i + 1].astype(np.float32)]

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = rep
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    tfl = conv.convert()
    (OUT / "ae_1dcnn_int8.tflite").write_bytes(tfl)

    it = tf.lite.Interpreter(model_content=tfl)
    it.allocate_tensors()
    i_d, o_d = it.get_input_details()[0], it.get_output_details()[0]
    si, zi = i_d["quantization"]; so, zo = o_d["quantization"]

    def score_int8(W):
        outv = np.empty(W.shape[0])
        for n in range(W.shape[0]):
            q = np.clip(np.round(W[n] / si + zi), -128, 127).astype(np.int8)[None]
            it.set_tensor(i_d["index"], q)
            it.invoke()
            y = (it.get_tensor(o_d["index"]).astype(np.float32) - zo) * so
            outv[n] = ((y[0] - W[n]) ** 2).mean()
        return outv

    sub = Wte[:3000]
    s_clean_q = score_int8(sub)
    s_clean_f = ae_score(model, sub)
    thr_q = float(np.percentile(s_clean_q, 99))
    thr_f = float(np.percentile(s_clean_f, 99))
    per = {}
    for k, F in faulted.items():
        Fq = F[:1500]
        per[k] = {"int8_detect": round(float((score_int8(Fq) > thr_q).mean()), 3),
                  "float_detect": round(float((ae_score(model, Fq) > thr_f).mean()), 3)}
    # how far the int8 scores sit from the float scores on the same windows
    agree = float(np.corrcoef(s_clean_q, s_clean_f)[0, 1])

    arena = sum(int(np.prod(d_["shape"])) for d_ in it.get_tensor_details()
                if d_["shape"].size)
    return {"tflite_bytes": len(tfl), "int8_float_score_corr": round(agree, 4),
            "int8_vs_float_detect": per, "tensor_arena_est_bytes": int(arena)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stations", type=int, default=12)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    r = run(a.stations, a.epochs, a.seed)
    print(f"\n  CNN: {r['cnn_params']} parameters -> ~{r['cnn_int8_weights_bytes'] / 1024:.1f} KB int8,"
          f" {r['cnn_macs_per_window']:,} MACs/window,"
          f" ~{r['esp32_latency_ms_estimate'][0]}-{r['esp32_latency_ms_estimate'][1]} ms on an ESP32 (estimate)")
    print(f"  written to {OUT}")


if __name__ == "__main__":
    main()
