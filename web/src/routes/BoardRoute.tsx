/* The maintenance board: what a technician should do next, and the evidence.
 *
 * WHY MASTER-DETAIL AND NOT A PAGE PER ITEM
 *
 * Triage is a sequence, not a destination. An operator works down the list
 * comparing one sensor against the last, and a full page navigation between
 * each throws away that comparison along with the scroll position. The list
 * stays put and only the right pane changes.
 *
 * The selection lives in the URL (/board/<id>) rather than in component state,
 * so a specific instrument can be linked to a colleague, and the browser's back
 * button steps back through the triage rather than leaving the board entirely.
 *
 * The ordering is the server's `rank` and this component does not re-sort it.
 * Rank is severity weighted by weight of evidence; reproducing that formula
 * here would give two rankings that quietly drift apart.
 */
import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQueue } from '../api/queries'
import { Async } from '../components/Async'
import { Badge, severityTone } from '../components/Badge'
import { Callout } from '../components/Callout'
import { ItemDetail } from '../components/ItemDetail'

export function BoardRoute() {
  const selected = useParams()['*'] || ''
  const navigate = useNavigate()
  const q = useQueue()
  const items = q.data?.items

  // Land on the worst item rather than an empty pane. `replace` keeps this out
  // of history, so back from the board goes home instead of bouncing between
  // the empty state and the first selection.
  useEffect(() => {
    if (!selected && items && items.length) {
      navigate('/board/' + items[0].id, { replace: true })
    }
  }, [selected, items, navigate])

  return (
    <div className="board">
      <Async query={q}>
        {(data) => (
          <>
            <aside className="board-list">
              <header className="board-head">
                <h1>Maintenance board</h1>
                <p className="muted small">
                  {data.items.length} sensors across {data.stations_scanned} stations,
                  worst first.
                </p>
              </header>

              <div className="board-score">
                <Score v={data.scorecard.analyst_named} k="named by analysts" />
                <Score v={data.scorecard.we_raised_of_those} k="we raised" />
                <Score
                  v={
                    data.scorecard.recall == null
                      ? '—'
                      : Math.round(data.scorecard.recall * 100) + '%'
                  }
                  k="recall"
                />
              </div>

              <ul className="cards">
                {data.items.map((it) => {
                  const active = it.id === selected
                  return (
                    <li key={it.id}>
                      <button
                        className={'card' + (active ? ' active' : '')}
                        onClick={() => navigate('/board/' + it.id)}
                        aria-current={active ? 'true' : undefined}
                      >
                        <span className={'spine ' + severityTone(it.severity)} aria-hidden="true" />
                        <span className="card-main">
                          <span className="card-top">
                            <span className="card-station">{it.station}</span>
                            <span className="card-sev num">{it.severity.toFixed(1)}σ</span>
                          </span>
                          <span className="card-sensor">
                            {it.label}
                            {it.housekeeping && <Badge tone="accent">hk</Badge>}
                            {it.confirmed_by_analyst && <Badge tone="ok">confirmed</Badge>}
                          </span>
                          <span className="card-meta num">
                            drift {it.drift_per_day.toFixed(3)}/d · trust{' '}
                            {it.trust.toFixed(2)} · open {it.days_since_onset.toFixed(1)}d
                          </span>
                          <span className={'card-action ' + (it.action === 'DISPATCH' ? 'bad' : 'sus')}>
                            {it.action}
                          </span>
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </aside>

            <section className="board-detail">
              {data.action_note && (
                <Callout tone="neutral" title="Why every item carries the same action">
                  {data.action_note}
                </Callout>
              )}
              <Callout tone="sus" title="How to read the precision figure">
                {data.scorecard.caveat}
              </Callout>
              {selected ? (
                <ItemDetail id={selected} />
              ) : (
                <p className="muted">Select a sensor to see the evidence behind it.</p>
              )}
            </section>
          </>
        )}
      </Async>
    </div>
  )
}

function Score({ v, k }: { v: number | string; k: string }) {
  return (
    <div className="score">
      <span className="score-v num">{v}</span>
      <span className="score-k">{k}</span>
    </div>
  )
}
