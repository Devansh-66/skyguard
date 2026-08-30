/* One socket, many readers.
 *
 * The live panel and the map marker both need what is arriving, and the
 * obvious thing -- a WebSocket inside each component -- opens two connections
 * to the same broadcast, doubles the traffic, and gives the two views subtly
 * different ideas of "now" whenever one lags. So the connection lives here,
 * module-level, and components subscribe to it.
 *
 * It connects on the first subscriber and closes on the last, which matters on
 * a page where the live section can be folded away: a socket nobody is reading
 * should not stay open holding a server slot.
 */
import { useEffect, useState } from 'react'

export interface LiveReading {
  type: string
  t: number
  station: string
  temp: number
  rh: number
  pres: number
  accepted?: boolean
  server_flags?: string[]
}

/** The grade event as the server sends it: snake_case, and flat. */
interface GradeMessage {
  z: number
  band: Band
  expected: number
  baseline: number
  baseline_needed: number
}

export type Band = 'learning' | 'ok' | 'watch' | 'fault'

export interface LiveState {
  status: 'connecting' | 'open' | 'closed'
  /** Newest first. A window, not a log: the archive is /api/map/*. */
  rows: LiveReading[]
  /** One station's history, for drawing. */
  trace: { temp: number[]; rh: number[]; pres: number[] }
  /** The most recent reading, whatever station it came from. */
  latest: LiveReading | null
  running: boolean
  fault: string
  /** Set when the node reported nothing -- a dropout is silence, not a value. */
  silent: boolean
  /** The node's verdict against its neighbours, updated per reading. */
  grade: {
    z: number
    band: Band
    expected: number
    baseline: number
    baselineNeeded: number
  } | null
}

const KEEP = 40
const TRACE = 240

let sock: WebSocket | null = null
let base = ''
const subs = new Set<(s: LiveState) => void>()

let state: LiveState = {
  status: 'connecting', rows: [], trace: { temp: [], rh: [], pres: [] },
  latest: null, running: false, fault: 'none', silent: false, grade: null,
}

function push(next: Partial<LiveState>) {
  state = { ...state, ...next }
  subs.forEach((fn) => fn(state))
}

function connect() {
  if (sock) return
  // ws:// against http, wss:// against https. A page served over TLS cannot
  // open an insecure socket, and the browser refuses it without saying why --
  // the classic "works locally, silently dead once deployed".
  const origin = base || window.location.origin
  const url = origin.replace(/^http/, 'ws') + '/api/live'
  try {
    sock = new WebSocket(url)
  } catch {
    push({ status: 'closed' })
    return
  }
  sock.onopen = () => push({ status: 'open' })
  sock.onclose = () => { sock = null; push({ status: 'closed' }) }
  sock.onmessage = (ev) => {
    let m: LiveReading & { backlog?: LiveReading[]; running?: boolean; kind?: string }
    try { m = JSON.parse(ev.data) } catch { return }

    if (m.type === 'hello' && Array.isArray(m.backlog)) {
      const rows = m.backlog.filter((x) => x.type === 'reading').slice(-KEEP).reverse()
      push({ rows, latest: rows[0] ?? null })
      return
    }
    if (m.type === 'feeder') { push({ running: Boolean(m.running) }); return }
    if (m.type === 'fault') { push({ fault: String(m.kind ?? 'none') }); return }
    if (m.type === 'silence') { push({ silent: true }); return }
    if (m.type === 'grade') {
      const g = m as unknown as GradeMessage
      push({
        grade: {
          z: g.z, band: g.band, expected: g.expected,
          baseline: g.baseline, baselineNeeded: g.baseline_needed,
        },
      })
      return
    }
    if (m.type !== 'reading') return

    push({
      rows: [m, ...state.rows].slice(0, KEEP),
      latest: m,
      silent: false,
      trace: {
        temp: [...state.trace.temp, m.temp].slice(-TRACE),
        rh: [...state.trace.rh, m.rh].slice(-TRACE),
        pres: [...state.trace.pres, m.pres].slice(-TRACE),
      },
    })
  }
}

/** Subscribe to the feed. */
export function useLive(apiBase = ''): LiveState {
  const [, force] = useState(0)
  useEffect(() => {
    base = apiBase
    const fn = () => force((n) => n + 1)
    subs.add(fn)
    connect()
    return () => {
      subs.delete(fn)
      // Last reader out closes the door.
      if (subs.size === 0 && sock) { sock.close(); sock = null }
    }
  }, [apiBase])
  return state
}

/** Clear the drawn history, e.g. when the node is repaired and the old trace
 *  would otherwise show a step that the sensor never made. */
export function resetTrace() {
  push({ trace: { temp: [], rh: [], pres: [] }, grade: null })
}

export async function liveCommand(apiBase: string, path: string) {
  const r = await fetch((apiBase || '') + path, { method: 'POST' })
  if (!r.ok) throw new Error(`${path} returned ${r.status}`)
  return r.json()
}
