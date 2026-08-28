/* The landing page.
 *
 * The hero is a full-bleed generated sky whose weather is the fleet's actual
 * condition -- `unrest` is the share of monitored sensors currently needing a
 * technician, so a healthy network is a clear dawn and a failing one clouds
 * over. Nothing on this page is placeholder copy or invented numbers: every
 * figure below comes from /api/queue, and if the API is down the counters say
 * so rather than showing zeros.
 */
import { Link } from 'react-router-dom'
import { useQueue } from '../api/queries'
import { SkyScene } from '../components/SkyScene'

export function HomeRoute() {
  const q = useQueue()
  const d = q.data

  // Unrest is bounded by the number of stations, not by the item count, so a
  // station with three bad channels cannot on its own overcast the whole sky.
  const unrest = d
    ? Math.min(1, new Set(d.items.map((i) => i.station)).size / Math.max(d.stations_scanned, 1))
    : 0

  return (
    <div className="home">
      <section className="hero">
        <SkyScene unrest={unrest} />
        <div className="hero-body">
          <p className="eyebrow">Automatic weather station integrity</p>
          <h1 className="hero-title">
            Every instrument drifts.
            <br />
            <em>Most networks find out too late.</em>
          </h1>
          <p className="hero-sub">
            SkyGuard watches temperature, pressure and humidity across a station
            network and tells you which sensor needs a person — before the data
            it is feeding into the forecast goes quietly wrong.
          </p>
          <div className="hero-actions">
            <Link to="/board" className="btn primary">Open the maintenance board</Link>
            <a href="/console/console.html" className="btn ghost">View the network map</a>
          </div>

          <dl className="hero-stats">
            <Stat v={d ? d.stations_scanned : null} k="stations under watch" />
            <Stat v={d ? d.items.length : null} k="sensors needing attention" />
            <Stat
              v={d && d.scorecard.recall != null ? Math.round(d.scorecard.recall * 100) + '%' : null}
              k="of analyst-named faults found"
            />
            <Stat v={d ? d.windows_scanned : null} k="fault windows replayed" />
          </dl>
          <p className="hero-note">
            {q.isError
              ? 'Live figures unavailable — the API is not responding.'
              : 'Live, from real one-minute observations. Fault labels come from human analysts and are never shown to the estimator.'}
          </p>
        </div>
        <div className="hero-weather">
          {d ? weatherLine(unrest) : 'reading the network…'}
        </div>
      </section>

      <section className="strip">
        <Point
          n="01"
          h="It watches the instrument, not the weather"
          b="An unusual reading is usually just unusual weather. A sensor that has moved
             away from its neighbours, from its own history and from its own daily rhythm
             at the same time is a sensor that has broken. SkyGuard separates the two."
        />
        <Point
          n="02"
          h="Six independent checks, and a rule about agreeing"
          b="Physics, neighbours, history, instrument signature, clock and housekeeping each
             judge separately. One check firing alone is a suspicion, not a finding — only
             physically impossible readings are allowed to raise an alarm on their own."
        />
        <Point
          n="03"
          h="It says what to do, and why"
          b="A slow, steady offset is corrected in software. A sensor whose logger voltage has
             moved with it is hardware, and a coefficient will not hold it. Each item on the
             board carries the reasoning that produced its action."
        />
      </section>
    </div>
  )
}

function Stat({ v, k }: { v: number | string | null; k: string }) {
  return (
    <div className="hstat">
      <dt className="hstat-v num">{v ?? '—'}</dt>
      <dd className="hstat-k">{k}</dd>
    </div>
  )
}

function Point({ n, h, b }: { n: string; h: string; b: string }) {
  return (
    <article className="point">
      <span className="point-n num">{n}</span>
      <h3>{h}</h3>
      <p>{b}</p>
    </article>
  )
}

/** The sky is a status display, so it is captioned. A visual signal nobody can
 *  decode is decoration; one sentence turns it into a reading. */
function weatherLine(unrest: number): string {
  if (unrest === 0) return 'clear — every station reporting within tolerance'
  if (unrest < 0.34) return 'scattered cloud — a few stations need attention'
  if (unrest < 0.67) return 'overcast — much of the network needs attention'
  return 'closing in — most of the network needs attention'
}
