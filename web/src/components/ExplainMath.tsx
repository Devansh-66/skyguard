import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/cn'

/* HOW THE NUMBER WAS ARRIVED AT, STEP BY STEP.
 *
 * The panel already says WHICH agent carried a decision. This says HOW the
 * number underneath it was computed, and it is the honest form of explainable
 * AI for a system whose detection is statistical rather than learned: there is
 * no model here to attribute, so attributing to one would be theatre. What
 * there is, is arithmetic -- and arithmetic can be shown.
 *
 * Four steps, revealed in sequence:
 *
 *   1  the station's own reading, which on its own looks fine
 *   2  minus the median of its neighbours   -> the residual
 *   3  divided by the trailing spread       -> z, in sigmas
 *   4  compared against 6 and 8             -> the band
 *
 * Every value is passed in from the assessment that produced the verdict, so
 * this cannot drift away from the decision it claims to explain. Where a value
 * is genuinely unavailable the row says so instead of showing a plausible
 * number, because a worked example with an invented figure in it is worse than
 * no worked example.
 */

export interface MathInputs {
  /** The station's own reading, in the channel's units. */
  reading?: number | null
  /** Median of the neighbours at the same moment, same units. */
  neighbour?: number | null
  /** Robust spread the residual is standardised by. */
  sigma?: number | null
  /** Standardised distance, if the caller already has it. */
  z?: number | null
  unit?: string
  watchAt?: number
  faultAt?: number
}

export function ExplainMath({
  reading, neighbour, sigma, z, unit = '', watchAt = 6, faultAt = 8,
}: MathInputs) {
  const [step, setStep] = useState(0)
  const ref = useRef<HTMLDivElement>(null)

  // Derive what we can, and be explicit about what we cannot.
  const residual = reading != null && neighbour != null ? reading - neighbour : null
  const zVal = z != null ? z
    : (residual != null && sigma ? residual / sigma : null)
  const band = zVal == null ? null
    : Math.abs(zVal) >= faultAt ? 'FAULT'
    : Math.abs(zVal) >= watchAt ? 'WATCH' : 'OK'

  /* Steps arrive one per beat. The timer is the only driver -- no observer --
     because this sits inside a panel the reader has already chosen to open,
     and gating it on visibility is how content ends up never appearing. */
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setStep(4)
      return
    }
    setStep(0)
    const ids = [1, 2, 3, 4].map((n) =>
      window.setTimeout(() => setStep(n), 260 * n))
    return () => ids.forEach(window.clearTimeout)
  }, [reading, neighbour, sigma, z])

  const fmt = (v: number | null | undefined, dp = 2) =>
    v == null || !Number.isFinite(v) ? '—' : v.toFixed(dp)

  return (
    <div ref={ref} className="overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
      <div className="divide-y divide-rule">
        <Row n={1} on={step >= 1}
             label="What this station reported"
             expr={reading == null ? 'not available' : `${fmt(reading)} ${unit}`}
             note="On its own, a plausible number." />
        <Row n={2} on={step >= 2}
             label="What its neighbours reported"
             expr={neighbour == null ? 'not available' : `${fmt(neighbour)} ${unit}`}
             note="Median, so one bad neighbour cannot move it." />
        <Row n={3} on={step >= 3}
             label="The difference — the residual"
             expr={residual == null ? 'not available'
               : `${fmt(reading)} − ${fmt(neighbour)} = ${fmt(residual)} ${unit}`}
             note="Shared weather cancels here. What is left belongs to the instrument."
             emphasis />
        <Row n={4} on={step >= 4}
             label="Standardised by this station's own spread"
             expr={zVal == null ? 'not available'
               : sigma
                 ? `${fmt(residual)} ÷ ${fmt(sigma)} = ${fmt(zVal, 1)} σ`
                 : `${fmt(zVal, 1)} σ`}
             note={`Watch at ${watchAt}σ, fault at ${faultAt}σ — calibrated against a fault-free run.`}
             emphasis />
      </div>

      {band && (
        <div className={cn(
          'flex items-center justify-between gap-3 border-t px-5 py-3.5 transition-opacity duration-500',
          step >= 4 ? 'opacity-100' : 'opacity-0',
          band === 'FAULT' ? 'border-fault/30 bg-fault-soft'
            : band === 'WATCH' ? 'border-watch/30 bg-watch-soft'
            : 'border-ok/30 bg-ok-soft',
        )}>
          <span className="text-sm text-ink-2">
            {band === 'OK'
              ? 'Inside the band — no action.'
              : `Beyond ${band === 'FAULT' ? faultAt : watchAt} sigma.`}
          </span>
          <span className={cn(
            'font-mono text-xs font-semibold uppercase tracking-widest',
            band === 'FAULT' ? 'text-fault' : band === 'WATCH' ? 'text-watch' : 'text-ok',
          )}>
            {band}
          </span>
        </div>
      )}
    </div>
  )
}

function Row({ n, on, label, expr, note, emphasis }: {
  n: number; on: boolean; label: string; expr: string; note: string
  emphasis?: boolean
}) {
  return (
    <div
      className={cn(
        'px-5 py-3.5 transition-all duration-500 ease-out',
        // Transform and colour only. Never opacity: a stalled transition would
        // leave the row invisible, and these rows are the explanation.
        on ? 'translate-y-0' : 'translate-y-1',
      )}
    >
      <div className="flex items-baseline gap-3">
        <span className={cn(
          'flex size-5 shrink-0 items-center justify-center rounded-full font-mono text-[10px]',
          on ? 'bg-ink text-paper' : 'bg-sunk text-ink-3',
        )}>
          {n}
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
            {label}
          </div>
          <div className={cn('tnum mt-1 font-mono',
                             emphasis ? 'text-base font-medium text-ink' : 'text-sm text-ink-2')}>
            {expr}
          </div>
          <div className="mt-1 text-xs text-ink-3">{note}</div>
        </div>
      </div>
    </div>
  )
}
