import { useEffect, useMemo, useRef, useState } from 'react'

/* A NETWORK NOTICING SOMETHING.
 *
 * The rest of the page explains the method. This shows the consequence: a
 * field of stations sitting quiet, one of them beginning to drift, the ring
 * around it opening as the verdict firms up, and the neighbours it was judged
 * against lighting up as they are consulted.
 *
 * It is a diagram, not a feed -- the layout is fixed and the sequence is the
 * same on every visit, because a hero that shuffles is one nobody can point at
 * in a room. The real map is one click away and is genuinely live.
 */

const DOTS = 54
const FAULTY = 23          // index of the station that goes wrong
const CYCLE = 7200         // ms for one pass

function mulberry(seed: number) {
  return () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const W = 520, H = 300

export function NetworkPulse() {
  const ref = useRef<HTMLDivElement>(null)
  // Starts at the verdict, not at zero. If rAF never runs -- a frozen tab, a
  // screenshot service, animations off -- the still frame shows the moment the
  // system catches the fault rather than an empty field of grey dots.
  const [t, setT] = useState(0.72)
  const [live, setLive] = useState(true)

  const dots = useMemo(() => {
    const rnd = mulberry(11)
    // Poisson-ish scatter: jitter inside a loose grid so it reads as a network
    // over terrain rather than as a pattern.
    const out: { x: number; y: number }[] = []
    const cols = 9, rows = 6
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        out.push({
          x: 40 + (c + 0.5) * ((W - 80) / cols) + (rnd() - 0.5) * 26,
          y: 30 + (r + 0.5) * ((H - 60) / rows) + (rnd() - 0.5) * 22,
        })
      }
    }
    return out.slice(0, DOTS)
  }, [])

  // Which stations the faulty one is compared against: the nearest few.
  const neighbours = useMemo(() => {
    const f = dots[FAULTY]
    return dots
      .map((d, i) => ({ i, d2: (d.x - f.x) ** 2 + (d.y - f.y) ** 2 }))
      .filter((n) => n.i !== FAULTY)
      .sort((a, b) => a.d2 - b.d2)
      .slice(0, 5)
      .map((n) => n.i)
  }, [dots])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setT(0.72)                          // hold at the moment of the verdict
      return
    }
    // Runs on mount. The observer only PAUSES it when the figure is off
    // screen, to save a repaint; it is not what starts it. Gating the start on
    // the observer meant that anywhere the callback did not arrive the diagram
    // sat frozen on its first frame, which looks exactly like a broken chart.
    let raf = 0, start = 0
    const step = (ts: number) => {
      if (!start) start = ts
      setT(((ts - start) % CYCLE) / CYCLE)
      raf = requestAnimationFrame(step)
    }
    setLive(true)
    raf = requestAnimationFrame(step)

    const io = new IntersectionObserver((es) => {
      const on = es[0].isIntersecting
      if (on) {
        if (!raf) raf = requestAnimationFrame(step)
      } else {
        cancelAnimationFrame(raf); raf = 0; start = 0
      }
    }, { threshold: 0.2 })
    io.observe(el)
    return () => { io.disconnect(); cancelAnimationFrame(raf) }
  }, [])

  // Phases: quiet -> drifting -> neighbours consulted -> verdict -> reset
  const drift = clamp((t - 0.15) / 0.35)          // 0..1 the fault grows
  const consult = clamp((t - 0.45) / 0.18)        // neighbour links draw in
  const verdict = clamp((t - 0.62) / 0.12)        // the ring closes
  const fading = clamp((t - 0.88) / 0.12)         // everything settles back

  const f = dots[FAULTY]
  const sev = drift * (1 - fading)

  return (
    <div ref={ref} className="rounded-[--radius-lg] border border-rule bg-surface p-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
           aria-label="A field of weather stations. One begins to drift, its nearest neighbours are consulted, and a verdict is raised against it.">
        {/* the neighbours it is judged against */}
        {neighbours.map((i) => {
          const d = dots[i]
          return (
            <line key={'l' + i} x1={f.x} y1={f.y} x2={d.x} y2={d.y}
                  stroke="var(--color-brand)"
                  strokeOpacity={consult * 0.5 * (1 - fading)}
                  strokeWidth={1} strokeDasharray="3 3" />
          )
        })}

        {dots.map((d, i) => {
          const isF = i === FAULTY
          const isN = neighbours.includes(i)
          const fill = isF
            ? (sev > 0.66 ? 'var(--color-fault)'
              : sev > 0.25 ? 'var(--color-watch)' : 'var(--color-ok)')
            : 'var(--color-ink-3)'
          return (
            <g key={i}>
              {isF && verdict > 0 && (
                // the verdict ring, opening outward as confidence firms
                <circle cx={d.x} cy={d.y} r={5 + verdict * 16}
                        fill="none" stroke="var(--color-fault)"
                        strokeOpacity={(1 - verdict) * 0.9 * (1 - fading)}
                        strokeWidth={1.5} />
              )}
              <circle
                cx={d.x} cy={d.y}
                r={isF ? 4 + sev * 2.5 : isN ? 3.2 : 2.6}
                fill={fill}
                fillOpacity={isF ? 1 : isN ? 0.55 + consult * 0.4 : 0.42}
              />
            </g>
          )
        })}
      </svg>

      {/* The caption changes with the phase, so the picture is narrated rather
          than left to be guessed at. */}
      <p className="mt-3 min-h-[20px] text-sm text-ink-2">
        {!live ? 'A network of stations, watching each other.'
          : verdict > 0.1 ? 'Verdict: this one is the instrument, not the weather.'
          : consult > 0.1 ? 'Comparing against its nearest neighbours…'
          : drift > 0.12 ? 'One station is starting to disagree.'
          : 'All stations agree. Nothing to do.'}
      </p>
    </div>
  )
}

const clamp = (v: number) => Math.max(0, Math.min(1, v))
