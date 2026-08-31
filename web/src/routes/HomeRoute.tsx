/* The front sheet.
 *
 * WHAT WAS WRONG WITH THE ONE BEFORE
 *
 * It opened with "STATIONS 9" and a chart of a humidity probe in Waukomis,
 * Oklahoma. Nine is the ARM validation corpus, and Oklahoma is where it stands.
 * For an entry to the Ministry of Earth Sciences that is not a small framing
 * error -- the first screen said the system watches nine American instruments,
 * when it watches 344 Indian locations and a node reporting now.
 *
 * ARM is still how the detector was validated and that is said plainly further
 * down, in a sentence, where it belongs. It is evidence, not the subject.
 *
 * WHAT THIS PAGE IS FOR
 *
 * Three things, in this order: what the system is, whether it works, and where
 * to go next. Everything on it is a number this repository can produce, and
 * the ones that are unflattering are here too -- a landing page that only
 * carries good news is a landing page nobody should believe.
 */
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import { useLiveStation } from '../api/queries'
import { usePageTitle } from '../lib/title'
import { useLive } from '../lib/useLive'

interface Summary {
  network: {
    simulated_stations: number
    states: number
    injected_faults: number
    days: number
    step_minutes: number
  }
  parameters: string[]
  measured: {
    recall: number
    precision: number
    recall_excluding_dropouts: number
    alert_episodes: number
    stations_alerting: number
    note: string
  }
  validation: { corpus: string; why: string }
}

function useSummary() {
  return useQuery({
    queryKey: ['summary'] as const,
    queryFn: ({ signal }) => get<Summary>('/api/summary', signal),
    staleTime: Infinity,
  })
}

