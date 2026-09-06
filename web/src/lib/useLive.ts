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
  /** Record frames since this band began, or null while it is ok. */
  open_frames: number | null
}

export type Band = 'learning' | 'ok' | 'watch' | 'fault'

export interface LiveState {
  status: 'connecting' | 'open' | 'closed'
  /** Newest first. A window, not a log: the archive is /api/map/*. */
  rows: LiveReading[]
  /** The node's readings placed on the SHARED record axis, indexed by frame.
   *
   * Not a rolling trace against a wall clock. Every reading the node sends
   * belongs to a fifteen-minute step of the same record the other 344 stations
   * are drawn from, so it is stored by frame and drawn in the same chart, on
   * the same axis, with the same window control. A separate live chart beside
   * them implied two different kinds of time where there is only one. */
  byFrame: { temp: (number | null)[]; rh: (number | null)[]; pres: (number | null)[] }
  /** Per-frame band from the online grader: '0' ok, '1' watch, '2' fault. */
  grades: string[]
  /** The highest frame received, i.e. how far the pen has drawn. */
  frame: number
  /** Which traverse of the record the node is on. A new pass is a fresh
   *  sheet: the frames from the last one are not this one's readings. */
  pass: number
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
    openFrames: number | null
  } | null
}

const KEEP = 40

let sock: WebSocket | null = null
let retry = 0
let timer: ReturnType<typeof setTimeout> | null = null
let base = ''
const subs = new Set<(s: LiveState) => void>()

let state: LiveState = {
  status: 'connecting', rows: [],
  latest: null, running: false, fault: 'none', silent: false, grade: null,
  byFrame: { temp: [], rh: [], pres: [] }, grades: [], frame: 0, pass: 0,
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
  let ws: WebSocket
  try {
    ws = new WebSocket(url)
    sock = ws
  } catch {
    push({ status: 'closed' })
    if (subs.size > 0) {
      const wait = Math.min(1000 * 2 ** retry, 15000)
      retry += 1
      if (timer !== null) clearTimeout(timer)
      timer = setTimeout(() => { timer = null; connect() }, wait)
    }
    return
  }
  // A DEAD SOCKET MUST NOT SPEAK FOR THE LIVE ONE.
  //
  // These handlers close over shared module state, and a socket that has been
  // replaced still fires: the old one's onclose arrived after the reconnect
  // had already succeeded, set sock back to null and pushed status 'closed'
  // over a connection that was working perfectly. The page then sat frozen
  // with readings streaming into handlers whose updates were being overwritten
  // by a corpse. Anything from a socket that is no longer `sock` is ignored.
  const stale = () => sock !== ws
  ws.onopen = () => { if (stale()) return; retry = 0; push({ status: 'open' }) }
  ws.onclose = () => {
    if (stale()) return
    sock = null
    push({ status: 'closed' })
    // RECONNECT. Without this the page is permanently deaf to the live feed
    // the first time the connection drops -- a server restart, a laptop
    // sleeping, a Space waking up -- and since the clock is driven by readings
    // arriving, the whole dashboard silently stops. Play then looks broken
    // while the node reports perfectly well on the other side of a socket
    // nobody is listening to.
    //
    // Backoff so a server that is down is not hammered, capped so a server
    // that comes back is picked up promptly.
    if (subs.size === 0) return
    const wait = Math.min(1000 * 2 ** retry, 15000)
    retry += 1
    if (timer !== null) clearTimeout(timer)
    timer = setTimeout(() => { timer = null; connect() }, wait)
  }
  ws.onmessage = (ev) => {
    if (stale()) return
    let m: LiveReading & { backlog?: LiveReading[]; running?: boolean; kind?: string }
    try { m = JSON.parse(ev.data) } catch { return }

    if (m.type === 'hello') {
      const h = m as unknown as {
        backlog?: LiveReading[]; running?: boolean; fault?: string
        frame?: number; pass?: number
      }
      const rows = (h.backlog ?? []).filter((x) => x.type === 'reading')
        .slice(-KEEP).reverse()
      // The hello carries the CURRENT state, not just the backlog: a page
      // opened after the node started never hears the event that says so.
      push({
        rows, latest: rows[0] ?? null,
        running: Boolean(h.running),
        fault: h.fault ?? 'none',
        pass: h.pass ?? 0,
      })
      return
    }
    if (m.type === 'feeder') { push({ running: Boolean(m.running) }); return }
    if (m.type === 'fault') { push({ fault: String(m.kind ?? 'none') }); return }
    if (m.type === 'silence') { push({ silent: true }); return }
    if (m.type === 'grade') {
      const g = m as unknown as GradeMessage
      const gf = (m as unknown as { frame?: number }).frame
      const grades = state.grades.slice()
      if (typeof gf === 'number') {
        while (grades.length < gf) grades.push('0')
        grades[gf] = g.band === 'fault' ? '2' : g.band === 'watch' ? '1' : '0'
      }
      push({
        grades,
        grade: {
          z: g.z, band: g.band, expected: g.expected,
          baseline: g.baseline, baselineNeeded: g.baseline_needed,
          openFrames: g.open_frames,
        },
      })
      return
    }
    if (m.type !== 'reading') return

    // EVERY READING GOES IN THE LEDGER; ONLY ONE STATION MOVES THE PEN.
    //
    // Both the feeder and the ESP32 post through /api/ingest and are published
    // on this socket. Writing both into byFrame drew two stations as one trace
    // -- and worse, let a hardware node in Maharashtra drive the clock for a
    // page showing a feeder in Gujarat.
    if (traceStation && m.station !== traceStation) {
      push({ rows: [m, ...state.rows].slice(0, KEEP) })
      return
    }

    const f = (m as unknown as { frame?: number }).frame
    const p = (m as unknown as { pass?: number }).pass ?? 0
    const next: Partial<LiveState> = {
      rows: [m, ...state.rows].slice(0, KEEP),
      latest: m,
      silent: false,
    }
    // A NEW PASS IS A FRESH SHEET.
    //
    // The node reports past the end of the thirty-day record and comes back to
    // the start. Keeping the previous traverse's frames drew the tail of one
    // pass and the head of the next on the same axis, with the untouched middle
    // between them -- two disconnected traces that looked like a broken chart
    // and were really the station reporting twice for the same timestamp.
    // A FRAME THAT GOES BACKWARDS IS A NEW SESSION, NOT A STRAY READING.
    //
    // frame used to be kept with Math.max(state.frame, f), which made it a
    // ratchet: once the server restarted, the node began its record again at a
    // low frame while the page still held the high-water mark from the last
    // session, and the maximum never moved again. The clock froze permanently
    // with readings pouring in and being discarded, which looked exactly like
    // a dead Play button. Treat a rewind the way a new pass is treated -- the
    // record restarted, so start a fresh sheet.
    const rewound = typeof f === 'number' && f + 1 < state.frame
    if (p !== state.pass || rewound) {
      state = {
        ...state, pass: p, frame: 0, grades: [],
        byFrame: { temp: [], rh: [], pres: [] },
      }
    }
    if (typeof f === 'number') {
      // Written by frame, not appended: a reading is FOR a moment in the
      // record, and two readings for the same frame are the same moment
      // measured twice, not two moments.
      const put = (arr: (number | null)[], v: number) => {
        const a = arr.slice()
        while (a.length < f) a.push(null)
        a[f] = v
        return a
      }
      next.byFrame = {
        temp: put(state.byFrame.temp, m.temp),
        rh: put(state.byFrame.rh, m.rh),
        pres: put(state.byFrame.pres, m.pres),
      }
      next.frame = f
      next.pass = p
    }
    push(next)
  }
}

