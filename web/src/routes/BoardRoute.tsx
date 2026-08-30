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
import { useQueue, useSimMap } from '../api/queries'
import { BAND, type Band, type SimStation } from '../api/mapTypes'
import { Link } from 'react-router-dom'
import { siteInfo } from '../api/sites'
import { Async } from '../components/Async'
import { Badge, severityTone } from '../components/Badge'
import { Callout } from '../components/Callout'
import { ItemDetail } from '../components/ItemDetail'

export function BoardRoute() {
  const selected = useParams()['*'] || ''
  const navigate = useNavigate()
  const q = useQueue()
  const sim = useSimMap()
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

              {/* THE SIMULATED NETWORK BELONGS ON THE BOARD TOO.
                *
                * The board only ever showed the ARM instruments -- nine masts
                * in the US with faults a human analyst confirmed. That is the
                * evidence half of the product. The other half is the 344
                * Indian locations, and it existed only on the map, so this
                * page silently claimed the whole system watched nine sensors.
                *
                * It is kept SEPARATE rather than ranked in with the ARM items.
                * Those are confirmed faults on real hardware; these are
                * injected faults on generated readings, and merging them into
                * one queue would put a synthetic incident in front of a
                * technician as if it were work. */}
              <SimSummary sim={sim.data} />

              <div className="belowhead" style={{ marginTop: 18 }}>
                ARM instruments · analyst-confirmed
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
                            {/* The place, not the datastream code. Nobody can be
                                dispatched to "sgpmetE37". */}
                            <span className="card-station">
                              {siteInfo(it.station)?.place ?? it.station}
                            </span>
                            <span className="card-sev num">{it.severity.toFixed(1)}σ</span>
                          </span>
                          <span className="card-sensor">
                            {it.label}
                            {it.housekeeping && <Badge tone="accent">hk</Badge>}
                            {it.confirmed_by_analyst && <Badge tone="ok">confirmed</Badge>}
                          </span>
                          <span className="card-meta num">
                            {it.station} · drift {it.drift_per_day.toFixed(3)}/d · trust{' '}
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

/** The simulated Indian network, summarised: how many stations ever went bad
 *  over the month, and the worst of them.
 *
 *  Worst-over-the-window rather than at one hour, because the board has no
 *  clock and "flagged right now" would depend on an hour nobody chose. */
function SimSummary({ sim }: { sim: ReturnType<typeof useSimMap>['data'] }) {
  if (!sim) return null

  const worst = (st: SimStation): { band: Band; hours: number } => {
    let band: Band = 'NODATA'
    let hours = 0
    for (const c of st.g) {
      const b = BAND[c]
      if (b === 'FAULT' || b === 'WATCH') hours++
      if (b === 'FAULT') band = 'FAULT'
      else if (b === 'WATCH' && band !== 'FAULT') band = 'WATCH'
      else if (b === 'OK' && band === 'NODATA') band = 'OK'
    }
    return { band, hours }
  }

  const rows = sim.stations.map((s) => ({ s, ...worst(s) }))
    .filter((r) => r.band === 'FAULT' || r.band === 'WATCH')
    .sort((a, b) => b.hours - a.hours)
  const faults = rows.filter((r) => r.band === 'FAULT').length

  return (
    <section className="simsum">
      <div className="belowhead">Simulated network · India</div>
      <p className="muted small">
        {rows.length} of {sim.stations.length} stations were flagged at some
        point over the 30 days; {faults} reached fault. Injected faults on
        generated readings — not work orders.
      </p>
      <ul className="simlist">
        {rows.slice(0, 8).map((r) => (
          <li key={r.s.id}>
            <span className={'spine ' + (r.band === 'FAULT' ? 'bad' : 'warn')} aria-hidden="true" />
            <span className="simname">{r.s.name}</span>
            <span className="mono muted">{r.s.state}</span>
            <span className="mono num">{r.hours} h</span>
          </li>
        ))}
      </ul>
      <Link to="/network" className="btn ghost tiny">Open the network map</Link>
    </section>
  )
}
