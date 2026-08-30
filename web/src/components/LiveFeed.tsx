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
import { useCallback, useEffect, useRef, useState } from 'react'

export interface LiveReading {
  type: string
  t: number
  station: string
  temp: number
  rh: number
  pres: number
  accepted?: boolean
  server_flags?: string[]
  source?: string
}

type Status = 'connecting' | 'open' | 'closed'

/** How many rows to keep on screen.
 *
 * This is a WINDOW, not a log. At four readings a second an unbounded list is
 * a memory leak with a scrollbar, and the archive already holds every reading
 * that matters -- /api/map/* is what history is for. */
const KEEP = 40

/** Points on the strip charts. Two minutes at two readings a second. */
const TRACE = 240

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

export function LiveFeed({ apiBase = '', station, stationName }: {
  apiBase?: string
  /** The station to stream. Without one the feeder walks the network and the
   *  strip charts stay empty, which is honest: there is no series to draw. */
  station?: string | null
  stationName?: string | null
}) {
  const [rows, setRows] = useState<LiveReading[]>([])
  /* The trace, kept separately from the table. The table is every reading that
   * arrives; this is one station's history, which is the only thing that can
   * be drawn as a line. */
  const [trace, setTrace] = useState<{ temp: number[]; rh: number[]; pres: number[] }>(
    { temp: [], rh: [], pres: [] })
  const [status, setStatus] = useState<Status>('connecting')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ws = useRef<WebSocket | null>(null)

  useEffect(() => {
    // ws:// against http, wss:// against https. Getting this wrong is the
    // classic "works locally, silently dead once deployed" bug: a page served
    // over TLS cannot open an insecure socket, and the browser blocks it
    // without a useful message.
    const base = apiBase || window.location.origin
    const url = base.replace(/^http/, 'ws') + '/api/live'
    let sock: WebSocket
    try {
      sock = new WebSocket(url)
    } catch (e) {
      setStatus('closed')
      setError(String(e))
      return
    }
    ws.current = sock
    sock.onopen = () => { setStatus('open'); setError(null) }
    sock.onclose = () => setStatus('closed')
    sock.onerror = () => setError('The socket closed. Is the API running?')
    sock.onmessage = (ev) => {
      try {
        const m = JSON.parse(ev.data)
        if (m.type === 'hello' && Array.isArray(m.backlog)) {
          setRows(m.backlog.filter((x: LiveReading) => x.type === 'reading')
            .slice(-KEEP).reverse())
          return
        }
        if (m.type === 'feeder') { setRunning(Boolean(m.running)); return }
        if (m.type !== 'reading') return
        // Newest first, and trimmed on every push rather than periodically:
        // the trim is what keeps this a window instead of a leak.
        setRows((prev) => [m, ...prev].slice(0, KEEP))
        // Only the watched station extends the trace. A chart mixing 344
        // stations' values into one line is not a measurement of anything.
        if (!station || m.station === stationName) {
          setTrace((p) => ({
            temp: [...p.temp, m.temp].slice(-TRACE),
            rh: [...p.rh, m.rh].slice(-TRACE),
            pres: [...p.pres, m.pres].slice(-TRACE),
          }))
        }
      } catch { /* a malformed frame is not worth a broken panel */ }
    }
    return () => sock.close()
  }, [apiBase, station, stationName])

  // A new subject starts a new trace. Carrying the old station's points into
  // the new station's line would draw a step that never happened.
  useEffect(() => { setTrace({ temp: [], rh: [], pres: [] }) }, [station])

  /* Set the running state from the RESPONSE, not only from the socket event.
   *
   * The server broadcasts {type:"feeder"} when a replay starts, and relying on
   * that alone left the button saying "Start the feed" while forty readings a
   * second poured in underneath it -- the feed was running and the only control
   * for it claimed otherwise. The socket event still arrives and still wins;
   * this just stops the button lying in the gap. */
  const send = useCallback(async (path: string, nowRunning: boolean) => {
    try {
      const r = await fetch((apiBase || '') + path, { method: 'POST' })
      if (!r.ok) { setError(`${path} returned ${r.status}`); return }
      setError(null)
      setRunning(nowRunning)
    } catch (e) {
      setError(String(e))
    }
  }, [apiBase])

  return (
    <div className="live">
      <div className="live-bar">
        <span className={'live-dot ' + status} aria-hidden="true" />
        <span className="mono live-status">
          {status === 'open' ? 'connected' : status}
        </span>
        <button type="button" className="btn ghost tiny"
                onClick={() => (running
                  ? send('/api/live/stop', false)
                  : send('/api/live/replay?per_second=2'
                      + (station ? `&station=${encodeURIComponent(station)}` : ''),
                    true))}>
          {running ? 'Stop the feed' : 'Start the feed'}
        </button>
        <span className="mono muted live-count">{rows.length ? `${rows.length} shown` : ''}</span>
      </div>

      {error && <p className="small muted">{error}</p>}

      {station ? (
        <div className="strips">
          <Strip label="Temperature" unit="°C" values={trace.temp} />
          <Strip label="Relative humidity" unit="%" values={trace.rh} />
          <Strip label="Pressure" unit="hPa" values={trace.pres} />
        </div>
      ) : (
        <p className="small muted">
          Select a station above and the feed will stream that one, drawing its
          three channels as each reading arrives. Without a subject the feeder
          walks all 344 and there is no series to draw.
        </p>
      )}

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
              <tr key={`${r.t}-${r.station}-${i}`}>
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
                Nothing arriving. Start the feed to post simulated readings
                through the real ingest path.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="small muted">
        The readings are simulated; the pipeline is not. Each row was posted to
        <code> /api/ingest</code>, screened against the WMO rails, and pushed
        back over a WebSocket in that request. An ESP32 will post to the same
        endpoint and appear in the same list.
      </p>
    </div>
  )
}
