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
import { useEffect, useState } from 'react'
import { usePageTitle } from '../lib/title'
import { useNavigate, useParams } from 'react-router-dom'
import { Link } from 'react-router-dom'
import { useLiveStanding, useQueue, useSimMap } from '../api/queries'
import { StationChannels } from '../components/StationChannels'
import { type Band, type SimMap, type SimStation } from '../api/mapTypes'
import { alertsFor } from '../lib/alerts'
import { siteInfo } from '../api/sites'
import { Async } from '../components/Async'
import { Badge, severityTone } from '../components/Badge'
import { Callout } from '../components/Callout'
import { ItemDetail } from '../components/ItemDetail'

export function BoardRoute() {
  usePageTitle('Maintenance board')
  const selected = useParams()['*'] || ''
  const navigate = useNavigate()
  const q = useQueue()
  const sim = useSimMap()
  const node = useLiveStanding()
  /* WHICH HALF OF THE BOARD TO SHOW.
   *
   * The two groups rest on different evidence and rank by different numbers --
   * ARM by severity in sigma against faults a human confirmed, the simulated
   * network by duration against faults we injected. Both on screen at once is
   * right for a survey and wrong for working: scrolling past 16 American masts
   * to reach the Indian stations, every time, is the kind of friction that
   * makes people stop using a queue. */
  const [show, setShow] = useState<'all' | 'arm' | 'india'>('all')
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
                  {data.items.length + simItems(sim.data).length} sensors across{' '}
                  {data.stations_scanned + (sim.data?.stations.length ?? 0)} stations,
                  worst first within each group.
                </p>
              </header>

              <label className="board-filter">
                Show
                <select value={show} onChange={(e) => setShow(e.target.value as never)}>
                  <option value="all">Both networks</option>
                  <option value="india">Simulated — India</option>
                  <option value="arm">ARM — analyst-confirmed</option>
                </select>
              </label>

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

              {/* THE SIMULATED NETWORK IS ON THE BOARD, AS BOARD ITEMS.
                *
                * A first attempt put it in a summary panel beside the list with
                * a link to the map. That was not the board. The board is one
                * ranked list of SENSORS TO ACT ON, each with a card and a
                * detail pane behind it, and a network shown as a paragraph of
                * counts is a footnote, not something anyone can be dispatched
                * against. These use the same card, the same spine, the same
                * detail pane.
                *
                * They stay in their own group rather than interleaved, for one
                * concrete reason: the ARM items are ranked by severity in
                * sigma, and nothing in the simulated export carries a sigma.
                * Ranking them together would mean inventing a common number.
                * The group heading says which evidence each half rests on. */}
              {/* THE LIVE NODE, AT THE TOP, when it has something to say.
                *
                * It is a station like any other and it belongs in the queue
                * like any other -- a device that faults and appears nowhere a
                * technician looks is a device nobody will be sent to. It sits
                * above both groups because it is the only item on this board
                * that is happening NOW: everything below is a study of a
                * record that has already been written. */}
              {node.data && node.data.band !== 'learning' && node.data.band !== 'ok' && (
                <>
                  <div className="group-head">Live node · reporting now</div>
                  <ul className="cards">
                    <li>
                      <button type="button"
                              className={'card' + (selected === 'live' ? ' active' : '')}
                              onClick={() => navigate('/board/live')}>
                        <span className={'spine ' + (node.data.band === 'fault' ? 'bad' : 'sus')}
                              aria-hidden="true" />
                        <span className="card-main">
                          <span className="card-top">
                            <span className="card-station">{node.data.station.name}</span>
                            <span className="card-sev num">{node.data.z.toFixed(1)}σ</span>
                          </span>
                          <span className="card-sensor">
                            Temperature
                            <Badge tone="accent">live</Badge>
                          </span>
                          <span className="card-meta num">
                            {node.data.station.state} · {node.data.station.elev} m ·{' '}
                            {node.data.open_seconds
                              ? `open ${Math.round(node.data.open_seconds)}s`
                              : 'just now'}
                          </span>
                          <span className={'card-action '
                            + (node.data.band === 'fault' ? 'bad' : 'sus')}>
                            {node.data.band === 'fault' ? 'DISPATCH' : 'WATCH'}
                          </span>
                        </span>
                      </button>
                    </li>
                  </ul>
                </>
              )}

              {show !== 'india' && (<>
              <div className="group-head">
                ARM instruments · {data.items.length} · analyst-confirmed faults
              </div>
              <ul className="cards">
                {data.items.map((it) => {
                  const active = it.id === selected
                  return (
                    <li key={it.id}>
                      <button
                        type="button"
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
              </>)}

              {show !== 'arm' && (
                <SimItems sim={sim.data} selected={selected}
                          onPick={(id) => navigate('/board/' + id)} />
              )}

              {/* THESE TWO DESCRIBE THE CORPUS, NOT THE ITEM.
                *
                * They used to sit at the top of the detail pane, so every
                * sensor a reader opened repeated the same two paragraphs about
                * the dataset -- and pushed the charts, the only thing that
                * shows what actually happened, two thousand pixels down the
                * scroll. A caveat that is true of all sixteen items is a
                * property of the board and belongs on the board, once. */}
              <details className="corpus-note">
                <summary>About these figures</summary>
                {data.action_note && (
                  <>
                    <strong>Why every item says DISPATCH</strong>
                    <p>{data.action_note}</p>
                  </>
                )}
                <strong>How to read the precision figure</strong>
                <p>{data.scorecard.caveat}</p>
              </details>
            </aside>

            <section className="board-detail">
              {/* A card that opens nothing is not a board item, so the
                  simulated sensors get a detail pane too -- their own, because
                  the evidence is different in kind. An ARM item is backed by a
                  report a human wrote; a simulated one is backed by an
                  injection we performed, and the useful thing to show is what
                  we said against what was actually done. */}
              {selected.startsWith('sim:') ? (
                <SimDetail id={selected} sim={sim.data} />
              ) : selected ? (
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

/* THE SIMULATED NETWORK, AS BOARD ITEMS.
 *
 * One item is one (station, channel) -- the same unit as an ARM item, because
 * a technician is dispatched to a sensor and not to a site. A station whose
 * thermometer drifted is not a station whose barometer drifted.
 *
 * Ranked by HOURS FLAGGED, and the card says so rather than printing a sigma
 * it does not have. Hours is the honest severity here: the export carries
 * grades, not the distances behind them, and a fabricated sigma would sort the
 * list plausibly and mean nothing.
 */
type SimItem = {
  id: string
  s: SimStation
  ch: 'temp' | 'rh' | 'pres'
  band: Band
  hours: number
  episodes: number
  /** Still running at the end of the record, or closed by itself. */
  open: boolean
  /** Hour the most recent episode began. */
  from: number
}

const CH_LABEL = { temp: 'Temperature', rh: 'Relative humidity', pres: 'Pressure (MSL)' }

export function simItems(sim: SimMap | undefined): SimItem[] {
  if (!sim) return []
  const out: SimItem[] = []
  for (const st of sim.stations) {
    for (const ch of ['temp', 'rh', 'pres'] as const) {
      /* Episodes, not flagged hours. Counting hours put stations on this board
       * that had never been wrong for more than an hour at a time -- 2,484
       * runs across the network, half of them a single hour long. An item here
       * is meant to be a condition somebody drives out to look at. */
      const eps = alertsFor(st, ch)
      if (!eps.length) continue
      const hours = eps.reduce((n, e) => n + e.hours, 0)
      const band: Band = eps.some((e) => e.band === 'FAULT') ? 'FAULT' : 'WATCH'
      /* AN ALERT THAT CLEARED IS NOT THE SAME WORK AS ONE STILL RUNNING.
       * The board is a queue; something that fixed itself, or was a false
       * alarm that went away, must not sit in it looking like a job. It stays
       * on the board -- the record matters, and a station that alerts and
       * clears repeatedly is itself a finding -- but it is marked closed and
       * sorted below everything open. */
      const last = eps[eps.length - 1]
      out.push({ id: `sim:${st.id}:${ch}`, s: st, ch, band, hours,
                 episodes: eps.length, open: last.to === null, from: last.from })
    }
  }
  // Open work first, then by how long it has been wrong.
  return out.sort((a, b) =>
    Number(b.open) - Number(a.open)
    || (b.band === 'FAULT' ? 1 : 0) - (a.band === 'FAULT' ? 1 : 0)
    || b.hours - a.hours)
}

function SimItems({ sim, selected, onPick }: {
  sim: SimMap | undefined
  selected: string
  onPick: (id: string) => void
}) {
  const items = simItems(sim)
  if (!sim || !items.length) return null
  const shown = items.slice(0, 40)
  return (
    <>
      <div className="group-head">
        Simulated network, India · {items.filter((i) => i.open).length} open of {items.length}
      </div>
      <ul className="cards">
        {shown.map((it) => {
          const active = it.id === selected
          return (
            <li key={it.id}>
              <button type="button" className={'card' + (active ? ' active' : '')}
                      onClick={() => onPick(it.id)}
                      aria-current={active ? 'true' : undefined}>
                <span className={'spine ' + (it.band === 'FAULT' ? 'bad' : 'sus')}
                      aria-hidden="true" />
                <span className="card-main">
                  <span className="card-top">
                    <span className="card-station">{it.s.name}</span>
                    <span className="card-sev num">{it.hours} h</span>
                  </span>
                  <span className="card-sensor">
                    {CH_LABEL[it.ch]}
                    {it.s.fault && it.s.fault.channel === it.ch
                      && <Badge tone="ok">injected</Badge>}
                  </span>
                  <span className="card-meta num">
                    {it.s.state} · {it.s.elev} m · {it.episodes} episode{it.episodes > 1 ? 's' : ''}
                  </span>
                  <span className={'card-action ' + (!it.open ? 'done'
                    : it.band === 'FAULT' ? 'bad' : 'sus')}>
                    {!it.open ? 'CLEARED' : it.band === 'FAULT' ? 'DISPATCH' : 'WATCH'}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
      {items.length > shown.length && (
        <p className="muted small" style={{ padding: '8px 2px' }}>
          Showing the {shown.length} longest-running of {items.length}. The rest
          are on the network map.
        </p>
      )}
    </>
  )
}

/** One simulated sensor, with what was injected beside what we said. */
function SimDetail({ id, sim }: { id: string; sim: SimMap | undefined }) {
  const [, stationId, ch] = id.split(':')
  const st = sim?.stations.find((x) => x.id === stationId)
  if (!sim || !st) return <p className="muted">Loading the simulated network…</p>

  const it = simItems(sim).find((x) => x.id === id)
  const injected = st.fault
  // The one comparison worth making: did the thing we flagged correspond to
  // something that was actually done to this station, on this channel?
  const onThisChannel = injected && injected.channel === ch
  const verdict = !injected
    ? 'Nothing was injected into this station. Every flagged hour here is a '
      + 'false alarm.'
    : onThisChannel
      ? `A ${injected.kind} was injected on this channel from hour `
        + `${injected.onset_hour}. Flagged hours before that are false alarms.`
      : `A ${injected.kind} was injected into this station, but on `
        + `${injected.channel}, not this channel. Flags here are false alarms `
        + 'unless the fault crossed channels.'

  return (
    <article className="simdetail">
      <header className="stnhead">
        <h2>{st.name}</h2>
        <span className="mono muted">
          {st.state} · {st.elev} m ·{' '}
          {Math.abs(st.lat).toFixed(2)}{st.lat < 0 ? 'S' : 'N'}{' '}
          {Math.abs(st.lon).toFixed(2)}{st.lon < 0 ? 'W' : 'E'}
        </span>
      </header>

      <div className="fields">
        <Field k="channel" v={CH_LABEL[ch as 'temp' | 'rh' | 'pres']} />
        <Field k="hours flagged" v={String(it?.hours ?? 0)} />
        <Field k="status" v={it?.open ? 'open' : 'cleared'} />
        <Field k="episodes" v={String(it?.episodes ?? 0)} />
        <Field k="injected" v={injected ? `${injected.kind} on ${injected.channel}` : 'nothing'} />
      </div>

      <Callout tone={injected && onThisChannel ? 'ok' : 'sus'}
               title="What was done to this station">
        {verdict}
      </Callout>

      <div className="belowhead" style={{ marginTop: 18 }}>The record</div>
      <StationChannels sim={sim} s={st} hour={0} />

      <p className="muted small">
        Generated readings at a real IMD location. The grader never saw the
        injection; it is shown here only so the verdict can be checked against
        it. <Link to="/network">Open this station on the map</Link>.
      </p>
    </article>
  )
}

function Field({ k, v }: { k: string; v: string }) {
  return (
    <div className="field">
      <span className="field-k">{k}</span>
      <span className="field-v">{v}</span>
    </div>
  )
}
