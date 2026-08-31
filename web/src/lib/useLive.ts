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
    if (p !== state.pass) {
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
      next.frame = Math.max(state.frame, f)
      next.pass = p
    }
    push(next)
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
  push({
    byFrame: { temp: [], rh: [], pres: [] }, grades: [], frame: 0, grade: null,
  })
}

export async function liveCommand(apiBase: string, path: string) {
  const r = await fetch((apiBase || '') + path, { method: 'POST' })
  if (!r.ok) throw new Error(`${path} returned ${r.status}`)
  return r.json()
}