/** Subscribe to the feed. */
/** Whose readings drive the trace and the clock.
 *
 *  Empty means "the first station we hear from", which is what the single-node
 *  build did implicitly. Set explicitly by the page once it knows the feeder's
 *  name, because the socket now carries hardware nodes too. */
let traceStation = ''

export function useLive(apiBase = '', station = ''): LiveState {
  const [, force] = useState(0)
  useEffect(() => {
    base = apiBase
    if (station && station !== traceStation) {
      // A different station owns the pen: the frames on the sheet are not its
      // readings, so start a fresh one rather than continuing someone else's.
      traceStation = station
      resetTrace()
    }
    const fn = () => force((n) => n + 1)
    subs.add(fn)
    connect()
    return () => {
      subs.delete(fn)
      // Last reader out closes the door.
      if (subs.size === 0) {
        if (timer !== null) { clearTimeout(timer); timer = null }
        if (sock) { sock.close(); sock = null }
      }
    }
  }, [apiBase, station])
  return state
}

/** Clear the drawn history, e.g. when the node is repaired and the old trace
 *  would otherwise show a step that the sensor never made. */
export function resetTrace() {
  push({
    byFrame: { temp: [], rh: [], pres: [] }, grades: [], frame: 0, grade: null,
  })
}

export async function liveCommand(apiBase: string, path: string) {
  const r = await fetch((apiBase || '') + path, { method: 'POST' })
  if (!r.ok) throw new Error(`${path} returned ${r.status}`)
  return r.json()
}
