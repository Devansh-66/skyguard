/* The live feed: readings arriving, and what the server made of each one.
 *
 * WHY THIS PANEL EXISTS AT ALL
 *
 * The WebSocket and the ingest path have been working for a while with nothing
 * on screen showing it, which meant the real-time half of this system was
 * invisible to anyone who did not open a socket by hand. A capability nobody
 * can see is, for every practical purpose, a capability that is not there.
 *
 * WHAT IS AND IS NOT LIVE HERE
 *
 * The readings are simulated and the PIPELINE is real. Each row below was
 * posted to /api/ingest, screened against the WMO rails, and pushed back over
 * the socket in that request. An ESP32 will post to the same endpoint and land
 * in the same list, which is the only claim this panel makes.
 */
import { useCallback, useState } from 'react'
import { liveCommand, resetTrace, useLive } from '../lib/useLive'

/** A live strip chart: the pen draws as readings arrive.
 *
 * WHY IT WATCHES ONE STATION
 *
 * The feeder can walk the whole network, and for a chart that is useless: with
 * 344 stations in rotation any single one is heard from once every 344
 * readings, so a "live graph" would be one dot a minute with 343 other
 * stations' values interleaved. A time series needs a subject. Streaming one
 * station is what makes the trace a trace -- and it is also what an ESP32 on a
 * bench actually is: one station, reporting.
 */
function Strip({ label, unit, values }: {
  label: string; unit: string; values: number[]
}) {
  const W = 420, H = 52, P = 3
  const lo = values.length ? Math.min(...values) : 0
  const hi = values.length ? Math.max(...values) : 1
  const pad = (hi - lo) * 0.15 || 0.5
  const y = (v: number) => P + ((hi + pad - v) / ((hi + pad) - (lo - pad))) * (H - 2 * P)
  const x = (i: number) => (values.length < 2 ? P
    : P + (i / (values.length - 1)) * (W - 2 * P))
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
  const last = values.length ? values[values.length - 1] : null

  return (
    <div className="strip">
      <div className="strip-head">
        <span className="strip-label">{label}</span>
        <span className="mono strip-now">
          {last == null ? '—' : `${last.toFixed(1)} ${unit}`}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="strip-svg" role="img"
           aria-label={`${label}, last ${values.length} readings`}>
        <rect width={W} height={H} className="chan-stock" />
        <line x1={0} x2={W} y1={H / 2} y2={H / 2} className="chan-rule" />
        {values.length > 1 && <path d={d} className="chan-pen" />}
        {last != null && values.length > 0 && (
          <circle cx={x(values.length - 1)} cy={y(last)} r={2.5} className="chan-nib" />
        )}
      </svg>
    </div>
  )
}

export function LiveFeed({ apiBase = '' }: { apiBase?: string }) {
  const live = useLive(apiBase)
  const [error, setError] = useState<string | null>(null)

  const cmd = useCallback(async (path: string) => {
    try { await liveCommand(apiBase, path); setError(null) }
    catch (e) { setError(String(e)) }
  }, [apiBase])

  const { status, rows, trace, running, fault, silent, grade } = live

  return (
    <div className="live">
      <div className="live-bar">
        <span className={'live-dot ' + status} aria-hidden="true" />
        <span className="mono live-status">
          {status === 'open' ? 'connected' : status}
        </span>
        <button type="button" className="btn ghost tiny"
                onClick={() => cmd(running ? '/api/live/stop'
                  : '/api/live/replay?per_second=2')}>
          {running ? 'Stop the node' : 'Start the node'}
        </button>

        {/* BREAK IT WHILE SOMEBODY IS WATCHING.
            The fault vocabulary is the injector's, not one invented for a
            demo: showing a fault this system was never tested against would be
            theatre. It changes the reading only -- the detector is not told. */}
        <label className="mono faultsel">
          Fault
          <select value={fault} onChange={(e) => {
            resetTrace()
            cmd('/api/live/fault?kind=' + e.target.value)
          }}>
            <option value="none">none — healthy</option>
            <option value="drift">drift — 0.02 °C per reading</option>
            <option value="offset">offset — +4.5 °C step</option>
            <option value="stuck">stuck — value frozen</option>
            <option value="spike">spike — random jumps</option>
            <option value="dropout">dropout — stops reporting</option>
          </select>
        </label>

        <span className="mono muted live-count">
          {silent ? 'no reading' : rows.length ? `${rows.length} shown` : ''}
        </span>
      </div>

      {error && <p className="small muted">{error}</p>}

      {/* THE VERDICT, in the same words the map uses. The rails and the
          neighbour check answer different questions and both are shown: the
          rails catch a reading that cannot be true, this catches a reading
          that is merely wrong. */}
      <div className="live-verdict">
        {grade == null ? (
          <span className="muted small">No verdict yet — start the node.</span>
        ) : grade.band === 'learning' ? (
          <span className="muted small">
            Learning what normal looks like here · {grade.baseline}/{grade.baselineNeeded}
            {' '}readings. A station just switched on cannot be judged yet.
          </span>
        ) : (
          <>
            <span className={'verdict-chip ' + grade.band}>{grade.band}</span>
            <span className="mono small">
              {grade.z.toFixed(1)}σ from its neighbours · they expect{' '}
              {grade.expected.toFixed(1)} °C
            </span>
          </>
        )}
      </div>

      <div className="strips">
        <Strip label="Temperature" unit="°C" values={trace.temp} />
        <Strip label="Relative humidity" unit="%" values={trace.rh} />
        <Strip label="Pressure" unit="hPa" values={trace.pres} />
      </div>

      <div className="tabwrap live-box">
        <table className="alerttab">
          <thead>
            <tr>
              <th>Station</th><th>Temp</th><th>RH</th><th>Pressure</th>
              <th>Screened</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.t}-${i}`}>
                <td className="stncell">{r.station}</td>
                <td className="mono num">{r.temp.toFixed(1)} °C</td>
                <td className="mono num">{r.rh.toFixed(1)} %</td>
                <td className="mono num">{r.pres.toFixed(1)}</td>
                <td className="mono">
                  {r.server_flags && r.server_flags.length
                    ? <span className="flagged">{r.server_flags.join(', ')}</span>
                    : <span className="muted">passed</span>}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr><td colSpan={5} className="muted small">
                Nothing arriving. Start the node to post readings through the
                real ingest path.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="small muted">
        One station, reporting. Each row was posted to <code>/api/ingest</code>,
        screened against the WMO rails, and pushed back over a WebSocket in that
        request. An ESP32 posting to the same endpoint replaces this entirely —
        which is why it is a station on the map and not a panel beside it.
      </p>
    </div>
  )
}
