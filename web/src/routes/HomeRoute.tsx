/* The front sheet.
 *
 * The hero is not an illustration. It is the worst fault currently on the
 * board, drawn as the recorder would have drawn it: the real trace, the real
 * in-specification band, the pen turning oxide red where the instrument left
 * tolerance, and the observing analyst's own note pinned in the margin. The
 * first thing a visitor sees is therefore a measurement, not a mood -- which is
 * the only defensible hero for a project whose whole argument is that claims
 * must be earned.
 *
 * It costs nothing extra: the series is already fetched by the same query the
 * board uses, so opening the board afterwards is instant.
 *
 * ROOM TO GROW
 *
 * The page is a stack of independent <section class="plate"> blocks. The
 * network map and the per-station insight plots drop in as further plates
 * without disturbing anything above them. Nothing is stubbed here in the
 * meantime: a section that says "coming soon" is worse than no section.
 */
import { Link } from 'react-router-dom'
import { useQueue, useQueueItem } from '../api/queries'
import { siteName } from '../api/sites'
import { Barograph } from '../components/Barograph'
import { extent, inSigma, include, stamp } from '../components/chart'

const BIAS_TOLERANCE = 2

export function HomeRoute() {
  const q = useQueue()
  const d = q.data
  const worst = d?.items[0]
  const detail = useQueueItem(worst?.id)
  const s = detail.data

  return (
    <div className="sheet">
      {/* ---------- nameplate ---------- */}
      <header className="masthead">
        <div>
          <h1 className="wordmark">SkyGuard</h1>
          <p className="masthead-sub">
            Automatic weather station integrity — temperature, pressure,
            relative humidity
          </p>
        </div>
        <dl className="nameplate">
          <NameplateRow k="Stations" v={d ? String(d.stations_scanned) : '—'} />
          <NameplateRow k="Records replayed" v={d ? String(d.windows_scanned) : '—'} />
        </dl>
      </header>

      {/* ---------- the hero plate: one real fault ---------- */}
      <section className="plate hero-plate">
        <div className="plate-head">
          <span className="engraved">Recorder trace · live from the board</span>
          <h2 className="plate-title">
            A broken sensor does not stop. <em>It keeps reporting.</em>
          </h2>
          <p className="plate-body">
            A probe that has failed slowly reads a little wrong, then a little
            more, for weeks. No threshold catches it, because at no single moment
            is any number implausible. The failure is not the reading — it is the
            drift, and drift is only visible against something that has not
            drifted.
          </p>
        </div>

        <div className="plate-figure">
          {s ? (
            <>
              <Barograph
                values={inSigma(s.series.bias, s.series.noise)}
                e={include(
                  extent(inSigma(s.series.bias, s.series.noise)),
                  -BIAS_TOLERANCE * 1.3,
                  BIAS_TOLERANCE * 1.3,
                )}
                faulty={s.series.faulty}
                threshold={BIAS_TOLERANCE}
                height={168}
                animate
                label={siteName(s.station) + ' · ' + s.label + ' · bias (σ)'}
                from={stamp(s.series.t[0])}
                to={stamp(s.series.t[s.series.t.length - 1])}
              />
              <aside className="margin-note">
                <span className="engraved">Observer's note</span>
                <p className="note-subject">{s.analyst_subject}</p>
                <p className="note-body">{s.analyst_note}</p>
                <p className="note-sig">
                  {s.station} · {s.window.dqr}
                  <br />
                  {stamp(s.window.start)} — {stamp(s.window.end)}
                </p>
              </aside>
            </>
          ) : (
            <p className="muted small plate-loading">
              {q.isError || detail.isError
                ? 'The recorder is not responding — the API is unavailable.'
                : 'Winding the drum…'}
            </p>
          )}
        </div>

        {s && (
          <p className="plate-caption small muted">
            Red is where this instrument left its ±{BIAS_TOLERANCE}σ tolerance.
            The shaded span is what a human analyst independently reported as
            faulty — shown for comparison, never used by the estimate. The pen
            lifts at gaps in the record.
          </p>
        )}
      </section>

      {/* ---------- the ledger ---------- */}
      <section className="ledger">
        <Cell
          v={d ? String(d.items.length) : null}
          k="sensors awaiting a technician"
          n="ranked by evidence, worst first"
        />
        <Cell
          v={d ? String(d.scorecard.analyst_named) : null}
          k="faults named by analysts"
          n="written by people who inspected the instruments"
        />
        <Cell
          v={d && d.scorecard.recall != null ? Math.round(d.scorecard.recall * 100) + '%' : null}
          k="of those we found"
          n="earned recall, not a tuned figure"
        />
        <Cell
          v={d ? String(d.stations_scanned) : null}
          k="stations under watch"
          n="real one-minute observations"
        />
      </section>

      {/* ---------- how ---------- */}
      <section className="plate notes">
        <div className="note">
          <span className="engraved">I</span>
          <h3>It watches the instrument, not the weather</h3>
          <p>
            An unusual reading is usually just unusual weather. A sensor that has
            moved away from its neighbours, from its own history and from its own
            daily rhythm at once has broken. SkyGuard separates the two.
          </p>
        </div>
        <div className="note">
          <span className="engraved">II</span>
          <h3>Six checks, and a rule about agreeing</h3>
          <p>
            Physics, neighbours, history, instrument signature, clock and
            housekeeping each judge separately. One firing alone is a suspicion,
            not a finding — only a physically impossible reading may raise an
            alarm by itself.
          </p>
        </div>
        <div className="note">
          <span className="engraved">III</span>
          <h3>It says what to do, and why</h3>
          <p>
            A slow steady offset is corrected in software. A sensor whose logger
            voltage moved with it is hardware, and no coefficient will hold it.
            Every item carries the reasoning that produced its action.
          </p>
        </div>
      </section>

      <section className="closing">
        <Link to="/board" className="btn">Open the maintenance board</Link>
        <Link to="/network" className="btn ghost">Network map</Link>
        <p className="small muted colophon">
          Detections run against real ARM one-minute observations. Fault labels
          are written by human analysts and are never shown to the estimator.
        </p>
      </section>
    </div>
  )
}

function NameplateRow({ k, v }: { k: string; v: string }) {
  return (
    <div className="np-row">
      <dt>{k}</dt>
      <dd className="num">{v}</dd>
    </div>
  )
}

/** null renders as an em dash, never as 0. A count of zero and a count that
 *  could not be obtained are different claims. */
function Cell({ v, k, n }: { v: string | null; k: string; n: string }) {
  return (
    <div className="cell">
      <span className="cell-v num">{v ?? '—'}</span>
      <span className="cell-k">{k}</span>
      <span className="cell-n">{n}</span>
    </div>
  )
}
