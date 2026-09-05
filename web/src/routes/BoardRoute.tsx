/* The maintenance board: what to do, where, and how soon.
 *
 * WHO THIS SCREEN IS FOR
 *
 * A maintenance planner and the technician they dispatch. Not the person
 * tuning the detector. An earlier version led every card with a sigma, a drift
 * rate and a trust posterior, which are the right numbers for judging the
 * ALGORITHM and useless for judging the JOB -- none of them says whether to
 * bring a spare probe or a multimeter.
 *
 * Every card answers three questions in this order: what is the job, how soon,
 * and where. The verdict comes from the three-agent panel in
 * api/orchestrator.py, which judges the simulated network and the live node
 * with one set of rules.
 *
 * THE ARM HALF IS GONE
 *
 * This board used to carry sixteen American masts above the Indian stations,
 * ranked by a different number, with a filter to switch between them and two
 * paragraphs explaining why the two halves could not be compared. All of that
 * was scaffolding around a corpus that is not what this project is for. One
 * network, one ranking, no filter, no explanation needed.
 */
import { useMemo } from 'react'
import { usePageTitle } from '../lib/title'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { useLiveStanding, useSimMap } from '../api/queries'
import { StationChannels } from '../components/StationChannels'
import { type Band, type SimMap, type SimStation } from '../api/mapTypes'
import { alertsFor } from '../lib/alerts'
import { Badge } from '@/components/ui/badge'
import { Callout } from '../components/Callout'
import { ActionCard, AgentVerdicts, CaseProgress } from '../components/AgentPanel'
import { ExplainMath } from '../components/ExplainMath'
import { cn } from '@/lib/cn'
import {
  type Assessment, type EvidenceIn, useTriage,
  ACTION_SHORT, PRIORITY_LABEL,
} from '../lib/triage'

const CH_LABEL = { temp: 'Temperature', rh: 'Relative humidity', pres: 'Pressure (MSL)' }

export function BoardRoute() {
  usePageTitle('Maintenance board')
  const selected = useParams()['*'] || ''
  const navigate = useNavigate()
  const sim = useSimMap()
  const node = useLiveStanding()

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
        neighbours_agree: node.data.band === 'ok',
        days_open: node.data.open_seconds
          ? node.data.open_seconds / 86400 : null,
      })
    }
    return out
  }, [sims, node.data])

  const tri = useTriage(evidence)
  const verdictOf = (id: string): Assessment | undefined =>
    tri.data?.assessments[id]

  const all = Object.values(tri.data?.assessments ?? {})
  const byP = (p: number) => all.filter((a) => a.priority === p).length

  const ordered = useMemo(
    () => [...sims].sort((a, b) =>
      (verdictOf(a.id)?.priority ?? 9) - (verdictOf(b.id)?.priority ?? 9)
      || Number(b.open) - Number(a.open)
      || b.hours - a.hours),
    [sims, tri.data],
  )
  const shown = ordered.slice(0, 40)
  const liveOpen = node.data && node.data.band !== 'learning'
                   && node.data.band !== 'ok'

  return (
    <div className="mx-auto grid max-w-[1600px] gap-6 px-5 py-6
                    lg:grid-cols-[minmax(340px,400px)_minmax(0,1fr)]">
      <aside className="flex min-w-0 flex-col">
        <header className="mb-4">
          <h1 className="text-2xl font-semibold tracking-tight">Maintenance board</h1>
          {/* One sentence saying what the screen is for. The previous version
              opened straight into a list and left the reader to infer it. */}
          <p className="mt-1 text-sm text-ink-2">
            Sensors that need a technician, worst first.
          </p>
          <div className="mt-4 grid grid-cols-3 gap-2">
            <PrioCount n={byP(1)} label="Today" tone="fault" />
            <PrioCount n={byP(2)} label="This week" tone="watch" />
            <PrioCount n={byP(3)} label="Next visit" tone="ok" />
          </div>
        </header>

        {liveOpen && node.data && (
          <>
            <GroupHead>Reporting now</GroupHead>
            <ul className="mb-4 flex flex-col gap-2">
              <WorkCard
                place={node.data.station.name}
                where={`${node.data.station.state} · ${node.data.station.elev} m`}
                sensor="Temperature"
                age={node.data.open_seconds
                  ? `open ${Math.round(node.data.open_seconds)}s` : 'just now'}
                a={verdictOf('live')}
                badge={<Badge tone="brand">live</Badge>}
                active={selected === 'live'}
                onPick={() => navigate('/board/live')}
              />
            </ul>
          </>
        )}

        <GroupHead>
          {sims.filter((i) => i.open).length} open ·{' '}
          {sims.length - sims.filter((i) => i.open).length} awaiting check
        </GroupHead>
        {!sim.data ? (
          <p className="text-sm text-ink-3">Loading the network…</p>
        ) : !sims.length ? (
          <p className="text-sm text-ink-3">Nothing is flagged. Nobody needs dispatching.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {shown.map((it) => (
              <WorkCard
                key={it.id}
                place={it.s.name}
                where={`${it.s.state} · ${it.s.elev} m`}
                sensor={CH_LABEL[it.ch]}
                age={it.open
                  ? `wrong for ${Math.max(1, Math.round(it.openDays))} d`
                  : 'cleared, awaiting check'}
                a={verdictOf(it.id)}
                active={it.id === selected}
                onPick={() => navigate('/board/' + it.id)}
              />
            ))}
          </ul>
        )}
        {sims.length > shown.length && (
          <p className="px-1 py-3 text-xs text-ink-3">
            {shown.length} of {sims.length} shown. The rest are on the map.
          </p>
        )}
      </aside>

      <section className="min-w-0">
        {selected === 'live' ? (
          <LiveDetail a={verdictOf('live')} />
        ) : selected.startsWith('sim:') ? (
          <SimDetail id={selected} sim={sim.data} a={verdictOf(selected)} />
        ) : (
          <p className="rounded-[--radius-lg] border border-dashed border-rule
                        p-10 text-center text-ink-3">
            Select a sensor to see what needs doing.
          </p>
        )}
      </section>
    </div>
  )
}

