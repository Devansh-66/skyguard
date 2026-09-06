import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import { cn } from '@/lib/cn'

/* HOW THE PANEL BEHAVES ACROSS THE WHOLE NETWORK.
 *
 * Every other explanation on this site is about one verdict. This one audits
 * the design, and it answers two questions that are invisible one row at a
 * time.
 *
 * IS IT REALLY THREE AGENTS?
 *
 * An agent whose contribution is zero on every row is an ornament. You cannot
 * see that on a single sensor -- a zero there just means "this one was not
 * about hardware" -- but across sixty rows it is unmissable. The strip per
 * agent shows exactly that, and the honest answer this network gives is that
 * one of the three currently is an ornament, for a reason stated underneath
 * rather than hidden.
 *
 * WHAT DOES EACH AGENT CATCH?
 *
 * The grid groups the same numbers by the fault that was INJECTED -- which the
 * panel is never shown -- so it is a measurement rather than marking our own
 * homework. An empty column is a fault class nothing on the panel detects:
 * a capability gap found by arithmetic instead of by losing a station.
 *
 * EVERY CELL CARRIES ITS COUNT.
 *
 * Fourteen injected faults across six kinds means some cells rest on two rows.
 * A thin cell has to read as thin, not as a finding, so n is never optional
 * and cells below three rows are drawn back.
 */

interface AgentRow {
  agent: string
  title: string
  n: number
  mean: number
  pushed: number
  argued_against: number
  no_effect: number
  values: number[]
}

interface Behaviour {
  rows: number
  agents: AgentRow[]
  by_kind: Record<string, { n: number; mean: Record<string, number> }>
  actions: Record<string, number>
  dispatches_avoided: number
}

const ORDER = ['data_quality', 'hardware', 'context']