export function HomeRoute() {
  usePageTitle(undefined)
  const sum = useSummary()
  const node = useLiveStation()
  const live = useLive(import.meta.env.VITE_API_BASE ?? '')
  const n = sum.data?.network
  const m = sum.data?.measured

  return (
    <div className="sheet home">
      <header className="hero">
        <p className="engraved">Ministry of Earth Sciences · India Meteorological Department · PS26073</p>
        <h1 className="hero-title">
          A broken weather station does not stop.
          <em> It keeps reporting.</em>
        </h1>
        <p className="hero-lede">
          A probe that fails slowly reads a little wrong, then a little more, for
          weeks. No threshold catches it, because at no single moment is any
          number implausible. The failure is not the reading — it is the drift,
          and drift is only visible against something that has not drifted.
        </p>
        <p className="hero-sub">
          SkyGuard finds it using temperature, pressure and relative humidity
          alone, by asking every station whether it still agrees with its
          neighbours.
        </p>

        <div className="hero-go">
          <Link to="/network" className="btn">Open the network</Link>
          <Link to="/board" className="btn ghost">Maintenance board</Link>
        </div>
      </header>

      {/* THE LIVE LINE. Not a decoration: it is the one claim on this page that
          proves itself while you read it, and it is the difference between a
          system that processes a stream and a system that replays a file. */}
      <section className="livestrip">
        <span className={'live-dot ' + live.status} aria-hidden="true" />
        <span className="mono">
          {live.latest && node.data
            ? <>
                <strong>{node.data.name}</strong> reporting from{' '}
                {node.data.state} — {live.latest.temp.toFixed(1)} °C ·{' '}
                {live.latest.rh.toFixed(1)} % · {live.latest.pres.toFixed(1)} hPa
              </>
            : node.data
              ? <>waiting for {node.data.name} to report…</>
              : <>the live node is not configured on this host</>}
        </span>
        {live.grade && live.grade.band !== 'learning' && (
          <span className={'verdict-chip ' + live.grade.band}>{live.grade.band}</span>
        )}
      </section>

      <section className="figures">
        <Figure v={n ? String(n.simulated_stations) : '—'}
                k="station locations"
                n="real IMD sites, across India" />
        <Figure v={n ? String(n.states) : '—'}
                k="states and territories"
                n="assigned by point-in-polygon" />
        <Figure v={n ? `${n.days} days` : '—'}
                k="of record"
                n={n ? `at ${n.step_minutes}-minute steps` : ''} />
        <Figure v="3" k="parameters" n="temperature, pressure, humidity" />
      </section>

      <section className="plate">
        <span className="engraved">How it decides</span>
        <div className="how">
          <article>
            <h3>It watches the instrument, not the weather</h3>
            <p>
              Every station is compared with its neighbours at the same moment.
              Weather is shared and cancels; a fault belongs to one instrument
              and does not. A station with fewer than three neighbours within
              250 km cannot be judged this way, and the interface says so rather
              than guessing.
            </p>
          </article>
          <article>
            <h3>A reading is screened before it is believed</h3>
            <p>
              Range, step and persistence limits come from{' '}
              <strong>WMO-No. 8</strong>, the Guide to Instruments and Methods
              of Observation, quoted with its citation. Those catch what cannot
              be true. Everything subtler — drift, a frozen value, a quiet
              offset — passes them, which is why the neighbour check exists.
            </p>
          </article>
          <article>
            <h3>An alert has a beginning and an end</h3>
            <p>
              A grade is recomputed every step with no memory, so thresholding
              it directly produced 2,484 flagged runs, half of them a single
              step long. Alerts are raised only after three consecutive flagged
              steps and cleared only after six clean ones — harder to close than
              to open, or a drifting sensor closes its own alert.
            </p>
          </article>
        </div>
      </section>

      <section className="plate">
        <span className="engraved">What it actually scores</span>
        <div className="scored">
          <div className="scored-nums">
            <Figure v={m ? `${Math.round(m.recall * 100)}%` : '—'}
                    k="recall" n="of injected faults found" />
            <Figure v={m ? `${Math.round(m.precision * 100)}%` : '—'}
                    k="precision" n="of alerting stations that had one" />
            <Figure v={m ? `${Math.round(m.recall_excluding_dropouts * 100)}%` : '—'}
                    k="recall, excluding dropouts"
                    n="a silent station has no residual to difference" />
          </div>
          <p className="scored-note">
            Measured against {n ? n.injected_faults : 28} faults injected into a
            network of {n ? n.simulated_stations : 344}, with the grader given
            the readings and nothing else. Both numbers belong together: the
            same detector reaches 86% recall at 15% precision if the bands are
            loosened, and a queue nobody trusts is worse than a shorter one.
          </p>
          <p className="scored-note muted">
            {m?.note}
          </p>
        </div>
      </section>

      <section className="plate">
        <span className="engraved">What is real, and what is not</span>
        <div className="tablewrap">
          <table className="honesty">
            <thead>
              <tr><th /><th>Locations</th><th>Readings</th><th>Fault labels</th></tr>
            </thead>
            <tbody>
              <tr>
                <td className="k">Simulated network</td>
                <td>real IMD sites</td>
                <td className="gen">generated</td>
                <td className="gen">injected, truth known</td>
              </tr>
              <tr>
                <td className="k">Live node</td>
                <td>real, Gandhinagar</td>
                <td className="gen">generated, arriving now</td>
                <td className="gen">injected on demand</td>
              </tr>
              <tr>
                <td className="k">WDQMS</td>
                <td>real IMD stations</td>
                <td>real departures</td>
                <td>none published</td>
              </tr>
              <tr>
                <td className="k">ARM validation</td>
                <td>real, United States</td>
                <td>real archive</td>
                <td>confirmed by analysts</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="scored-note muted">
          {sum.data?.validation.why} The readings on the map are generated and
          will stay generated through the finals; what is being demonstrated is
          the pipeline that judges them, which is the same pipeline an ESP32
          will post into.
        </p>
      </section>
    </div>
  )
}

function Figure({ v, k, n }: { v: string; k: string; n?: string }) {
  return (
    <div className="figure">
      <span className="figure-v num">{v}</span>
      <span className="figure-k">{k}</span>
      {n && <span className="figure-n">{n}</span>}
    </div>
  )
}
