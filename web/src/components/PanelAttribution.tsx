import { cn } from '@/lib/cn'
import type { Attribution } from '../lib/triage'
import { ACTION_SHORT } from '../lib/triage'

/* HOW MUCH EACH AGENT MATTERED, AS A NUMBER RATHER THAN A LABEL.
 *
 * The panel above this already says WHICH agent carried the call. That is a
 * label, and a label cannot show that one agent argued the other way and lost,
 * or that two agreed and a third was irrelevant. This can.
 *
 * WHAT THE READER IS LOOKING AT
 *
 * A track from "no visit" to "today". Everyone starts at the left -- with no
 * agent consulted the panel recommends monitoring -- and each agent shifts the
 * running total right (toward sending someone) or left (arguing against it).
 * Where the last step lands IS the verdict. Nothing is normalised, nothing is
 * left over, and the reader can add the numbers up themselves.
 *
 * That is not a design flourish, it is the efficiency axiom of the Shapley
 * value: contributions sum exactly to the outcome. A force plot in a paper
 * usually only approximates this, because approximating is all you can do with
 * hundreds of features. With three agents every coalition is enumerable, so
 * this is the exact quantity and the arithmetic really does close.
 *
 * THE COUNTERFACTUAL IS THE HALF PEOPLE ACTUALLY USE.
 *
 * "Hardware contributed 0.75" is a number to trust. "Silence hardware and this
 * becomes CALIBRATE" is a sentence to act on -- it says what the agent bought
 * you, in the vocabulary of the work order. Both are shown; the sentence is
 * given the larger share of the row.
 */

interface Props { at: Attribution }

/** The three places the verdict can land, in escalation order. */
const STOPS = [
  { at: 0, label: 'no visit' },
  { at: 0.5, label: 'this week' },
  { at: 1, label: 'today' },
]

export function PanelAttribution({ at }: Props) {
  const cs = at.contributions
  if (!cs.length) return null

  /* Lay the steps end to end from the base. Each agent's segment starts where
     the previous one finished, so the track reads as a sequence of decisions
     and not as three bars that happen to share an axis. */
  let cursor = at.base
  const steps = cs.map((c) => {
    const from = cursor
    cursor += c.phi
    return { c, from, to: cursor }
  })

  const pct = (v: number) => `${Math.max(0, Math.min(1, v)) * 100}%`
  const decided = steps.reduce((best, s) =>
    Math.abs(s.c.phi) > Math.abs(best.c.phi) ? s : best, steps[0])

  return (
    <div className="overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">

      {/* ------------------------------------------------------- the track */}
      <div className="border-b border-rule px-5 pb-4 pt-4">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
            How much each agent moved the decision
          </span>
          <span className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
            exact · all {at.coalitions} coalitions
          </span>
        </div>

        {/* A LANE PER AGENT, NOT ONE SHARED BAR.
          *
          * Drawn on a single track the segments overlap whenever two agents
          * disagree, and the one painted last simply hides the other -- which
          * erased exactly the case worth seeing: data quality pushing toward a
          * visit and the weather check pulling it back to nothing. Stacked,
          * both are always visible and the reader can follow the running total
          * down the lanes like a waterfall. */}
        <div className="relative mt-4" style={{ height: steps.length * 14 + 6 }}>
          {steps.map(({ c, from, to }, i) => {
            const lo = Math.min(from, to), hi = Math.max(from, to)
            const none = hi - lo < 0.001
            return (
              <div key={c.agent} className="absolute inset-x-0" style={{ top: i * 14 }}>
                <div className="h-2 rounded-full bg-sunk" />
                {!none && (
                  <div
                    className={cn('absolute top-0 h-2 rounded-full',
                      c.phi < 0 ? 'bg-ok' : 'bg-fault')}
                    style={{ left: pct(lo), width: pct(hi - lo) }}
                  />
                )}
                {/* where this agent left the running total */}
                <div className="absolute top-0 size-2 -translate-x-1/2 rounded-full
                                border border-paper bg-ink-3"
                     style={{ left: pct(to) }} />
              </div>
            )
          })}

          {/* where it came to rest, through every lane */}
          <div className="absolute top-0 w-px bg-ink"
               style={{ left: pct(at.total), height: steps.length * 14 + 6 }} />
        </div>

        <div className="relative mt-1 h-4">
          {STOPS.map((s) => (
            <span key={s.at}
                  className={cn('absolute font-mono text-[9.5px] uppercase',
                    'tracking-widest text-ink-3',
                    s.at === 0 ? '' : s.at === 1 ? '-translate-x-full' : '-translate-x-1/2')}
                  style={{ left: pct(s.at) }}>
              {s.label}
            </span>
          ))}
        </div>

        {/* Two colours doing opposite work need saying once, in words. */}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1
                        font-mono text-[9.5px] uppercase tracking-widest text-ink-3">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-4 rounded-full bg-fault" />
            toward a visit
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-4 rounded-full bg-ok" />
            against one
          </span>
        </div>
      </div>

      {/* ------------------------------------------------------- the rows */}
      <div className="divide-y divide-rule">
        {steps.map(({ c }) => {
          const none = Math.abs(c.phi) < 0.001
          return (
            <div key={c.agent} className="flex items-center gap-4 px-5 py-3">
              <span className={cn('size-2 shrink-0 rounded-full',
                none ? 'bg-ink-3/40' : c.phi < 0 ? 'bg-ok' : 'bg-fault')} />

              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-ink">{c.title}</div>
                <div className="mt-0.5 text-xs text-ink-2">
                  {none
                    ? 'Made no difference to this call.'
                    : c.phi < 0
                      ? 'Argued against sending anyone.'
                      : 'Pushed toward sending someone.'}
                  {' '}
                  <span className="text-ink-3">
                    Without it: {ACTION_SHORT[c.without_action] ?? c.without_action}.
                  </span>
                </div>
              </div>

              <span className={cn('tnum shrink-0 font-mono text-sm font-semibold',
                none ? 'text-ink-3' : c.phi < 0 ? 'text-ok' : 'text-fault')}>
                {c.phi > 0 ? '+' : c.phi < 0 ? '−' : ''}{Math.abs(c.phi).toFixed(2)}
              </span>
            </div>
          )
        })}
      </div>

      {/* THE ARITHMETIC, STATED. A reader who adds the column up should be
          told in advance that it closes -- otherwise the fact that it does
          looks like a coincidence rather than the guarantee it is. */}
      <div className="border-t border-rule bg-sunk/60 px-5 py-3">
        <p className="text-xs leading-relaxed text-ink-2">
          The three add up to exactly {at.total.toFixed(2)} — the verdict as
          issued. {decided.c.title} carried it.
          {' '}
          <span className="text-ink-3">
            Shapley values over the panel: each agent is scored by what it adds
            to every possible group of the others. With three agents all eight
            groups are checked, so this is the exact share, not an estimate.
          </span>
        </p>
      </div>
    </div>
  )
}
