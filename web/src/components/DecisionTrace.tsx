import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { Assessment } from '../lib/triage'

/* THE PROCESS, NOT JUST THE CONCLUSION.
 *
 * Everything else on this page is a summary: the job, three opinions, and how
 * much each one weighed. This is the walk itself -- every question the
 * adjudicator asked, in the order it reached them, with the answer it got.
 *
 * THE CHECKS THAT DID NOT FIRE ARE THE POINT.
 *
 * A verdict is only believable once you can see what it ruled out. "Send
 * someone" means little; "the hardware was asked and is fine, the neighbours
 * were asked and did not move, the readings were asked and are 6.5 sigma out,
 * and a correction typed in today would be wrong within a fortnight" is a
 * case. The rules that answered NO carry most of that, and a summary throws
 * every one of them away.
 *
 * COLLAPSED BY DEFAULT, AND NOT A LIBRARY.
 *
 * <details> is a disclosure widget the browser already has: it opens without
 * JavaScript, it is keyboard operable and screen-reader labelled for free, and
 * a printed page opens all of it. A div with an onClick would be less of all
 * four. The summary line says what is inside so nobody has to open it to find
 * out whether they wanted it.
 */

/* Three answers, not two. A check whose evidence is missing is recorded as
   n/a rather than folded into "no": an absence dressed as a finding is the
   one thing on this screen that would be worth not believing. */
const RESULT = {
  yes: { word: 'yes', tone: 'text-fault' },
  no: { word: 'no', tone: 'text-ink-3' },
  'n/a': { word: 'cannot tell', tone: 'text-watch' },
} as const

export function DecisionTrace({ a }: { a: Assessment }) {
  const t = a.trace
  if (!t?.length) return null
  const decided = t.find((s) => s.decided)

  return (
    <details className="group overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
      <summary
        className="flex cursor-pointer list-none items-center gap-3 px-5 py-3.5
                   text-sm transition-colors hover:bg-sunk
                   [&::-webkit-details-marker]:hidden"
      >
        <ChevronRight
          size={15}
          className="shrink-0 text-ink-3 transition-transform group-open:rotate-90"
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1">
          <span className="font-medium text-ink">How this was decided</span>
          <span className="ml-2 text-ink-3">
            {t.length} check{t.length === 1 ? '' : 's'}, in order
            {decided ? ` — number ${decided.step} settled it` : ''}
          </span>
        </span>
      </summary>

      <ol className="divide-y divide-rule border-t border-rule">
        {t.map((s) => {
          const r = RESULT[s.answer as keyof typeof RESULT] ?? RESULT.no
          return (
            <li key={s.step}
                className={cn('flex gap-3 px-5 py-3',
                  s.decided && 'bg-fault-soft/40')}>
              <span className={cn(
                'mt-0.5 flex size-5 shrink-0 items-center justify-center',
                'rounded-full font-mono text-[10px]',
                s.decided ? 'bg-ink text-paper' : 'bg-sunk text-ink-3')}>
                {s.step}
              </span>

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-sm text-ink">{s.question}</span>
                  <span className={cn('font-mono text-[10px] font-semibold',
                    'uppercase tracking-widest', r.tone)}>
                    {r.word}
                  </span>
                </div>
                {s.note && (
                  <div className="mt-0.5 text-xs leading-relaxed text-ink-2">
                    {s.note}
                  </div>
                )}
                {/* Only the step that ended the walk gets to say so. The rest
                    are context, and marking them all would flatten the one
                    piece of structure this list has. */}
                {s.decided && (
                  <div className="mt-1 font-mono text-[10px] uppercase
                                  tracking-widest text-fault">
                    → {a.action_label}
                  </div>
                )}
              </div>
            </li>
          )
        })}
      </ol>

      <p className="border-t border-rule bg-sunk/60 px-5 py-3 text-xs leading-relaxed text-ink-2">
        The checks run in a fixed order and the first one to answer yes decides.
        Hardware is asked before the weather check on purpose: a dead link is a
        fault in any weather, and no coefficient will fix it.
      </p>
    </details>
  )
}