export function PanelBehaviour() {
  const q = useQuery({
    queryKey: ['behaviour'] as const,
    queryFn: ({ signal }) => get<Behaviour>('/api/board/behaviour', signal),
    staleTime: Infinity,
  })

  if (q.isLoading) {
    return <Shell><p className="p-6 text-sm text-ink-3">Running the panel over the network…</p></Shell>
  }
  if (!q.data?.agents?.length) {
    return <Shell><p className="p-6 text-sm text-ink-3">The simulated network is not loaded.</p></Shell>
  }
  const d = q.data
  const agents = [...d.agents].sort(
    (a, b) => ORDER.indexOf(a.agent) - ORDER.indexOf(b.agent))
  const kinds = Object.entries(d.by_kind)
    .sort((a, b) => b[1].n - a[1].n)

  return (
    <Shell>
      <div className="border-b border-rule px-6 py-5">
        <h2 className="text-lg font-semibold tracking-tight">
          How the panel behaves across {d.rows} flagged sensors
        </h2>
        <p className="mt-1.5 max-w-[62ch] text-sm leading-relaxed text-ink-2">
          Every verdict on this board is three agents and an arbiter. These are
          the same Shapley values, gathered across the whole network — the view
          that says whether all three are doing work, and which faults each one
          actually catches.
        </p>
      </div>

      {/* ------------------------------------------------- who does the work */}
      <div className="divide-y divide-rule">
        {agents.map((a) => (
          <div key={a.agent} className="px-6 py-4">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <span className="text-sm font-medium text-ink">{a.title}</span>
              <span className="font-mono text-[11px] text-ink-3">
                decided {a.pushed + a.argued_against} of {a.n}
                {a.argued_against > 0 && ` · argued against ${a.argued_against}`}
              </span>
            </div>

            {/* One tick per sensor, placed by its contribution. Overlapping
                ticks are left overlapping: where the panel behaves the same
                way sixty times, a dense stack IS the finding. */}
            <div className="relative mt-2.5 h-6">
              <div className="absolute inset-x-0 top-3 h-px bg-rule" />
              <div className="absolute left-1/2 top-0 h-6 w-px bg-ink/20" />
              {a.values.map((v, i) => (
                <span
                  key={i}
                  title={`${v > 0 ? '+' : ''}${v.toFixed(2)}`}
                  className={cn('absolute top-1.5 h-3 w-[3px] -translate-x-1/2 rounded-full',
                    Math.abs(v) < 0.001 ? 'bg-ink-3/25'
                      : v < 0 ? 'bg-ok' : 'bg-fault')}
                  style={{ left: `${50 + (v / 1) * 50}%` }}
                />
              ))}
            </div>
            <div className="flex justify-between font-mono text-[9.5px] uppercase tracking-widest text-ink-3">
              <span>against a visit</span><span>no effect</span><span>toward one</span>
            </div>

            {a.pushed + a.argued_against === 0 && (
              /* Said out loud rather than left as an empty strip. */
              <p className="mt-2 text-xs leading-relaxed text-ink-2">
                Never affected a verdict on this network. The simulated export
                carries no housekeeping channels — supply, logger, link — so
                this agent has nothing to read. It fires correctly on the live
                node, which sends them.
              </p>
            )}
          </div>
        ))}
      </div>

      {/* --------------------------------------------- what each one catches */}
      <div className="border-t border-rule px-6 py-5">
        <h3 className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
          Mean contribution by the fault that was injected
        </h3>
        <p className="mt-1.5 max-w-[62ch] text-xs leading-relaxed text-ink-2">
          The panel is never shown which fault was injected, so this compares
          its behaviour against ground truth. A column of zeros is a fault class
          nothing here detects.
        </p>

        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[520px] border-separate border-spacing-0 text-sm">
            <thead>
              <tr>
                <th className="sticky left-0 bg-surface py-2 pr-3 text-left font-mono
                               text-[10px] uppercase tracking-widest text-ink-3">
                  Injected
                </th>
                <th className="py-2 pr-3 text-right font-mono text-[10px]
                               uppercase tracking-widest text-ink-3">n</th>
                {agents.map((a) => (
                  <th key={a.agent}
                      className="py-2 pl-3 text-right font-mono text-[10px]
                                 uppercase tracking-widest text-ink-3">
                    {a.title}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {kinds.map(([kind, row]) => {
                const thin = row.n < 3
                return (
                  <tr key={kind} className="border-t border-rule">
                    <td className={cn('sticky left-0 bg-surface border-t border-rule py-2 pr-3',
                      kind === 'none injected' ? 'text-ink-3' : 'text-ink')}>
                      {kind}
                    </td>
                    <td className={cn('tnum border-t border-rule py-2 pr-3 text-right font-mono text-xs',
                      thin ? 'text-ink-3' : 'text-ink-2')}>
                      {row.n}
                    </td>
                    {agents.map((a) => {
                      const v = row.mean[a.agent] ?? 0
                      return (
                        <td key={a.agent}
                            className={cn('tnum border-t border-rule py-2 pl-3 text-right font-mono text-xs',
                              // Thin rows are drawn back so two sensors never
                              // read as loudly as forty-six.
                              thin && 'opacity-55',
                              Math.abs(v) < 0.001 ? 'text-ink-3/60'
                                : v < 0 ? 'text-ok' : 'text-fault')}>
                          {v > 0 ? '+' : v < 0 ? '−' : ''}{Math.abs(v).toFixed(2)}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2.5 font-mono text-[10px] uppercase tracking-widest text-ink-3">
          rows under 3 sensors are drawn back — too thin to read as a finding
        </p>
      </div>

      {/* ------------------------------------------------------- the payoff */}
      <div className="border-t border-rule bg-sunk/60 px-6 py-4">
        <p className="text-sm leading-relaxed text-ink-2">
          Across this network the weather check argued escalation away{' '}
          <span className="font-semibold text-ink">
            {d.dispatches_avoided.toFixed(2)}
          </span>{' '}
          times over — visits that would otherwise have been scheduled for
          weather. That is what the third agent is worth, in the only unit a
          maintenance budget recognises.
        </p>
      </div>
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
      {children}
    </div>
  )
}
