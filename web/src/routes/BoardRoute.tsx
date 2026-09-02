/* The maintenance board: what to do, where, and how soon.
 *
 * WHO THIS SCREEN IS FOR
 *
 * A maintenance planner and the technician they dispatch. Not the person
 * tuning the detector. The previous version led every card with a sigma, a
 * drift rate and a trust posterior, which are the right numbers for judging
 * the ALGORITHM and useless for judging the JOB -- none of them says whether
 * to bring a spare probe or a multimeter. Those numbers still exist, one click
 * away in the detail pane, for whoever wants to audit a call.
 *
 * Every card now answers three questions in this order: what is the job, how
 * soon, and where. The verdict comes from the three-agent panel in
 * api/orchestrator.py -- the same panel for ARM, the simulated network and the
 * live node, so the board cannot give two answers about the same evidence.
 *
 * WHY MASTER-DETAIL
 *
 * Triage is a sequence, not a destination. An operator works down the list
 * comparing one sensor against the last, and a full page navigation between
 * each throws away that comparison along with the scroll position.
 *
 * The selection lives in the URL (/board/<id>) so a specific instrument can be
 * linked to a colleague.
 */
import { useEffect, useMemo, useState } from 'react'
import { usePageTitle } from '../lib/title'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { useLiveStanding, useQueue, useSimMap } from '../api/queries'
import { StationChannels } from '../components/StationChannels'
import { type Band, type SimMap, type SimStation } from '../api/mapTypes'
import { alertsFor } from '../lib/alerts'
import { siteInfo } from '../api/sites'
import { Async } from '../components/Async'
import { Badge } from '../components/Badge'
import { Callout } from '../components/Callout'
import { ItemDetail } from '../components/ItemDetail'
import { ActionCard, AgentVerdicts, CaseProgress } from '../components/AgentPanel'
import {
  type Assessment, type EvidenceIn, useTriage,
  ACTION_SHORT, PRIORITY_LABEL, decisionTone,
} from '../lib/triage'

const CH_LABEL = { temp: 'Temperature', rh: 'Relative humidity', pres: 'Pressure (MSL)' }

export function BoardRoute() {
  usePageTitle('Maintenance board')
  const selected = useParams()['*'] || ''
  const navigate = useNavigate()
  const q = useQueue()
  const sim = useSimMap()
  const node = useLiveStanding()
  const [show, setShow] = useState<'all' | 'arm' | 'india'>('all')

  const sims = useMemo(() => simItems(sim.data), [sim.data])

  /* One request for the whole board. The panel lives on the server; this
   * screen only collects what it is allowed to see and asks. */
  const evidence = useMemo<EvidenceIn[]>(() => {
    const out: EvidenceIn[] = sims.map(simEvidence)
    if (node.data && node.data.band !== 'learning') {
      out.push({
        id: 'live', source: 'live', sensor: 'temp', label: 'Temperature',
        band: node.data.band,
        bias_sigma: node.data.z,
        evidence_n: node.data.readings ?? null,
        neighbours_agree: node.data.band === 'ok' ? true : false,
        days_open: node.data.open_seconds
          ? node.data.open_seconds / 86400 : null,
      })
    }
    return out
  }, [sims, node.data])

  const tri = useTriage(evidence)
  const verdictOf = (id: string): Assessment | undefined =>
    tri.data?.assessments[id]

  const items = q.data?.items
  useEffect(() => {
    if (!selected && items && items.length) {
      navigate('/board/' + items[0].id, { replace: true })
    }
  }, [selected, items, navigate])

  return (
    <div className="board">
      <Async query={q}>
        {(data) => {
          // Counts a planner actually schedules against.
          const all: Assessment[] = [
            ...data.items.map((i) => i.assessment).filter(Boolean) as Assessment[],
            ...Object.values(tri.data?.assessments ?? {}),
          ]
          const byP = (p: number) => all.filter((a) => a.priority === p).length

          return (
          <>
            <aside className="board-list">
              <header className="board-head">
                <h1>Maintenance board</h1>
                <div className="prio-row">
                  <PrioCount n={byP(1)} label="Today" tone="bad" />
                  <PrioCount n={byP(2)} label="This week" tone="sus" />
                  <PrioCount n={byP(3)} label="Next visit" tone="ok" />
                </div>
              </header>

              <label className="board-filter">
                Show
                <select value={show} onChange={(e) => setShow(e.target.value as never)}>
                  <option value="all">Both networks</option>
                  <option value="india">Simulated — India</option>
                  <option value="arm">ARM — analyst-confirmed</option>
                </select>
              </label>

              {node.data && node.data.band !== 'learning' && node.data.band !== 'ok' && (
                <>
                  <div className="group-head">Reporting now</div>
                  <ul className="cards">
                    <WorkCard
                      id="live"
                      place={node.data.station.name}
                      where={`${node.data.station.state} · ${node.data.station.elev} m`}
                      sensor="Temperature"
                      age={node.data.open_seconds
                        ? `open ${Math.round(node.data.open_seconds)}s` : 'just now'}
                      a={verdictOf('live')}
                      badge={<Badge tone="accent">live</Badge>}
                      active={selected === 'live'}
                      onPick={() => navigate('/board/live')}
                    />
                  </ul>
                </>
              )}

              {show !== 'india' && (<>
                <div className="group-head">ARM instruments · {data.items.length}</div>
                <ul className="cards">
                  {[...data.items]
                    .sort((a, b) => (a.assessment?.priority ?? 9)
                                  - (b.assessment?.priority ?? 9))
                    .map((it) => (
                      <WorkCard
                        key={it.id}
                        id={it.id}
                        place={siteInfo(it.station)?.place ?? it.station}
                        where={siteInfo(it.station)?.region ?? it.station}
                        sensor={it.label}
                        age={it.days_since_onset != null
                          ? `wrong for ${it.days_since_onset.toFixed(0)} d` : ''}
                        a={it.assessment}
                        badge={it.confirmed_by_analyst
                          ? <Badge tone="ok">confirmed</Badge> : null}
                        active={it.id === selected}
                        onPick={() => navigate('/board/' + it.id)}
                      />
                    ))}
                </ul>
              </>)}

              {show !== 'arm' && (
                <SimItems items={sims} selected={selected} verdictOf={verdictOf}
                          onPick={(id) => navigate('/board/' + id)} />
              )}
            </aside>

            <section className="board-detail">
              {selected.startsWith('sim:') ? (
                <SimDetail id={selected} sim={sim.data} a={verdictOf(selected)} />
              ) : selected ? (
                <ItemDetail id={selected} />
              ) : (
                <p className="muted">Select a sensor to see what needs doing.</p>
              )}
            </section>
          </>
          )
        }}
      </Async>
    </div>
  )
}

