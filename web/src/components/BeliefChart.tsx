/* The reading and the belief about it, on one shared time axis.
 *
 * WHY HAND-WRITTEN SVG AND NOT A CHART LIBRARY
 *
 * uPlot was installed for this and then removed. The series here is a few
 * hundred to a few thousand hourly points, which SVG draws without complaint,
 * and the two things this chart must do -- shade the analyst's fault interval,
 * and draw the +/-2 sigma tolerance band that defines when an item is raised --
 * are both easier as raw geometry than as a library's annotation API. A
 * dependency that is harder to use than the thing it replaces is not earning
 * its place in the bundle.
 *
 * WHY TWO PANELS AND NOT ONE
 *
 * The reading and the bias estimate are in different units and, more
 * importantly, answer different questions: the top panel is what the instrument
 * said, the bottom is what we have concluded about the instrument. Overlaying
 * them on a shared y-axis invites the reading of "the line went up" as "the
 * sensor drifted", which is precisely the confusion the belief state exists to
 * resolve.
 */
import { useId } from 'react'
import type { Series } from '../api/types'

/** From BIAS_TOLERANCE in detect/belief.py. An item is raised when |bias|
 *  exceeds this many noise sigma, so the band is the decision boundary drawn. */
const BIAS_TOLERANCE = 2

const W = 900
const H_TOP = 120
const H_BOT = 90
const GAP = 26
const PAD_L = 46
const PAD_R = 10

interface Extent { lo: number; hi: number }

function extent(xs: (number | null)[]): Extent {
  const v = xs.filter((x): x is number => x != null && Number.isFinite(x))
  if (!v.length) return { lo: 0, hi: 1 }
  let lo = Math.min(...v), hi = Math.max(...v)
  if (hi - lo < 1e-9) { lo -= 0.5; hi += 0.5 }
  const m = (hi - lo) * 0.08
  return { lo: lo - m, hi: hi + m }
}

/** Build an SVG path, breaking it at gaps. A null is a missing observation, and
 *  joining across it draws a straight line through a dropout -- which reads as
 *  data where there is none. Dropouts are a fault class here, so drawing them
 *  as continuous would hide the very thing we detect. */
function path(ys: (number | null)[], e: Extent, top: number, h: number): string {
  const n = ys.length
  const x = (i: number) => PAD_L + (i / Math.max(n - 1, 1)) * (W - PAD_L - PAD_R)
  const y = (v: number) => top + h - ((v - e.lo) / (e.hi - e.lo)) * h
  let d = '', pen = false
  for (let i = 0; i < n; i++) {
    const v = ys[i]
    if (v == null || !Number.isFinite(v)) { pen = false; continue }
    d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)} `
    pen = true
  }
  return d.trim()
}

/** Contiguous runs of `true`, as [startIndex, endIndex] pairs. Used for the
 *  analyst's fault interval, which may be split by gaps in coverage. */
function runs(flags: boolean[]): [number, number][] {
  const out: [number, number][] = []
  let start = -1
  flags.forEach((f, i) => {
    if (f && start < 0) start = i
    if (!f && start >= 0) { out.push([start, i - 1]); start = -1 }
  })
  if (start >= 0) out.push([start, flags.length - 1])
  return out
}

export function BeliefChart({ series, unit, label }:
  { series: Series; unit: string; label: string }) {
  const uid = useId()
  const n = series.t.length
  if (!n) return <p className="muted">No series for this item.</p>

  const ev = extent(series.v)
  const be = extent(series.bias)
  // The tolerance band must be visible even when the bias never approaches it,
  // otherwise the chart silently rescales and a calm sensor looks alarming.
  be.lo = Math.min(be.lo, -BIAS_TOLERANCE * 1.2)
  be.hi = Math.max(be.hi, BIAS_TOLERANCE * 1.2)

  const topY = 0
  const botY = H_TOP + GAP
  const H = H_TOP + GAP + H_BOT + 18
  const x = (i: number) => PAD_L + (i / Math.max(n - 1, 1)) * (W - PAD_L - PAD_R)
  const yb = (v: number) => botY + H_BOT - ((v - be.lo) / (be.hi - be.lo)) * H_BOT

  const fmt = (s: string) => s.slice(0, 10)

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`${label} and the belief about it over ${n} hours`}>
        {/* the analyst's fault interval, behind everything */}
        {runs(series.faulty).map(([a, b], k) => (
          <rect key={`${uid}-f${k}`} x={x(a)} y={topY} width={Math.max(x(b) - x(a), 1)}
                height={H_TOP + GAP + H_BOT} className="fault-band" />
        ))}

        {/* top: what the instrument reported */}
        <rect x={PAD_L} y={topY} width={W - PAD_L - PAD_R} height={H_TOP} className="plot-bg" />
        <path d={path(series.v, ev, topY, H_TOP)} className="line-value" />
        <text x={4} y={topY + 11} className="axis">{ev.hi.toFixed(1)}</text>
        <text x={4} y={topY + H_TOP} className="axis">{ev.lo.toFixed(1)}</text>
        <text x={PAD_L + 4} y={topY + 11} className="axis-title">{label} ({unit})</text>

        {/* bottom: what we have concluded about the instrument */}
        <rect x={PAD_L} y={botY} width={W - PAD_L - PAD_R} height={H_BOT} className="plot-bg" />
        <rect x={PAD_L} y={yb(BIAS_TOLERANCE)} width={W - PAD_L - PAD_R}
              height={Math.abs(yb(-BIAS_TOLERANCE) - yb(BIAS_TOLERANCE))} className="tolerance-band" />
        <line x1={PAD_L} x2={W - PAD_R} y1={yb(0)} y2={yb(0)} className="zero-line" />
        <path d={path(series.bias, be, botY, H_BOT)} className="line-bias" />
        <text x={4} y={botY + 11} className="axis">{be.hi.toFixed(1)}</text>
        <text x={4} y={botY + H_BOT} className="axis">{be.lo.toFixed(1)}</text>
        <text x={PAD_L + 4} y={botY + 11} className="axis-title">
          estimated bias (sigma) · band = ±{BIAS_TOLERANCE}σ, the raise threshold
        </text>

        <text x={PAD_L} y={H - 4} className="axis">{fmt(series.t[0])}</text>
        <text x={W - PAD_R} y={H - 4} textAnchor="end" className="axis">{fmt(series.t[n - 1])}</text>
      </svg>
      <figcaption className="small muted">
        Shaded span is the interval an analyst reported as faulty. It is drawn
        for comparison only — nothing in the estimate uses it.
      </figcaption>
    </figure>
  )
}
