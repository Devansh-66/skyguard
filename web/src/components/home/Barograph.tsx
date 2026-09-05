import { useEffect, useMemo, useRef, useState } from 'react'

/* A BAROGRAPH, WHICH IS WHAT THIS PRODUCT ACTUALLY IS.
 *
 * The previous hero was a field of dots -- a generic network diagram that
 * could have belonged to any monitoring product, and it took a third of the
 * screen to say very little.
 *
 * This is the instrument the whole project imitates. A barograph is a drum of
 * ruled paper turning under an inked arm; the paper is printed with CURVED
 * hour lines, because the pen swings on a pivot and its tip travels an arc,
 * not a straight line. That curve is the signature of the thing -- anyone who
 * has seen a real chart recognises it instantly, and nobody who has not will
 * mistake it for a generic graph.
 *
 * The shaded band is what the neighbouring stations are reading. The pen
 * starts inside it and walks out. That is the entire product in one strip:
 * the reading alone looks plausible throughout, and only the distance from
 * the band says anything is wrong.
 *
 * Wide and short on purpose. It sits under a headline, not instead of one.
 */

const W = 960, H = 190
const PAD_L = 8, PAD_R = 8, PAD_T = 16, PAD_B = 22
const N = 300                 // samples across the drum
const CYCLE = 14000           // ms for a full pass

function mulberry(seed: number) {
  return () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function Barograph() {
  const ref = useRef<HTMLDivElement>(null)
  /* Starts most of the way through. A still frame -- a frozen tab, a
     screenshot, animations disabled -- should show the pen already outside the
     band, because that is the moment worth seeing. */
  const [t, setT] = useState(0.82)

  const { band, pen } = useMemo(() => {
    const rnd = mulberry(19)
    const band: { lo: number; hi: number; mid: number }[] = []
    const pen: number[] = []
    let wander = 0
    for (let i = 0; i < N; i++) {
      // The weather everyone shares: a diurnal swing plus a slow synoptic drift.
      wander += (rnd() - 0.5) * 0.06
      const mid = Math.sin((i / N) * Math.PI * 6) * 0.42
                + Math.sin((i / N) * Math.PI * 1.7 + 0.8) * 0.22
                + wander * 0.5
      const spread = 0.13
      band.push({ mid, lo: mid - spread, hi: mid + spread })
      // This station: the same weather, its own noise, and -- from a third of
      // the way in -- a calibration drift that never stops.
      const drift = i > N * 0.34 ? ((i - N * 0.34) / N) * 1.15 : 0
      pen.push(mid + (rnd() - 0.5) * 0.07 + drift)
    }
    return { band, pen }
  }, [])

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let raf = 0, start = 0
    const step = (ts: number) => {
      if (!start) start = ts
      setT(((ts - start) % CYCLE) / CYCLE)
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [])

  const drawn = Math.max(2, Math.round(t * N))
  const x = (i: number) => PAD_L + (i / (N - 1)) * (W - PAD_L - PAD_R)
  const y = (v: number) => H / 2 - v * (H - PAD_T - PAD_B) * 0.42

  const bandPath =
    band.slice(0, drawn).map((b, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(b.hi).toFixed(1)}`).join(' ')
    + ' ' +
    band.slice(0, drawn).reverse().map((b, k) => {
      const i = drawn - 1 - k
      return `L${x(i).toFixed(1)} ${y(b.lo).toFixed(1)}`
    }).join(' ') + ' Z'

  const penPath = pen.slice(0, drawn)
    .map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')

  const tip = drawn - 1
  const outside = pen[tip] > band[tip].hi || pen[tip] < band[tip].lo
  const excursion = Math.abs(pen[tip] - band[tip].mid)

  /* THE CURVED HOUR LINES. On a real chart the pen arm pivots at one end, so
     every hour line is an arc struck from that pivot. Drawing them straight is
     the giveaway that someone has only seen a photograph of one. */
  const hours = Array.from({ length: 13 }, (_, i) => {
    const px = PAD_L + (i / 12) * (W - PAD_L - PAD_R)
    const bow = 26
    return `M${px} ${PAD_T} Q${px + bow} ${H / 2} ${px} ${H - PAD_B}`
  })

  return (
    <div ref={ref}
         className="overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
           aria-label="A barograph chart. A shaded band shows what neighbouring stations are reading; one station's pen starts inside the band and slowly walks out of it.">
        {/* the ruled drum paper */}
        {Array.from({ length: 7 }, (_, i) => {
          const yy = PAD_T + (i / 6) * (H - PAD_T - PAD_B)
          return <line key={'h' + i} x1={PAD_L} x2={W - PAD_R} y1={yy} y2={yy}
                       stroke="var(--color-ink)" strokeOpacity={i === 3 ? 0.16 : 0.07}
                       strokeWidth={i === 3 ? 1 : 0.6} />
        })}
        {hours.map((d, i) => (
          <path key={'v' + i} d={d} fill="none" stroke="var(--color-ink)"
                strokeOpacity={0.07} strokeWidth={0.6} />
        ))}

        {/* what the neighbours say */}
        <path d={bandPath} fill="var(--color-ok)" fillOpacity={0.14} />

        {/* this station's pen */}
        <path d={penPath} fill="none"
              stroke={outside ? 'var(--color-fault)' : 'var(--color-ink)'}
              strokeOpacity={outside ? 1 : 0.75}
              strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" />

        {/* the nib, and the gap it has opened */}
        {outside && (
          <line x1={x(tip)} x2={x(tip)} y1={y(band[tip].mid)} y2={y(pen[tip])}
                stroke="var(--color-fault)" strokeOpacity={0.5}
                strokeWidth={1} strokeDasharray="2 2" />
        )}
        <circle cx={x(tip)} cy={y(pen[tip])} r={3.4}
                fill={outside ? 'var(--color-fault)' : 'var(--color-ink)'} />
      </svg>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-rule px-4 py-2.5">
        <span className="flex items-center gap-4 text-xs text-ink-3">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-4 rounded-sm bg-ok/25" />
            what the neighbours read
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4 rounded-sm bg-ink/70" />
            this station
          </span>
        </span>
        <span className={'tnum font-mono text-xs ' + (outside ? 'text-fault' : 'text-ink-3')}>
          {outside ? `off by ${excursion.toFixed(2)} — flagged` : 'within tolerance'}
        </span>
      </div>
    </div>
  )
}