function PrioCount({ n, label, tone }: { n: number; label: string; tone: string }) {
  return (
    <div className={'prio ' + tone}>
      <span className="prio-n num">{n}</span>
      <span className="prio-k">{label}</span>
    </div>
  )
}

/* ONE CARD, EVERY SOURCE.
 *
 * ARM sensors, simulated stations and the live node all reach a technician the
 * same way, so they get the same card. The differences between the corpora are
 * real but they are a property of the EVIDENCE, not of the job, and they live
 * in the detail pane. */
function WorkCard({ id, place, where, sensor, age, a, badge, active, onPick }: {
  id: string
  place: string
  where: string
  sensor: string
  age: string
  a: Assessment | undefined
  badge?: React.ReactNode
  active: boolean
  onPick: () => void
}) {
  const tone = a ? decisionTone(a.decision) : 'muted'
  return (
    <li>
      <button type="button" className={'card' + (active ? ' active' : '')}
              onClick={onPick} aria-current={active ? 'true' : undefined}
              data-id={id}>
        <span className={'spine ' + tone} aria-hidden="true" />
        <span className="card-main">
          <span className="card-top">
            <span className="card-do">
              {a ? ACTION_SHORT[a.action] : '—'}
            </span>
            <span className={'card-when ' + tone}>
              {a ? PRIORITY_LABEL[a.priority] : ''}
            </span>
          </span>
          <span className="card-station">{place}</span>
          <span className="card-sensor">
            {sensor}
            {badge}
          </span>
          <span className="card-meta">{where}{age ? ' · ' + age : ''}</span>
        </span>
      </button>
    </li>
  )
}

/* ---------------------------------------------- the simulated network */

type SimItem = {
  id: string
  s: SimStation
  ch: 'temp' | 'rh' | 'pres'
  band: Band
  hours: number
  episodes: number
  open: boolean
  from: number
  /** Share of the record with no observation at all, read from the grade
   *  string. This is an OBSERVABLE property -- '-' means nothing arrived --
   *  not the injection label, which the panel is never shown. */
  gapFraction: number
}

