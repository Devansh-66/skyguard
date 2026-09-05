/* What to do, and which agent said so.
 *
 * The detail pane used to open with a sigma, a drift rate and a trust
 * posterior. Those are the right numbers for tuning the detector and the wrong
 * ones for someone being sent to a station: none of them says whether to bring
 * a replacement probe or a multimeter. This block answers the technician's
 * question first -- what is the job, how soon, and why -- and leaves the
 * numbers below for whoever wants to audit the call.
 */
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/cn'
import { type Assessment, PRIORITY_LABEL } from '../lib/triage'

const DECISION = {
  critical: { bar: 'bg-fault', text: 'text-fault', tone: 'fault' as const },
  warning: { bar: 'bg-watch', text: 'text-watch', tone: 'watch' as const },
  normal: { bar: 'bg-ok', text: 'text-ok', tone: 'ok' as const },
}

export function ActionCard({ a }: { a: Assessment }) {
  const d = DECISION[a.decision] ?? DECISION.normal
  return (
    <div className="relative overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
      <span className={cn('absolute inset-y-0 left-0 w-1', d.bar)} aria-hidden="true" />
      <div className="px-5 py-4 pl-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* The job, in the largest type on the screen. It is the one thing
              the reader came for. */}
          <h2 className="text-xl font-semibold tracking-tight">{a.action_label}</h2>
          <Badge tone={d.tone}>{PRIORITY_LABEL[a.priority]}</Badge>
        </div>
        <p className="mt-2 max-w-[62ch] text-[15px] leading-relaxed text-ink-2">{a.why}</p>
        {a.can_fix_remotely && (
          <p className="mt-3 flex items-center gap-2 font-mono text-xs text-ok">
            <span className="inline-block size-1.5 rounded-full bg-ok" aria-hidden="true" />
            No site visit needed — correctable centrally.
          </p>
        )}
      </div>
    </div>
  )
}

/* THREE OPINIONS, NOT ONE SCORE.
 *
 * Each row is an agent that looked at one kind of evidence and reported on its
 * own. Showing them separately IS the explainability: a reader can see that
 * the hardware agent is the one that fired, and that the weather check did not
 * excuse it, without reading any code. */
const STATUS = {
  alarm: { dot: 'bg-fault', label: 'text-fault' },
  watch: { dot: 'bg-watch', label: 'text-watch' },
  ok: { dot: 'bg-ok', label: 'text-ok' },
  unknown: { dot: 'bg-ink-3', label: 'text-ink-3' },
}

export function AgentVerdicts({ a }: { a: Assessment }) {
  return (
    <div className="divide-y divide-rule overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
      {a.verdicts.map((v) => {
        const st = STATUS[v.status] ?? STATUS.unknown
        return (
          <div key={v.agent} className="flex items-start gap-3 px-5 py-3.5">
            <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', st.dot)} aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <div className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
                {v.title}
              </div>
              <div className="mt-0.5 text-sm text-ink">{v.headline}</div>
            </div>
            <span className={cn(
              'shrink-0 font-mono text-[10px] font-semibold uppercase tracking-wider',
              st.label,
            )}>
              {v.status}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/* The case lifecycle, as the maintenance workflow defines it. Drawn as a
 * progress spine rather than prose so a planner sees at a glance where a case
 * has got to. Steps after the current one are not yet true, and the interface
 * dims them rather than claiming them. */
const STEPS = ['Detected', 'Validated', 'Case open', 'Assigned', 'Verified', 'Closed']

export function CaseProgress({ at }: { at: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
      {STEPS.map((s, i) => {
        const done = i <= at
        return (
          <li key={s} className="flex items-center gap-1">
            <span className={cn(
              'flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs',
              done ? 'border-ok/30 bg-ok-soft text-ok' : 'border-rule text-ink-3',
            )}>
              <span className={cn('size-1.5 rounded-full', done ? 'bg-ok' : 'bg-rule')}
                    aria-hidden="true" />
              {s}
            </span>
            {i < STEPS.length - 1 && (
              <span className="h-px w-2 bg-rule" aria-hidden="true" />
            )}
          </li>
        )
      })}
    </ol>
  )
}
