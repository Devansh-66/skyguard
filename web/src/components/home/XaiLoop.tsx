import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/cn'

/* EXPLAINABILITY, PLAYING.
 *
 * Not a derivation and not a diagram of a model's insides. This is the
 * explanation itself, running: evidence arriving one piece at a time, each
 * piece pushing the verdict one way or the other by an amount you can see, and
 * a decision settling out of the sum of them.
 *
 * It is the shape a force plot has, animated instead of printed -- which is
 * the point. A still contribution chart tells you the answer; watching the bar
 * move as each agent reports tells you HOW MUCH each one mattered, which is
 * the question explainability is actually asked.
 *
 * The scenario is fixed and repeats, because a loop that shuffles is one
 * nobody can narrate in a room. The live board runs the same panel on real
 * readings.
 */

interface Piece {
  agent: string
  finding: string
  /** How far this pushes the verdict, -1 (innocent) .. +1 (at fault). */
  push: number
  tone: 'ok' | 'watch' | 'fault'
}

const STORY: Piece[] = [
  { agent: 'Data quality', tone: 'watch', push: 0.34,
    finding: 'Reading has drifted 4.1σ from its neighbours' },
  { agent: 'Weather or fault', tone: 'fault', push: 0.32,
    finding: 'No neighbouring station moved with it' },
  { agent: 'Hardware health', tone: 'fault', push: 0.28,
    finding: 'Value repeated on 94% of the last 64 samples' },
]

const STEP_MS = 1500
const HOLD_MS = 2600
const TOTAL = STORY.length * STEP_MS + HOLD_MS

export function XaiLoop() {
  const [t, setT] = useState(0)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setT(STORY.length * STEP_MS)     // settle on the finished verdict
      return
    }
    let raf = 0, start = 0
    const step = (ts: number) => {
      if (!start) start = ts
      setT((ts - start) % TOTAL)
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [])

  // How much of each piece has arrived, 0..1
  const arrived = STORY.map((_, i) =>
    clamp((t - i * STEP_MS) / (STEP_MS * 0.75)))
  const total = STORY.reduce((sum, p, i) => sum + p.push * arrived[i], 0)
  const settled = arrived[STORY.length - 1] >= 1

  return (
    <div ref={ref} className="overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
      {/* the running total, as a bar that fills from the middle */}
      <div className="border-b border-rule px-5 py-5">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
            Confidence this is the instrument
          </span>
          <span className={cn('tnum font-mono text-sm font-semibold',
            total > 0.66 ? 'text-fault' : total > 0.33 ? 'text-watch' : 'text-ink-3')}>
            {Math.round(total * 100)}%
          </span>
        </div>

        <div className="relative mt-3 h-2.5 overflow-hidden rounded-full bg-sunk">
          <div
            className={cn('h-full rounded-full transition-[width] duration-200 ease-out',
              total > 0.66 ? 'bg-fault' : total > 0.33 ? 'bg-watch' : 'bg-ok')}
            style={{ width: `${clamp(total) * 100}%` }}
          />
          {/* the two thresholds the verdict is read against */}
          <span className="absolute inset-y-0 left-[33%] w-px bg-ink/25" />
          <span className="absolute inset-y-0 left-[66%] w-px bg-ink/25" />
        </div>
        <div className="mt-1.5 flex justify-between font-mono text-[9.5px] uppercase tracking-widest text-ink-3">
          <span>weather</span><span>watch</span><span>fault</span>
        </div>
      </div>

      {/* each piece of evidence, sliding in as it is weighed */}
      <div className="divide-y divide-rule">
        {STORY.map((p, i) => {
          const a = arrived[i]
          return (
            <div key={p.agent}
                 className="flex items-center gap-4 px-5 py-3.5"
                 style={{ transform: `translateX(${(1 - a) * 10}px)` }}>
              <span className={cn('size-2 shrink-0 rounded-full',
                p.tone === 'fault' ? 'bg-fault' : p.tone === 'watch' ? 'bg-watch' : 'bg-ok')} />
              <div className="min-w-0 flex-1">
                <div className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
                  {p.agent}
                </div>
                <div className="mt-0.5 text-sm text-ink">{p.finding}</div>
              </div>
              {/* how much this one moved the needle */}
              <div className="flex w-24 shrink-0 items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-sunk">
                  <div className={cn('h-full rounded-full',
                    p.tone === 'fault' ? 'bg-fault' : p.tone === 'watch' ? 'bg-watch' : 'bg-ok')}
                    style={{ width: `${a * (p.push / 0.34) * 100}%` }} />
                </div>
                <span className="tnum w-8 text-right font-mono text-[11px] text-ink-3">
                  +{(p.push * a).toFixed(2)}
                </span>
              </div>
            </div>
          )
        })}
      </div>

      <div className={cn('flex items-center justify-between gap-3 border-t px-5 py-3.5',
        settled ? 'border-fault/30 bg-fault-soft' : 'border-rule')}>
        <span className="text-sm text-ink-2">
          {settled
            ? 'Three independent findings agree. Inspect the sensor and its wiring.'
            : 'Weighing the evidence…'}
        </span>
        <span className={cn('font-mono text-xs font-semibold uppercase tracking-widest',
          settled ? 'text-fault' : 'text-ink-3')}>
          {settled ? 'Fault' : '…'}
        </span>
      </div>
    </div>
  )
}

const clamp = (v: number) => Math.max(0, Math.min(1, v))