export function simItems(sim: SimMap | undefined): SimItem[] {
  if (!sim) return []
  const out: SimItem[] = []
  for (const st of sim.stations) {
    for (const ch of ['temp', 'rh', 'pres'] as const) {
      const eps = alertsFor(st, ch)
      if (!eps.length) continue
      const hours = eps.reduce((n, e) => n + e.hours, 0)
      const band: Band = eps.some((e) => e.band === 'FAULT') ? 'FAULT' : 'WATCH'
      const last = eps[eps.length - 1]
      const g = ch === 'temp' ? st.gt : ch === 'rh' ? st.gh : st.gp
      let gaps = 0
      for (const c of g) if (c === '-') gaps++
      out.push({ id: `sim:${st.id}:${ch}`, s: st, ch, band, hours,
                 episodes: eps.length, open: last.to === null, from: last.from,
                 gapFraction: g.length ? gaps / g.length : 0 })
    }
  }
  return out.sort((a, b) =>
    Number(b.open) - Number(a.open)
    || (b.band === 'FAULT' ? 1 : 0) - (a.band === 'FAULT' ? 1 : 0)
    || b.hours - a.hours)
}

/** What the panel is allowed to see about a simulated sensor. Note what is
 *  NOT here: the injected fault. The grader never saw it and neither does the
 *  panel; it appears only in the detail pane, beside the verdict, so a reader
 *  can mark our own homework. */
function simEvidence(it: SimItem): EvidenceIn {
  return {
    id: it.id,
    source: 'sim',
    sensor: it.ch,
    label: CH_LABEL[it.ch],
    band: it.band === 'FAULT' ? 'fault' : 'watch',
    // A flagged station is by definition one its neighbours disagree with:
    // that disagreement is what the grade was computed from.
    neighbours_agree: false,
    episodes: it.episodes,
    days_open: it.hours / 24,
    gap_fraction: it.gapFraction,
    evidence_n: 200,
  }
}

function SimItems({ items, selected, verdictOf, onPick }: {
  items: SimItem[]
  selected: string
  verdictOf: (id: string) => Assessment | undefined
  onPick: (id: string) => void
}) {
  if (!items.length) return null
  const shown = [...items]
    .sort((a, b) => (verdictOf(a.id)?.priority ?? 9) - (verdictOf(b.id)?.priority ?? 9))
    .slice(0, 40)
  return (
    <>
      <div className="group-head">
        Simulated network · {items.filter((i) => i.open).length} open
      </div>
      <ul className="cards">
        {shown.map((it) => (
          <WorkCard
            key={it.id}
            id={it.id}
            place={it.s.name}
            where={`${it.s.state} · ${it.s.elev} m`}
            sensor={CH_LABEL[it.ch]}
            age={it.open ? `wrong for ${Math.round(it.hours / 24)} d` : 'cleared'}
            a={verdictOf(it.id)}
            active={it.id === selected}
            onPick={() => onPick(it.id)}
          />
        ))}
      </ul>
      {items.length > shown.length && (
        <p className="muted small" style={{ padding: '8px 2px' }}>
          {shown.length} of {items.length} shown. The rest are on the map.
        </p>
      )}
    </>
  )
}

/** One simulated sensor: the job first, then the panel, then the evidence. */
function SimDetail({ id, sim, a }: {
  id: string; sim: SimMap | undefined; a: Assessment | undefined
}) {
  const [, stationId, ch] = id.split(':')
  const st = sim?.stations.find((x) => x.id === stationId)
  if (!sim || !st) return <p className="muted">Loading…</p>

  const it = simItems(sim).find((x) => x.id === id)
  const injected = st.fault
  const onThisChannel = injected && injected.channel === ch

  return (
    <article className="simdetail">
      <header className="stnhead">
        <h2>{st.name}</h2>
        <span className="mono muted">
          {CH_LABEL[ch as 'temp' | 'rh' | 'pres']} · {st.state} · {st.elev} m
        </span>
      </header>

      {a && <ActionCard a={a} />}

      <div className="belowhead">Why the panel says so</div>
      {a ? <AgentVerdicts a={a} />
         : <p className="muted small">Asking the panel…</p>}

      <div className="belowhead">Case</div>
      <CaseProgress at={it?.open ? 2 : 5} />

      <div className="belowhead">The record</div>
      <StationChannels sim={sim} s={st} hour={0} />

      {/* Marking our own homework, kept last and clearly separated: the panel
          never saw any of this. */}
      <Callout tone={injected && onThisChannel ? 'ok' : 'sus'}
               title="Checking the verdict against what was injected">
        {!injected
          ? 'Nothing was injected into this station, so every flagged hour here '
            + 'is a false alarm.'
          : onThisChannel
            ? `A ${injected.kind} was injected on this channel from hour `
              + `${injected.onset_hour}.`
            : `A ${injected.kind} was injected on ${injected.channel}, not this `
              + 'channel.'}
        {' '}<Link to="/network">Open on the map</Link>.
      </Callout>
    </article>
  )
}
