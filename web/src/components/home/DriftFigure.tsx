import { useEffect, useMemo, useRef, useState } from 'react'

/* THE ARGUMENT OF THE PROJECT, AS ONE PICTURE.
 *
 * A drifting sensor is invisible in its own trace. Every station in a region
 * rises and falls together, so a probe sliding 0.05 C a day is buried inside a
 * daily swing forty times larger. No threshold can find it, because at no
 * single moment is any number implausible.
 *
 * Subtract what the neighbours are reading and the shared weather cancels --
 * that is what the right-hand panel is. Six traces collapse onto zero and the
 * seventh walks out of the band, and it was doing that the whole time.
 *
 * The data is generated here rather than fetched: this is a diagram of the
 * IDEA, and wiring it to a live endpoint would make a slow, fragile hero out
 * of something whose whole job is to be understood in three seconds. The
 * numbers on the rest of the page are the measured ones.
 */

const N = 120          // samples drawn
const NEIGHBOURS = 6
// The drift is deliberately SMALL against the weather: about 2.5 units total
// versus a swing of nine. That ratio is the whole point -- a real calibration
// drift is a fraction of the daily cycle, which is why it hides. Setting it
// large enough to see in the left panel would prove the opposite of the claim.
const DRIFT_PER_STEP = 0.021

/** Deterministic noise. A random hero that redraws differently on every visit
 *  is a hero nobody can point at in a slide. */
function mulberry(seed: number) {
  return () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

interface Series { raw: number[]; resid: number[] }

function build(): { series: Series[]; faulty: number } {
  const rnd = mulberry(7)
  // The shared weather: a diurnal swing plus a slow synoptic wander. Every
  // station sees this, which is exactly why it cancels.
  const weather = Array.from({ length: N }, (_, i) =>
    9 * Math.sin((i / N) * Math.PI * 4) + 3.5 * Math.sin((i / N) * Math.PI * 1.3 + 1))

  const raws: number[][] = []
  for (let s = 0; s <= NEIGHBOURS; s++) {
    const offset = (rnd() - 0.5) * 1.2
    raws.push(weather.map((w, i) => {
      const noise = (rnd() - 0.5) * 0.9
      // The last station is the faulty one: a linear drift, and nothing else
      // about it is different.
      const drift = s === NEIGHBOURS ? i * DRIFT_PER_STEP : 0
      return w + offset + noise + drift
    }))
  }
  // The residual is the station minus the MEDIAN of the others, which is what
  // the detector actually computes.
  const resid = raws.map((own, s) =>
    own.map((v, i) => {
      const others = raws.filter((_, k) => k !== s).map((r) => r[i]).sort((a, b) => a - b)
      const mid = others.length % 2
        ? others[(others.length - 1) / 2]
        : (others[others.length / 2 - 1] + others[others.length / 2]) / 2
      return v - mid
    }))
  return {
    series: raws.map((raw, i) => ({ raw, resid: resid[i] })),
    faulty: NEIGHBOURS,
  }
}

const W = 460, H = 200, PAD = 10

function path(values: number[], lo: number, hi: number, upto: number) {
  const n = Math.max(2, Math.round(upto))
  const pts: string[] = []
  for (let i = 0; i < n && i < values.length; i++) {
    const x = PAD + (i / (values.length - 1)) * (W - PAD * 2)
    const y = H - PAD - ((values[i] - lo) / (hi - lo)) * (H - PAD * 2)
    pts.push(`${x.toFixed(1)},${y.toFixed(1)}`)
  }
  return pts.join(' ')
}

export function DriftFigure() {
  const { series, faulty } = useMemo(build, [])
  const [t, setT] = useState(0)
  const ref = useRef<HTMLDivElement>(null)

  /* Draw once, when it comes into view, then stop. An animation that loops
     forever in the corner of the eye is a distraction, and one that runs
     before anyone has scrolled to it is wasted. */
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) { setT(N); return }
    let raf = 0, start = 0, running = false
    const step = (ts: number) => {
      if (!start) start = ts
      const p = Math.min(1, (ts - start) / 2600)
      setT(p * N)
      if (p < 1) raf = requestAnimationFrame(step)
    }
    const io = new IntersectionObserver((es) => {
      if (es[0].isIntersecting && !running) { running = true; raf = requestAnimationFrame(step) }
    }, { threshold: 0.25 })
    io.observe(el)
    return () => { io.disconnect(); cancelAnimationFrame(raf) }
  }, [])

  const rawAll = series.flatMap((s) => s.raw)
  const rLo = Math.min(...rawAll) - 1, rHi = Math.max(...rawAll) + 1
  const resAll = series.flatMap((s) => s.resid)
  const eLo = Math.min(...resAll) - 1, eHi = Math.max(...resAll) + 1

  return (
    <div ref={ref} className="grid gap-4 sm:grid-cols-2">
      <Panel
        label="What each station reports"
        note="Seven stations, one of them failing. Can you tell which?"
      >
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
             aria-label="Seven raw temperature traces rising and falling together, bunched so tightly that the failing station cannot be picked out.">
          {/* EVERY TRACE DRAWN THE SAME, INCLUDING THE BROKEN ONE.
              Colouring the faulty station here would answer the question the
              panel is asking. The reader should genuinely not be able to pick
              it out -- that is the finding, not a presentation choice. */}
          {series.map((s, i) => (
            <polyline
              key={i}
              points={path(s.raw, rLo, rHi, t)}
              fill="none"
              stroke="var(--color-ink-3)"
              strokeOpacity={0.55}
              strokeWidth={1.2}
            />
          ))}
        </svg>
      </Panel>

      <Panel
        label="After comparing with its neighbours"
        note="The shared weather cancels. One station walks out of the band."
        accent
      >
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
             aria-label="The same data after neighbour differencing: six traces collapse onto zero and the failing station walks out of the band.">
          {/* the band the detector calls normal */}
          <rect x={PAD} y={H / 2 - 16} width={W - PAD * 2} height={32}
                fill="var(--color-ok)" opacity="0.08" />
          <line x1={PAD} y1={H / 2} x2={W - PAD} y2={H / 2}
                stroke="var(--color-ink-3)" strokeOpacity="0.4" strokeDasharray="3 4" />
          {series.map((s, i) => (
            <polyline
              key={i}
              points={path(s.resid, eLo, eHi, t)}
              fill="none"
              stroke={i === faulty ? 'var(--color-fault)' : 'var(--color-ink-3)'}
              strokeOpacity={i === faulty ? 1 : 0.4}
              strokeWidth={i === faulty ? 2.2 : 1.1}
            />
          ))}
        </svg>
      </Panel>
    </div>
  )
}

function Panel({ label, note, accent, children }: {
  label: string; note: string; accent?: boolean; children: React.ReactNode
}) {
  return (
    <figure className="rounded-[--radius-lg] border border-rule bg-surface p-4">
      <figcaption className="mb-3">
        <div className={'font-mono text-[10px] uppercase tracking-widest '
                        + (accent ? 'text-ok' : 'text-ink-3')}>
          {label}
        </div>
        <div className="mt-1 text-sm text-ink-2">{note}</div>
      </figcaption>
      {children}
    </figure>
  )
}
