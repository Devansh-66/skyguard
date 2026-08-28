/* Geometry for the chart-paper plots. No JSX, no React -- just the maths, so it
 * can be tested and so the components stay about layout.
 */

export interface Extent {
  lo: number
  hi: number
}

/** Vertical range of a series, padded, never zero-height. */
export function extent(xs: (number | null)[], pad = 0.08): Extent {
  const v = xs.filter((x): x is number => x != null && Number.isFinite(x))
  if (!v.length) return { lo: 0, hi: 1 }
  let lo = Math.min(...v)
  let hi = Math.max(...v)
  if (hi - lo < 1e-9) {
    lo -= 0.5
    hi += 0.5
  }
  const m = (hi - lo) * pad
  return { lo: lo - m, hi: hi + m }
}

/** Include a value in an extent -- used to keep a tolerance band on screen even
 *  when the trace never approaches it. Without this the plot silently rescales
 *  and a calm instrument looks alarming. */
export function include(e: Extent, ...values: number[]): Extent {
  let { lo, hi } = e
  for (const v of values) {
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  return { lo, hi }
}

export interface Frame {
  x0: number
  y0: number
  w: number
  h: number
  e: Extent
  n: number
}

export const px = (f: Frame, i: number) =>
  f.x0 + (i / Math.max(f.n - 1, 1)) * f.w

export const py = (f: Frame, v: number) =>
  f.y0 + f.h - ((v - f.e.lo) / (f.e.hi - f.e.lo)) * f.h

/** Build a pen path, LIFTING THE PEN at gaps.
 *
 * A null is a missing observation, and joining across it draws a straight line
 * through a dropout -- which reads as data where there is none. Dropouts are a
 * fault class this product detects, so drawing them as continuous would hide
 * exactly what it exists to find. A real pen recorder does the same thing: no
 * paper contact, no line.
 */
export function penPath(ys: (number | null)[], f: Frame): string {
  let d = ''
  let down = false
  for (let i = 0; i < ys.length; i++) {
    const v = ys[i]
    if (v == null || !Number.isFinite(v)) {
      down = false
      continue
    }
    d += (down ? 'L' : 'M') + px(f, i).toFixed(1) + ' ' + py(f, v).toFixed(1) + ' '
    down = true
  }
  return d.trim()
}

/** The same trace, but only the stretches outside +/-threshold.
 *
 * Drawn as a second path over the first in oxide red, so an exceedance is a
 * property of the line itself rather than a separate marker the eye has to
 * associate with it. One sample of slack is left either side so the red does
 * not appear to start in mid-air. */
export function exceedPath(
  ys: (number | null)[],
  f: Frame,
  threshold: number,
): string {
  const out: (number | null)[] = ys.map((v) =>
    v != null && Number.isFinite(v) && Math.abs(v) > threshold ? v : null,
  )
  // bridge to the neighbouring in-range sample so the segment meets the trace
  for (let i = 0; i < ys.length; i++) {
    if (out[i] == null) continue
    if (i > 0 && out[i - 1] == null) out[i - 1] = ys[i - 1]
    if (i < ys.length - 1 && out[i + 1] == null) out[i + 1] = ys[i + 1]
    // skip the sample we just filled forward
    if (i < ys.length - 1) i++
  }
  return penPath(out, f)
}

/** Bias expressed in units of the sensor's own noise.
 *
 * THIS IS THE ONLY FORM WORTH PLOTTING, and getting it wrong is subtle. The
 * estimator's tolerance test is `|bias| <= BIAS_TOLERANCE * noise`, not
 * `|bias| <= BIAS_TOLERANCE`, and severity on a board item is
 * `|bias| / noise`. Plotting raw bias against a constant band therefore draws
 * some instruments sitting calmly inside a threshold they have in fact
 * crossed -- a chart quietly contradicting the number printed beside it.
 *
 * Normalised this way, the band is a true constant, and the end of the trace
 * equals the severity on the card by construction rather than by luck.
 */
export function inSigma(
  bias: (number | null)[],
  noise: (number | null)[],
): (number | null)[] {
  return bias.map((b, i) => {
    const n = noise[i]
    if (b == null || n == null || !Number.isFinite(b) || !Number.isFinite(n) || n === 0) {
      return null
    }
    return b / n
  })
}

/** Contiguous runs of `true`, as [start, end] index pairs. Used for the
 *  analyst's fault interval, which may be split by gaps in coverage. */
export function runs(flags: boolean[]): [number, number][] {
  const out: [number, number][] = []
  let start = -1
  flags.forEach((f, i) => {
    if (f && start < 0) start = i
    if (!f && start >= 0) {
      out.push([start, i - 1])
      start = -1
    }
  })
  if (start >= 0) out.push([start, flags.length - 1])
  return out
}

/** A short date for a chart margin: "13 Sep". */
export function stamp(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
  const M = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return d.getUTCDate() + ' ' + M[d.getUTCMonth()]
}