/* THE THREE NUMBERS A PLANNER SCHEDULES AGAINST.
 *
 * Big enough to read across a room, because this is the first thing anyone
 * looks at and the previous version set it at 20px in a row of grey labels. */
const TONE = {
  fault: 'text-fault',
  watch: 'text-watch',
  ok: 'text-ok',
} as const

function PrioCount({ n, label, tone }: {
  n: number; label: string; tone: keyof typeof TONE
}) {
  return (
    <div className="rounded-[--radius-md] border border-rule bg-surface px-3 py-2.5">
      <span className={cn('tnum block text-3xl font-semibold leading-none', TONE[tone])}>
        {n}
      </span>
      <span className="mt-1.5 block font-mono text-[10px] uppercase tracking-widest text-ink-3">
        {label}
      </span>
    </div>
  )
}


function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
      {children}
    </h3>
  )
}

function GroupHead({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-2 mt-4 font-mono text-[10px] uppercase tracking-widest text-ink-3">
      {children}
    </div>
  )
}

/* ONE CARD, EVERY SOURCE. A simulated station and the live node reach a
 * technician the same way, so they get the same card. */
function WorkCard({ place, where, sensor, age, a, badge, active, onPick }: {
  place: string
  where: string
  sensor: string
  age: string
  a: Assessment | undefined
  badge?: React.ReactNode
  active: boolean
  onPick: () => void
}) {
  const d = a?.decision
  const spine = d === 'critical' ? 'bg-fault' : d === 'warning' ? 'bg-watch'
              : d === 'normal' ? 'bg-ok' : 'bg-rule'
  const when = d === 'critical' ? 'text-fault' : d === 'warning' ? 'text-watch'
             : 'text-ink-3'
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        aria-current={active ? 'true' : undefined}
        className={cn(
          'group relative flex w-full gap-3 overflow-hidden rounded-[--radius-md]',
          'border bg-surface pr-3 text-left transition-colors',
          active ? 'border-brand ring-1 ring-brand' : 'border-rule hover:bg-sunk',
        )}
      >
        {/* The severity stripe. Encoding severity in FORM as well as colour is
            what lets someone scan the list without reading it. */}
        <span className={cn('w-1 shrink-0', spine)} aria-hidden="true" />
        <span className="flex min-w-0 flex-col gap-0.5 py-3">
          {/* THE JOB FIRST. A planner scans for the work, then finds the place;
              the old card led with the station name, which is the wrong way
              round for a queue. */}
          <span className="flex items-baseline justify-between gap-3">
            <span className="font-mono text-[11px] font-semibold uppercase tracking-widest">
              {a ? ACTION_SHORT[a.action] : '—'}
            </span>
            <span className={cn('font-mono text-[10px] font-semibold uppercase tracking-wider', when)}>
              {a ? PRIORITY_LABEL[a.priority] : ''}
            </span>
          </span>
          <span className="truncate text-[15px] font-semibold tracking-tight">{place}</span>
          <span className="flex flex-wrap items-center gap-1.5 text-sm text-ink-2">
            {sensor}
            {badge}
          </span>
          <span className="text-xs text-ink-3">{where}{age ? ' · ' + age : ''}</span>
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
  /** Days the current episode has been running. */
  openDays: number
  /** Share of the record with no observation at all, read from the grade
   *  string. An OBSERVABLE property -- '-' means nothing arrived -- not the
   *  injection label, which the panel is never shown. */
  gapFraction: number
}

export function simItems(sim: SimMap | undefined): SimItem[] {
  if (!sim) return []
  const stepMin = sim.step_minutes || 15
  const out: SimItem[] = []
  for (const st of sim.stations) {
    for (const ch of ['temp', 'rh', 'pres'] as const) {
      const eps = alertsFor(st, ch)
      if (!eps.length) continue
      const hours = eps.reduce((n, e) => n + e.hours, 0)
      const band: Band = eps.some((e) => e.band === 'FAULT') ? 'FAULT' : 'WATCH'
      const last = eps[eps.length - 1]
      // DAYS OF THE CURRENT EPISODE, IN REAL DAYS.
      //
      // Two bugs met here and produced "wrong for 34 d" on a 30-day record.
      // Summing every episode ever answered a different question than the
      // label asked; and `episode.hours` is a misnomer -- alerts.ts counts
      // characters of the grade string, and one character is one STEP, which
      // is fifteen minutes, not an hour. Both are fixed by taking the last
      // episode and converting through step_minutes.
      const openDays = last.hours * stepMin / (60 * 24)
      const g = ch === 'temp' ? st.gt : ch === 'rh' ? st.gh : st.gp
      let gaps = 0
      for (const c of g) if (c === '-') gaps++
      out.push({ id: `sim:${st.id}:${ch}`, s: st, ch, band, hours,
                 episodes: eps.length, open: last.to === null, from: last.from,
                 openDays, gapFraction: g.length ? gaps / g.length : 0 })
    }
  }
  return out
}

/** What the panel is allowed to see. Note what is NOT here: the injected
 *  fault. The grader never saw it and neither does the panel. */
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
    // openDays, not hours/24. `episode.hours` counts grade-string characters
    // and one character is a 15-minute STEP, so hours/24 reported 34 days on a
    // 30-day record -- and fed that to the panel, which repeated it back in the
    // verdict a technician reads. Fixed on the card label earlier; this was the
    // same bug one layer down, still telling the agent the wrong number.
    days_open: it.openDays,
    gap_fraction: it.gapFraction,
    evidence_n: 200,
  }
}

/** The live node, judged by the same panel as everything else. */
function LiveDetail({ a }: { a: Assessment | undefined }) {
  const node = useLiveStanding()
  if (!node.data) return <p className="text-ink-3">Waiting for the node…</p>
  const s = node.data.station
  return (
    <article className="flex flex-col gap-5">
      <header className="mb-5">
        <h2 className="text-2xl font-semibold tracking-tight">{s.name}</h2>
        <p className="mt-1 font-mono text-xs text-ink-3">
          Temperature · {s.state} · {s.elev} m · reporting now
        </p>
      </header>
      {a ? <ActionCard a={a} /> : <p className="text-sm text-ink-3">Asking the panel…</p>}
      <SectionLabel>Why the panel says so</SectionLabel>
      {a && <AgentVerdicts a={a} />}

      {/* THE ARITHMETIC, NOT JUST THE VERDICT.
        *
        * The panel says which agent decided. This says how the number it
        * decided on was reached: reading, minus the neighbours' median, over
        * the trailing spread, against the bands. Only rendered where the real
        * values exist -- a worked example with an invented figure in it is
        * worse than none. */}
      {node.data && node.data.expected != null && node.data.last != null && (
        <>
          <SectionLabel>How that number was reached</SectionLabel>
          <ExplainMath
            reading={node.data.last}
            neighbour={node.data.expected}
            z={node.data.z}
            sigma={node.data.z ? Math.abs((node.data.last - node.data.expected) / node.data.z) : null}
            unit="°C"
          />
        </>
      )}

      <SectionLabel>Case</SectionLabel>
      <CaseProgress at={2} />
      <p className="text-sm text-ink-3">
        This node posts through the same ingest endpoint an ESP32 would use, and
        is graded against its neighbours by the same bands as the map.{' '}
        <Link to="/network" className="text-brand underline underline-offset-2">
          Open it on the map
        </Link>.
      </p>
    </article>
  )
}

/** One simulated sensor: the job first, then the panel, then the evidence. */
function SimDetail({ id, sim, a }: {
  id: string; sim: SimMap | undefined; a: Assessment | undefined
}) {
  const [, stationId, ch] = id.split(':')
  const st = sim?.stations.find((x) => x.id === stationId)
  if (!sim || !st) return <p className="text-ink-3">Loading…</p>

  const it = simItems(sim).find((x) => x.id === id)
  const injected = st.fault
  const onThisChannel = injected && injected.channel === ch

  return (
    <article className="flex flex-col gap-5">
      <header className="mb-5">
        <h2 className="text-2xl font-semibold tracking-tight">{st.name}</h2>
        <p className="mt-1 font-mono text-xs text-ink-3">
          {CH_LABEL[ch as 'temp' | 'rh' | 'pres']} · {st.state} · {st.elev} m
        </p>
      </header>

      {a ? <ActionCard a={a} /> : <p className="text-sm text-ink-3">Asking the panel…</p>}

      <SectionLabel>Why the panel says so</SectionLabel>
      {a && <AgentVerdicts a={a} />}

      <SectionLabel>Case</SectionLabel>
      <CaseProgress at={it?.open ? 2 : 5} />

      <SectionLabel>The record</SectionLabel>
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
