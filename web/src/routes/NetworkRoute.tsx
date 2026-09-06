/* The network map, ported from the static console into the app.
 *
 * WHERE IT CAME FROM
 *
 * The map, the clock and the station list were built in a separate static
 * console while the app carried the landing page and the board. Two frontends
 * that had to be kept in step is a guarantee that one of them is wrong, and it
 * was: the console's channel charts had collapsed to two pixels wide and
 * nobody noticed, because nobody was looking at it. This is the port; the
 * console is gone.
 *
 * WHAT THE CONSOLE DID THAT THIS KEEPS, AND WHY EACH ONE WAS EARNED
 *
 *   The base is a FILTER over the tiles, not a different geometry. Swapping the
 *   imagery for a drawn India left one country floating on an empty ground,
 *   because a national boundary is the only geometry vendored here.
 *
 *   The station list is ALPHABETICAL and remembers which groups are open.
 *   Ordering by flag count reordered the list under the cursor every hour the
 *   clock advanced, and recomputing "open" from the data made groups spring
 *   open and shut on their own.
 *
 *   Healthy stations are drawn in the ground's own contrast, not white. White
 *   reads on satellite imagery and disappears on a pale one.
 */
import { GeoJSON, CircleMarker, MapContainer, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  useBoundaryGeo, useEdgeSeries, useEdgeStanding, useLiveStation, useSimMap,
  useStatesGeo,
  useTileStatus, useWdqmsMap,
} from '../api/queries'
import { BAND_ORDER, type Band, type SimMap, type SimStation } from '../api/mapTypes'
import { bandAt, frameOf, timeLabel } from '../lib/sim'
import { BAND_LABEL, HUE, label, why } from '../lib/bands'
import { allAlerts, ledgerAt } from '../lib/alerts'
import { StationChannels } from '../components/StationChannels'
import { MAP_BOX, fieldRange, paintField, rampCss } from '../lib/field'
import L from 'leaflet'
import { Async } from '../components/Async'
import { liveCommand, resetTrace, useLive } from '../lib/useLive'
import { usePageTitle } from '../lib/title'
import { useSticky } from '../lib/sticky'

type Net = 'sim' | 'wdqms'
type BaseKey = 'imagery' | 'muted' | 'dark'
type Channel = 'health' | 'temp' | 'rh' | 'pres'
type IndexCol = 'name' | 'state' | 'elev' | 'status'

/** A sortable column header. Clicking the active column reverses it, which is
 *  what every table anyone has ever used does. */
function Th({ col, sort, set, children }: {
  col: IndexCol
  sort: { col: IndexCol; desc: boolean }
  set: (s: { col: IndexCol; desc: boolean }) => void
  children: React.ReactNode
}) {
  const active = sort.col === col
  return (
    <th
      aria-sort={active ? (sort.desc ? 'descending' : 'ascending') : 'none'}
      className={'sticky top-0 z-10 whitespace-nowrap border-b border-rule bg-sunk '
                 + 'px-4 py-2.5 text-left font-mono text-[10px] font-semibold '
                 + 'uppercase tracking-widest '
                 + (active ? 'text-ink' : 'text-ink-3')}
    >
      <button type="button"
              className="inline-flex items-center gap-1 hover:text-ink"
              onClick={() => set({ col, desc: active ? !sort.desc : false })}>
        {children}
        <span aria-hidden="true" className="text-[8px]">
          {active ? (sort.desc ? '▼' : '▲') : ''}
        </span>
      </button>
    </th>
  )
}

type BaseDef = { label: string; filter: string; ok: string; okOpacity: number }

/* The base is a FILTER over the tiles. It used to also carry the three channel
 * fields, which put "what am I looking at" in two dropdowns at once: Base said
 * temperature and Channel said humidity and the map showed a mixture. One
 * question, one control -- Base is the ground, Channel is the measurement. */
const BASES: Record<BaseKey, BaseDef> = {
  imagery: { label: 'Imagery', filter: 'none', ok: '#FFFFFF', okOpacity: 0.6 },
  muted: { label: 'Muted', filter: 'grayscale(1) brightness(1.08) contrast(0.82)', ok: '#171A1E', okOpacity: 0.42 },
  dark: { label: 'Dark', filter: 'grayscale(1) brightness(0.42) contrast(1.15)', ok: '#FFFFFF', okOpacity: 0.5 },
}

/** India, for the opening view. The map shows the world; this is where it
 *  starts. */
const INDIA: [[number, number], [number, number]] = [[6.5, 68.0], [36.5, 97.5]]

/** Leaflet gives no React-side hook for pane styling, so the filter is applied
 *  imperatively to the tile pane. It has to be the PANE and not the container:
 *  filtering the container would grey the station markers too. */
function TilePaneFilter({ filter }: { filter: string }) {
  const map = useMap()
  useEffect(() => {
    const pane = map.getPane('tilePane')
    if (pane) {
      pane.style.filter = filter
      pane.setAttribute('aria-hidden', 'true')
    }
  }, [map, filter])
  return null
}

/** The field as the map's own background.
 *
 * An image overlay in a pane BELOW the markers and above the tiles, so the
 * stations stay readable on top of it. Repainted whenever the clock moves; the
 * geometry index behind it is computed once and reused, which is the only
 * reason scrubbing stays smooth. */
function FieldOverlay(
  { ch, rows, frame, clip }:
  { ch: 'temp' | 'rh' | 'pres' | undefined; rows: SimStation[]; frame: number
    clip?: unknown },
) {
  const map = useMap()
  const layer = useRef<L.ImageOverlay | null>(null)
  useEffect(() => {
    if (layer.current) { map.removeLayer(layer.current); layer.current = null }
    if (!ch || !rows.length) return
    if (!map.getPane('fieldPane')) {
      map.createPane('fieldPane')
      map.getPane('fieldPane')!.style.zIndex = '250'
    }
    const url = paintField(ch, rows, frame, clip)
    if (!url) return
    layer.current = L.imageOverlay(
      url,
      [[MAP_BOX.lat0, MAP_BOX.lon0], [MAP_BOX.lat1, MAP_BOX.lon1]],
      { pane: 'fieldPane', opacity: 0.92, interactive: false },
    ).addTo(map)
    return () => {
      if (layer.current) { map.removeLayer(layer.current); layer.current = null }
    }
  }, [map, ch, rows, frame, clip])
  return null
}

/** Opens on India and then leaves the map alone.
 *
 * There was a "fit to flagged" option here. It zoomed to the bounding box of
 * whatever was flagged, which sounds useful and was not: with the recalibrated
 * bands that is often nothing at all, sometimes one station, and the map either
 * refused to move or threw itself at a single dot in Assam. A control whose
 * behaviour depends on how many faults happen to exist right now is a control
 * nobody can predict, and the map already answers "where" by being a map.
 */
function Extent() {
  const map = useMap()
  useEffect(() => { map.fitBounds(INDIA, { padding: [24, 24] }) }, [map])
  return null
}

// Readings per second for a chosen simulated step. One reading is 30
// simulated minutes whatever the setting, so this is purely how fast the
// record is played: 15 min runs it four times faster than 1 hour.
function perSecond(stepMin: number): number {
  return Math.max(0.5, 60 / stepMin * 2)
}


/* A labelled control. The toolbar was a row of bare dropdowns whose meaning
 * you had to infer from their contents -- "1 hour" of what? -- so every one
 * now carries the question it answers. */
const SUMMARY = 'cursor-pointer select-none px-5 py-3.5 text-[15px] font-semibold '
              + 'tracking-tight marker:text-ink-3'

const SELECT = 'h-9 rounded-[--radius-md] border border-rule bg-paper px-2.5 '
             + 'text-sm text-ink outline-none focus-visible:ring-2 '
             + 'focus-visible:ring-[var(--color-brand)]'


function Readout({ label, v, mono, tone }: {
  label: string; v: string; mono?: boolean
  tone?: 'fault' | 'watch'
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-mono text-[9.5px] uppercase tracking-widest text-ink-3">
        {label}
      </span>
      <span className={
        'tnum text-sm font-medium '
        + (mono ? 'font-mono ' : '')
        + (tone === 'fault' ? 'text-fault' : tone === 'watch' ? 'text-watch' : 'text-ink')
      }>
        {v}
      </span>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
        {label}
      </span>
      {children}
    </label>
  )
}

export function NetworkRoute() {
  usePageTitle('Network')
  const tiles = useTileStatus()
  const sim = useSimMap()
  const wdqms = useWdqmsMap()
  const states = useStatesGeo()
  const boundary = useBoundaryGeo()
  const node = useLiveStation()
  /* Hardware nodes -- the ESP32 in Wokwi -- as opposed to the feeder
   * above. Registered with coordinates and graded against neighbours,
   * so they belong on this map as dots rather than in a side panel. */
  const edge = useEdgeStanding()
  const live = useLive(import.meta.env.VITE_API_BASE ?? '',
                       node.data?.name ?? '')

  const [net, setNet] = useSticky<Net>('net', 'sim')
  const [base, setBase] = useSticky<BaseKey>('base', 'imagery')
  const [channel, setChannel] = useSticky<Channel>('channel', 'health')
  const [showStates, setShowStates] = useSticky('showStates', false)
  /* HOW FAR THE CLOCK MOVES, and HOW MUCH CHART IS SHOWN. Both were fixed
   * constants -- an hour per tick and the whole month on every axis -- which
   * are reasonable defaults and terrible rules. A drift is invisible at
   * 30 days and obvious at 24 hours. */
  const [stepMin, setStepMin] = useSticky('stepMin', 60)
  const [windowH, setWindowH] = useSticky('windowH', 0)   // 0 = the whole record
  const [hour, setHour] = useSticky('hour', 0)
  const [selected, setSelected] = useSticky<string | null>('selected', null)

  /** The hardware node being looked at, if the selection is one. */
  const edgePicked = (selected && edge.data?.stations[selected]) || null
  const edgeSeries = useEdgeSeries(edgePicked ? edgePicked.id : null)

  /* FINDING A STATION IN 344 OF THEM.
   *
   * The index was 33 collapsed state groups and nothing else, so reaching one
   * named station meant knowing which state it is in and then reading a list.
   * A search box is the difference between an index and a filing cabinet.
   *
   * "Flagged only" is the other question this list is asked -- what needs
   * attention -- and answering it by expanding 33 groups and scanning is not
   * answering it. */
  /* Not sticky: whether a replay is in flight is about this second, not a
     preference to remember for the next visit. */
  const [replaying, setReplaying] = useState(false)
  const [query, setQuery] = useSticky('query', '')
  const [flaggedOnly, setFlaggedOnly] = useSticky('flaggedOnly', false)
  /** How the index is ordered. State first, because that is how a person who
   *  knows the network thinks about it; the header switches it. */
  const [sort, setSort] = useSticky<{ col: IndexCol; desc: boolean }>(
    'sort', { col: 'state', desc: false })

  const nSteps = sim.data?.n_steps ?? 1

  /* THE NODE IS "NOW", AND THE PAGE FOLLOWS IT.
   *
   * There were two clocks on this page and they disagreed: the map sat at day
   * 0 of the record while the live station's pen was at day 18.9 of the same
   * thirty days. Pressing Play advanced one and not the other, so the same
   * screen showed the network on 25 July and the node on 13 August.
   *
   * A live system has one present, and it is wherever the reporting station
   * has got to. So the clock is DERIVED from the node's frame rather than run
   * by a timer of its own, and everything on the page -- the map, the station
   * charts, the alert ledger -- reads the same moment as the node.
   *
   * Play and pause therefore control the NODE, not an animation: the only
   * thing that can advance time here is a reading arriving.
   */
  useEffect(() => {
    if (!live.running || !sim.data) return
    const step = live.frame * (sim.data.field_every || 1)
    setHour(Math.min(step, nSteps - 1))
  }, [live.frame, live.running, sim.data, nSteps])

  // Dragging the slider is taking manual control: the node is stopped so the
  // next reading does not yank the page back to the present. Play resumes it.
  const scrub = useCallback((step: number) => {
    setHour(step)
    if (live.running) {
      liveCommand(import.meta.env.VITE_API_BASE ?? '', '/api/live/stop')
        .catch(() => { /* the clock still moved; that is what was asked for */ })
    }
  }, [live.running])

  const b = BASES[base]
  /* Whether the live node's last reading failed the screen. Kept next to the
   * other map state so the marker is coloured by the same rule as every other
   * dot: red means something is wrong with it, and nothing else does. */
  /* THE NODE'S COLOUR IS ITS VERDICT, by the same rule as every other dot.
   *
   * Not the WMO screen. Measured on this node: a drift, a stuck value and a
   * +4.5 C offset all PASS the rails, because all three are physically
   * plausible readings -- which is the whole reason neighbour differencing
   * exists. Colouring the marker by the screen would have shown a healthy dot
   * for every fault the project is actually about. */
  const liveBand = live.grade?.band ?? null
  /* THE CHANNEL IS THE MEASUREMENT, and now it shows the measurement.
   *
   * Picking Temperature used to recolour the dots by the temperature grade and
   * nothing else. With the bands recalibrated to 6 and 8 sigma that is one dot
   * in three hundred and forty-four, so the control looked broken -- it was
   * working perfectly and had almost nothing to say. Selecting a channel now
   * also paints that channel's field, which is the data itself rather than a
   * verdict about it, and always changes the whole map. */
  const field: 'temp' | 'rh' | 'pres' | undefined =
    channel === 'health' ? undefined : channel

  /* Graded once per hour, not once per marker: 344 stations times a lookup per
   * render is the difference between scrubbing and stuttering. Worst last so a
   * fault is never painted under a healthy neighbour. */
  const graded = useMemo(() => {
    if (net !== 'sim' || !sim.data) return []
    const rows = sim.data.stations.map((s) => ({ s, band: bandAt(s, channel, hour) }))
    rows.sort((x, y) => BAND_ORDER[x.band] - BAND_ORDER[y.band])
    return rows
  }, [net, sim.data, channel, hour])

  /* THE INDEX, as one flat list.
   *
   * Grouping by state put the list in 33 containers and made the state
   * something you had to open rather than something you could read. As a
   * column it is sortable, searchable, and always visible -- and every row is
   * the same height, so nothing moves when anything changes. */
  const indexRows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const rows = graded.filter((r) => {
      if (flaggedOnly && r.band !== 'WATCH' && r.band !== 'FAULT') return false
      if (!q) return true
      return r.s.name.toLowerCase().includes(q)
        || (r.s.state || '').toLowerCase().includes(q)
    })
    const dir = sort.desc ? -1 : 1
    return rows.sort((a, b) => {
      switch (sort.col) {
        case 'elev': return dir * (a.s.elev - b.s.elev)
        case 'status':
          // Worst first when sorting by status: the reason anyone sorts by it.
          return dir * (BAND_ORDER[b.band] - BAND_ORDER[a.band])
            || a.s.name.localeCompare(b.s.name)
        case 'name': return dir * a.s.name.localeCompare(b.s.name)
        default:
          return dir * ((a.s.state || '').localeCompare(b.s.state || '')
            || a.s.name.localeCompare(b.s.name))
      }
    })
  }, [graded, query, flaggedOnly, sort])

  const flagged = graded.filter((r) => r.band === 'WATCH' || r.band === 'FAULT')

  /* ALERTS ARE EPISODES, NOT HOURS. See lib/alerts.ts: a grade is recomputed
   * from scratch every hour with no memory, so thresholding it directly gave
   * 2,484 "alerts" of which 1,318 lasted a single hour. These are debounced
   * into conditions with a beginning and an end. Computed once for the whole
   * record -- it does not depend on where the clock is. */
  const alerts = useMemo(
    () => (sim.data ? allAlerts(sim.data.stations) : []), [sim.data])
  /* The node as a station record, built once. Both the chart and the alert
   * ledger need it in the same shape as the other 344, because it is the same
   * kind of thing and every surface that treats it differently is a surface
   * that will drift. */
  const nodeStation: SimStation | null = node.data && sim.data
    ? { ...sim.data.stations[0], id: node.data.id, name: node.data.name,
        state: node.data.state, lat: node.data.lat, lon: node.data.lon,
        elev: node.data.elev, fault: null }
    : null

  const ledger = useMemo(() => ledgerAt(alerts, hour), [alerts, hour])

  /* THE LIVE NODE IN THE SAME LEDGER. It is a station in this network, so a
   * fault on it belongs where every other fault is listed. Put first because
   * it is the only entry that is happening now -- everything else in this
   * ledger is a record of a month already graded. */
  /** How long the node has been in this band, in the SAME UNIT the rest of
   *  this table uses.
   *
   *  It said "209 frames" beside rows saying "6 h", which is two units for one
   *  quantity -- and the number was wrong as well, counted from the end of the
   *  baseline rather than from the onset of the fault. A frame is half an hour
   *  of record, so the conversion is the honest one. */
  const nodeOpenLabel = live.grade?.openFrames != null
    ? `${Math.max(1, Math.round(live.grade.openFrames / 2))} h`
    : null

  /* HARDWARE NODES IN THE LEDGER.
   *
   * An episode that never reaches the alert list is an episode nobody reads.
   * The feeder gets a row below from its socket grade; these get one from the
   * polled standing, which is the same verdict arriving by a different route.
   *
   * `from` is a RECORD STEP for a simulated row. A node carries its duration
   * explicitly instead, for the same reason the feeder does: subtracting a
   * frame index from a step index is where "open -4 h" came from. */
  const edgeAlerts = useMemo(() => {
    // openLabel is carried on top of an Alert rather than in it: only rows
    // that own a wall clock have one, and widening the shared Alert type for
    // two of them would put a field on 344 rows that can never fill it.
    const out: (typeof ledger[number] & { openLabel?: string | null })[] = []
    for (const st of Object.values(edge.data?.stations ?? {})) {
      const g = edge.data?.standing[st.id]
      if (!g || (g.case !== 'watch' && g.case !== 'fault')) continue
      if (!sim.data) continue
      out.push({
        id: 'edge:' + st.id,
        s: { ...sim.data.stations[0], id: st.id, name: st.name,
             state: st.state, lat: st.lat, lon: st.lon, elev: st.elev,
             fault: null },
        ch: 'temp' as const,
        // Dated from where the episode STARTED, like every other row.
        from: g.open_from_frame ?? g.frame,
        to: null,
        // Record hours, not wall clock: two frames to the hour. The wall-clock
        // version counted how long the page had been open, and grew while the
        // node was not reporting at all.
        openLabel: g.open_frames != null
          ? `${(g.open_frames / 2).toFixed(1)} h` : null,
        band: (g.case === 'fault' ? 'FAULT' : 'WATCH') as Band,
        hours: 0,
        status: 'OPEN' as const,
        // Open by definition: a closed case is one the node stopped being in,
        // and the standing only ever reports the band it is in now.
        closedAt: null,
      })
    }
    return out
  }, [edge.data, sim.data])

  /** Hardware nodes that survive the index's search box and flagged filter.
   *  Same two rules the 344 obey, so the list does not quietly answer
   *  "flagged only" without a node that is in fault. */
  const edgeRows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return Object.values(edge.data?.stations ?? {})
      .map((st) => ({ st, g: edge.data?.standing[st.id] }))
      .filter(({ st, g }) => {
        if (q && !(`${st.name} ${st.state}`.toLowerCase().includes(q))) return false
        if (flaggedOnly && !(g && (g.case === 'watch' || g.case === 'fault'))) return false
        return true
      })
  }, [edge.data, query, flaggedOnly])

  const ledgerWithNode = useMemo(() => {
    const b = live.grade?.band
    if (!nodeStation || !b || (b !== 'watch' && b !== 'fault')) {
      return edgeAlerts.length ? [...edgeAlerts, ...ledger] : ledger
    }
    return [...edgeAlerts, {
      id: 'live:' + nodeStation.id,
      s: nodeStation,
      ch: 'temp' as const,
      // `from` is a RECORD STEP for every other row. The node's own clock is
      // the wall clock, so it carries its duration explicitly rather than
      // letting the table subtract a frame index from a step index -- which
      // is where "open -4 h" came from.
      from: hour,
      to: null,
      openLabel: nodeOpenLabel,
      band: (b === 'fault' ? 'FAULT' : 'WATCH') as Band,
      hours: 0,
      status: 'OPEN' as const,
      closedAt: null,
    }, ...ledger]
  }, [ledger, live.grade?.band, live.frame, nodeStation, hour, nodeOpenLabel])
  /* THE OPENING STATION IS CHOSEN ONCE, AND THEN LEFT ALONE.
   *
   * The page needs a station selected on arrival, or the charts are replaced by
   * an instruction and there is no graph on the page at all. The first attempt
   * DERIVED that station -- worst at the current hour -- which meant the clock
   * reselected it every tick: the name changed on its own, the three traces
   * were swapped underneath whoever was reading them, and stepping through the
   * month became impossible because the subject kept moving.
   *
   * A default is a starting point, not a rule. It is set once, when the data
   * first arrives, and after that only a click changes it.
   */
  useEffect(() => {
    if (selected || !graded.length) return
    // A NAMED DEFAULT, not "whichever is worst".
    //
    // Picking the worst station meant the page opened on a different place
    // every time the record was regenerated, which is no way to demonstrate
    // anything twice. Ahmadabad is chosen because it is a large, recognisable
    // station near the live node.
    //
    // Spelled AHMADABAD in the WMO list, not "Ahmedabad", and matched exactly:
    // a loose /ahm/ selects AHMADNAGAR in Maharashtra first. Falling back to
    // the worst keeps the page useful if the name ever leaves the export.
    const preferred = graded.find((g) => g.s.name.trim().toUpperCase() === 'AHMADABAD')
    const worst = [...graded].sort((a, c) => BAND_ORDER[c.band] - BAND_ORDER[a.band])[0]
    setSelected((preferred ?? worst).s.id)
    // graded is deliberately absent from the deps: this must run on the first
    // load and never again, and listing it would re-arm the effect every hour.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.data])

  const chosen = sim.data?.stations.find((s) => s.id === selected) ?? null
  /* The live node is selectable like any other station, because it IS one.
   * But it does not share their clock, and the section below says so rather
   * than letting the replay slider look as though it governs a device that is
   * reporting right now. */
  const nodeSelected = Boolean(node.data && selected === node.data.id)

  /* THE HARDWARE NODE, DRESSED AS A STATION SO THE STATION CHART CAN DRAW IT.
   *
   * StationChannels takes a SimStation and a per-frame overlay. The node is
   * not in the simulated export -- that is the point of it -- so it borrows
   * the shape of one and supplies its own identity, exactly as the feeder does
   * above, and its readings are placed on the shared frame axis. */
  const edgeStanding = edgePicked ? edge.data?.standing[edgePicked.id] : undefined
  const edgeStation: SimStation | null = edgePicked && sim.data
    ? { ...sim.data.stations[0], id: edgePicked.id, name: edgePicked.name,
        state: edgePicked.state, lat: edgePicked.lat, lon: edgePicked.lon,
        elev: edgePicked.elev, fault: null }
    : null
  /** The fetched series as the frame-indexed overlay the chart wants. */
  const edgeLive = useMemo(() => {
    const d = edgeSeries.data
    if (!d) return undefined
    const put = (vals: (number | null)[]) => {
      const out: (number | null)[] = []
      d.frames.forEach((f, i) => { out[f] = vals[i] ?? null })
      return out
    }
    return {
      byFrame: { temp: put(d.reported.temp), rh: put(d.reported.rh),
                 pres: put(d.reported.pres) },
      // Per-frame bands are not stored with the readings, so the trace is
      // drawn uncoloured rather than coloured from a guess. The band for the
      // node as a whole is on the badge above, where it is a fact.
      grades: [] as string[],
      upto: d.frames.length ? d.frames[d.frames.length - 1] : 0,
    }
  }, [edgeSeries.data])



  return (
    <div className="mx-auto max-w-[1600px] px-5 py-6">
      {/* A REAL PAGE HEADING.
          The previous version hid the title to save vertical space and left
          the reader facing a row of unlabelled dropdowns and a map, with
          nothing saying what any of it was. Space is cheaper than confusion. */}
      <header className="mb-5">
        <h1 className="text-2xl font-semibold tracking-tight">Network</h1>
        <p className="mt-1 max-w-[70ch] text-sm text-ink-2">
          Every station, graded against its neighbours. Play the record to watch
          faults appear, or pick a station to see its three channels.
        </p>
      </header>

      <div className="mb-3 flex flex-wrap items-end gap-x-5 gap-y-3
                      rounded-[--radius-lg] border border-rule bg-surface px-4 py-3">
        <Field label="Network">
          <select className={SELECT} value={net} onChange={(e) => setNet(e.target.value as Net)}>
            <option value="sim">Simulated — 344 locations</option>
            <option value="wdqms">Real — IMD via WDQMS</option>
          </select>
        </Field>
        <Field label="Base map">
          <select className={SELECT} value={base} onChange={(e) => setBase(e.target.value as BaseKey)}>
            {Object.entries(BASES).map(([k, v]) =>
              <option key={k} value={k}>{v.label}</option>)}
          </select>
        </Field>
        {net === 'sim' && (
          <Field label="Colour by">
            <select className={SELECT} value={channel}
                    onChange={(e) => setChannel(e.target.value as Channel)}>
              <option value="health">Worst channel</option>
              <option value="temp">Temperature</option>
              <option value="rh">Humidity</option>
              <option value="pres">Pressure</option>
            </select>
          </Field>
        )}
        {/* Step sets how fast the node reports, because a reading arriving is
            the only thing that advances time on this page now. */}
        <Field label="Play speed">
          <select className={SELECT} value={stepMin} onChange={(e) => {
            const min = +e.target.value
            setStepMin(min)
            // Retune, do not restart. Posting /api/live/replay here returned
            // 409 for a node that was already reporting, and the speed never
            // changed; restarting instead would have reset the clock to day 0.
            liveCommand(import.meta.env.VITE_API_BASE ?? '',
              `/api/live/rate?per_second=${perSecond(min)}`).catch(() => {})
          }}>
            <option value={15}>15 min</option>
            <option value={30}>30 min</option>
            <option value={60}>1 hour</option>
            <option value={180}>3 hours</option>
          </select>
        </Field>
        <Field label="Chart window">
          <select className={SELECT} value={windowH} onChange={(e) => setWindowH(+e.target.value)}>
            <option value={24}>Last 24 hours</option>
            <option value={72}>Last 3 days</option>
            <option value={168}>Last 7 days</option>
            <option value={0}>Whole record</option>
          </select>
        </Field>
        <label className="flex cursor-pointer items-center gap-2 pb-1.5 text-sm text-ink-2">
          <input type="checkbox" className="size-4 accent-[var(--color-brand)]"
                 checked={showStates}
                 onChange={(e) => setShowStates(e.target.checked)} />
          State outlines
        </label>
      </div>

      <Async query={tiles}>
        {(t) => (
          <div className="mapwrap overflow-hidden rounded-[--radius-lg] border border-rule">
            {/* THE WHEEL SCROLLS THE PAGE, not the map.
              *
              * A full-width map with wheel zoom on is a trap: the reader
              * scrolls down, the cursor crosses the map, the page stops and
              * the map zooms out instead. Ctrl/Cmd and the wheel still zooms,
              * the +/- buttons still work, and drag still pans. */}
            {/* THE WHEEL ZOOMS THE MAP. It scrolled the page for a while, on a
              * misreading of a note about zoom-on-scroll; a full-width map is
              * something you work inside, and reaching for the wheel over it
              * means zoom.
              *
              * wheelPxPerZoomLevel is raised well above Leaflet's default of 60
              * because one notch per level is the "too fast" everyone complains
              * about: a single flick crosses three levels and loses the country.
              * 220 makes a level cost a deliberate scroll.
              *
              * zoomSnap stays 1. Leaflet cannot animate a fractional zoom, so
              * fractional snapping is what made tiles pop rather than glide --
              * the earlier attempt to soften zooming was the cause of it. Speed
              * belongs in the wheel sensitivity, not in the zoom levels.
              *
              * keepBuffer loads a ring of tiles beyond the viewport so panning
              * moves over ready pixels instead of revealing grey. */}
            <MapContainer center={[22.5, 82]} zoom={4}
                          scrollWheelZoom wheelPxPerZoomLevel={220}
                          zoomSnap={1} zoomDelta={1} zoomAnimation
                          markerZoomAnimation fadeAnimation
                          className="netmap">
              <Extent />
              <TilePaneFilter filter={b.filter} />
              <FieldOverlay ch={field}
                            rows={net === 'sim' && sim.data ? sim.data.stations : []}
                            frame={sim.data ? frameOf(sim.data, hour) : 0}
                            clip={boundary.data} />
              {t.available && (
                <>
                  <TileLayer url={t.tile_template} maxZoom={t.max_zoom}
                             keepBuffer={4} updateWhenZooming={false}
                             attribution={t.attribution} />
                  {/* The official boundary from NCMRWF, not drawn by us: the
                      depiction of a national border is not something an
                      application should improvise.
                      Served as WMS tiles through the API's proxy where there is
                      one, and as the vendored geometry where there is not -- a
                      static host has no proxy, and the same source either way is
                      what matters. */}
                  {t.boundary_template
                    ? <TileLayer url={t.boundary_template} maxZoom={t.max_zoom} />
                    : boundary.data != null && (
                        <GeoJSON data={boundary.data as never}
                                 style={{ color: '#2A3F6B', weight: 1.1,
                                          opacity: 0.9, fill: false }} />)}
                </>
              )}
              {/* THE LIVE NODE, drawn after the network so it sits on top of
                  it. It is a station like any other -- same map, same
                  neighbours, same grading -- and the only thing marking it out
                  is that its reading arrived rather than being loaded. The
                  ring is what says "this one is reporting now"; the fill is
                  its screening verdict, exactly as for every other dot. */}
              {net === 'sim' && node.data && (
                <CircleMarker center={[node.data.lat, node.data.lon]}
                  radius={live.running ? 9 : 7}
                  eventHandlers={{ click: () => setSelected(node.data!.id) }}
                  pathOptions={{
                    color: live.status === 'open' ? '#1D6FE0' : '#8C8172',
                    weight: 2.5,
                    fillColor: liveBand === 'fault' ? '#E01B24'
                      : liveBand === 'watch' ? '#1D6FE0' : '#FFFFFF',
                    fillOpacity: 0.95,
                  }}>
                  <Tooltip direction="top" offset={[0, -8]}>
                    <b>{node.data.name}</b> — live node<br />
                    {node.data.state} · {node.data.elev} m<br />
                    {live.latest && live.latest.station === node.data.name ? (
                      <span className="mono">
                        {live.latest.temp.toFixed(1)} °C ·{' '}
                        {live.latest.rh.toFixed(1)} % ·{' '}
                        {live.latest.pres.toFixed(1)} hPa
                      </span>
                    ) : <span className="mono">not reporting</span>}
                    {live.grade && (
                      <><br /><b>
                        {live.grade.band === 'learning'
                          ? `learning its baseline (${live.grade.baseline}/${live.grade.baselineNeeded})`
                          : `${live.grade.band} · ${live.grade.z.toFixed(1)}σ from its neighbours`}
                      </b></>
                    )}
                    {live.latest?.server_flags?.length
                      ? <><br />screen: {live.latest.server_flags.join(', ')}</> : null}
                    <br />
                    <span className="mono">{node.data.neighbours.length} neighbours</span>
                  </Tooltip>
                </CircleMarker>
              )}

              {/* HARDWARE NODES. A device measuring its own readings, as
                  opposed to the feeder above which generates them. Dashed ring
                  so the two are never confused on a projector; fill is the
                  band, exactly as for every other dot. */}
              {net === 'sim' && edge.data && Object.values(edge.data.stations).map((st) => {
                const g = edge.data!.standing[st.id]
                // The CASE colours the dot. Colouring by the single reading
                // made the map flicker amber on noise while the board -- which
                // waits for three -- showed nothing, and a viewer cannot tell
                // which of the two is lying.
                const band = g?.case ?? 'learning'
                return (
                  <CircleMarker key={st.id} center={[st.lat, st.lon]}
                    radius={8}
                    eventHandlers={{ click: () => setSelected(st.id) }}
                    pathOptions={{
                      color: band === 'fault' ? '#E01B24'
                        : band === 'watch' ? '#B07908' : '#3B7A57',
                      weight: 2.5,
                      dashArray: '4 3',
                      fillColor: band === 'fault' ? '#E01B24'
                        : band === 'watch' ? '#F0B429' : '#FFFFFF',
                      fillOpacity: 0.95,
                    }}>
                    <Tooltip direction="top" offset={[0, -8]}>
                      <b>{st.name}</b> — {st.label}<br />
                      {st.state} · {st.elev} m<br />
                      {g ? (
                        <>
                          <span className="mono">
                            {g.reported.temp.toFixed(1)} °C ·{' '}
                            {g.reported.rh.toFixed(1)} % ·{' '}
                            {g.reported.pres.toFixed(1)} hPa
                          </span><br />
                          <b>{band === 'learning'
                            ? `learning its baseline (${g.readings}/40)`
                            : `${band} · ${g.z.toFixed(1)}σ from its neighbours`}</b>
                          {g.case_open && g.open_frames
                            ? <><br /><span className="mono">
                                case open {(g.open_frames / 2).toFixed(1)} h of record
                              </span></> : null}
                          <br />
                          <span className="mono">
                            neighbours say {g.expected.temp.toFixed(1)} °C ·{' '}
                            residual {g.residual > 0 ? '+' : ''}{g.residual.toFixed(2)}
                          </span>
                        </>
                      ) : <span className="mono">no readings yet</span>}
                      <br />
                      <span className="mono">{g?.neighbours ?? 6} neighbours · frame {g?.frame ?? '—'}</span>
                    </Tooltip>
                  </CircleMarker>
                )
              })}

              {showStates && states.data != null && (
                <GeoJSON data={states.data as never}
                         style={{ color: '#FFFFFF', weight: 1.2, opacity: 0.85, fill: false }} />
              )}

              {net === 'sim' && graded.map(({ s, band }) => {
                const hue = HUE[band]
                const sel = s.id === selected
                return (
                  <CircleMarker key={s.id} center={[s.lat, s.lon]}
                    radius={band === 'FAULT' ? 7 : band === 'WATCH' ? 5 : 3}
                    pathOptions={{
                      color: sel ? '#FFFFFF' : hue ?? b.ok,
                      fillColor: hue ?? b.ok,
                      fillOpacity: hue ? 0.95 : b.okOpacity,
                      weight: sel ? 2 : 0, stroke: sel,
                    }}
                    eventHandlers={{ click: () => setSelected(s.id) }}>
                    <Tooltip direction="top" offset={[0, -6]}>
                      <b>{s.name}</b> — {label(sim.data, s, channel, hour, band)}<br />
                      {s.state} · {s.elev} m<br />
                      <span className="mono">{sim.data && timeLabel(sim.data, hour)}</span>
                      {s.fault && <><br /><b>injected: {s.fault.kind} on {s.fault.channel}</b></>}
                    </Tooltip>
                  </CircleMarker>
                )
              })}

              {net === 'wdqms' && wdqms.data?.stations.filter((s) => s.in_india).map((s) => {
                const band = (s.health.state === 'FAULT' ? 'FAULT'
                  : s.health.state === 'WATCH' ? 'WATCH' : 'OK') as Band
                const hue = HUE[band]
                return (
                  <CircleMarker key={s.id} center={[s.latitude, s.longitude]}
                    radius={band === 'FAULT' ? 7 : band === 'WATCH' ? 5 : 3}
                    pathOptions={{ color: hue ?? b.ok, fillColor: hue ?? b.ok,
                                   fillOpacity: hue ? 0.95 : b.okOpacity, weight: 0, stroke: false }}>
                    <Tooltip direction="top" offset={[0, -6]}>
                      <b>{s.name}</b> — {s.health.state}<br />
                      {s.region} · worst: {s.health.channel} at {s.health.severity}× tolerance
                      {s.near.verdict === 'isolated' && <><br /><b>alone in its area</b></>}
                    </Tooltip>
                  </CircleMarker>
                )
              })}

            </MapContainer>
          </div>
        )}
      </Async>

      {net === 'sim' && sim.data && (
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-3
                        rounded-[--radius-lg] border border-rule bg-surface px-4 py-3">
          <button
            type="button"
            onClick={() => liveCommand(
              import.meta.env.VITE_API_BASE ?? '',
              live.running ? '/api/live/stop'
                : `/api/live/replay?per_second=${perSecond(stepMin)}`,
            ).catch(() => {})}
            className="inline-flex h-9 min-w-[84px] items-center justify-center gap-2
                       rounded-[--radius-pill] bg-ink px-4 text-sm font-medium text-paper
                       transition-opacity hover:opacity-85"
          >
            {live.running ? 'Pause' : 'Play'}
          </button>

          <input type="range" min={0} max={nSteps - 1} value={hour}
                 aria-label="Position in the 30-day record"
                 onChange={(e) => scrub(+e.target.value)}
                 className="h-1.5 min-w-[220px] flex-1 cursor-pointer appearance-none
                            rounded-full bg-sunk accent-[var(--color-brand)]" />

          {/* The clock and the counts, each labelled. The old bar ran them
              together as one grey mono string -- "0 fault · 0 watch · paused ·
              day 0.0 of 30" -- which is five separate facts pretending to be
              a sentence. */}
          <div className="flex items-center gap-5">
            <Readout label="Record time" v={timeLabel(sim.data, hour)} mono />
            <Readout
              label="Day"
              v={`${(hour * (sim.data?.step_minutes ?? 15) / 1440).toFixed(1)} / ${(nSteps * (sim.data?.step_minutes ?? 15) / 1440).toFixed(0)}`}
              mono
            />
            <Readout label="Faults now"
                     v={String(flagged.filter((r) => r.band === 'FAULT').length)}
                     tone="fault" />
            <Readout label="Watch"
                     v={String(flagged.filter((r) => r.band === 'WATCH').length)}
                     tone="watch" />
          </div>
        </div>
      )}

      {/* A field with no scale is decoration. The ends are the channel's own
          encoding range, which is what the ramp is stretched across. */}
      {field && sim.data && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2
                        rounded-[--radius-lg] border border-rule bg-surface px-4 py-3">
          <span className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
            Scale
          </span>
          <span className="tnum font-mono text-sm">
            {fieldRange(sim.data, field).lo} {fieldRange(sim.data, field).unit}
          </span>
          <span className="h-2.5 w-40 rounded-full border border-rule"
                style={{ background: rampCss(field) }} />
          <span className="tnum font-mono text-sm">
            {fieldRange(sim.data, field).hi} {fieldRange(sim.data, field).unit}
          </span>
          <span className="text-xs text-ink-3">
            Surface interpolated between stations — only the dots are measured.
          </span>
        </div>
      )}

      {/* NOT THREE COLUMNS.
        *
        * Rail, station and alerts side by side gave each of them about 260px,
        * and none of the three can do its job in 260px: a month-long trace
        * becomes a smudge, an alert wraps onto four lines, and the state list
        * was the only one that did not mind. So the page reads DOWN instead,
        * full width, one question per section -- which is also how the rest of
        * this site is built. The two that are really tables are drawn as
        * tables, and the station index flows across the width in text columns
        * rather than being penned into a panel. */}

      {/* WHOLE SECTIONS FOLD, NOT INDIVIDUAL CHARTS.
        *
        * The page is three long panels stacked -- a station, an alert ledger,
        * an index of 344 stations -- and a reader working on one of them has to
        * scroll past the other two every time. Folding a single chart does not
        * help with that; folding the section it lives in does.
        *
        * All three open by default. A page of collapsed headings hides its own
        * content behind a click nobody knows to make. */}

      {net === 'sim' && (
        <details className="mt-6 rounded-[--radius-lg] border border-rule bg-surface" open>
          <summary className={SUMMARY}>
            {edgePicked ? edgePicked.name
              : nodeSelected && node.data ? node.data.name
              : chosen ? chosen.name : 'Selected station'}
          </summary>
          {edgePicked && sim.data
            ? (<>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-5 pb-3 text-sm text-ink-2">
                  <span className="tnum font-mono text-xs text-ink-3">
                    {edgePicked.state} · {edgePicked.elev} m ·{' '}
                    {Math.abs(edgePicked.lat).toFixed(2)}N{' '}
                    {Math.abs(edgePicked.lon).toFixed(2)}E
                  </span>
                  <span className="badge" style={{ color: 'var(--ink-2)' }}>
                    hardware node
                  </span>
                  {edgeStanding && (
                    <span className="badge" style={{
                      color: edgeStanding.case === 'fault' ? 'var(--oxide)'
                        : edgeStanding.case === 'watch' ? 'var(--amber)'
                        : 'var(--ink-2)' }}>
                      {/* The case, so this badge agrees with the dot, the
                          index and the work card. The sigma beside it is this
                          reading's, which is what the chart is drawing. */}
                      {edgeStanding.case === 'learning'
                        ? `learning (${edgeStanding.readings}/40)`
                        : `${edgeStanding.case} · ${edgeStanding.z.toFixed(1)}σ`}
                    </span>
                  )}
                  {/* THE ONE CONTROL THIS NODE NEEDS.
                      A rebuild clears the readings -- that is what a reset
                      looks like on an ephemeral host -- and this is the way
                      back. It clears first: replaying without clearing draws
                      the same frames twice and the trace appears to double
                      back on itself. */}
                  <button type="button"
                    className="rounded-[--radius-md] border border-rule px-2.5 py-1
                               font-mono text-[11px] uppercase tracking-wider
                               text-ink-2 hover:bg-sunk
                               focus-visible:ring-2 focus-visible:ring-[var(--color-brand)]
                               disabled:opacity-50"
                    disabled={replaying}
                    onClick={async () => {
                      setReplaying(true)
                      try {
                        await liveCommand(import.meta.env.VITE_API_BASE ?? '',
                          `/api/edge/replay?station=${edgePicked.id}&rate=25`)
                      } catch { /* the panel already shows the count */ }
                      finally { setReplaying(false) }
                    }}>
                    {replaying ? 'replaying…' : 'replay scenario'}
                  </button>
                  <span className="tnum ml-auto font-mono text-xs text-ink-3">
                    {edgeSeries.data ? `${edgeSeries.data.n} readings` : 'loading'}
                  </span>
                </div>
                {edgeSeries.data && edgeSeries.data.n === 0 && (
                  <p className="small muted">
                    This node has never reported to this server. The readings
                    live on the host's disk, which a rebuild clears &mdash; so
                    a fresh deployment starts empty until either an ESP32 in
                    Wokwi posts to it or the scenario above is replayed.
                  </p>
                )}

                {/* The SAME chart the other 344 use, so the node is read the
                    way every other station is read. Its trace is drawn from
                    what it actually sent; the grey line underneath is what its
                    neighbours were reading at those frames, which is the
                    comparison the verdict is made of. */}
                <StationChannels
                  sim={sim.data}
                  s={edgeStation!}
                  hour={hour}
                  windowH={windowH}
                  live={edgeLive} />

                <p className="small muted">
                  This node measures its own readings on an ESP32 and posts
                  them to <code>/api/ingest</code> over TLS, through the same
                  door the rest of the network uses. Each sample is one frame
                  of the record —{' '}
                  <strong>
                    {edgeSeries.data?.minutes_per_frame ?? 30} simulated minutes
                  </strong>
                  {' '}— and the pen has reached{' '}
                  <strong>
                    {edgeSeries.data?.frames.length
                      ? edgeSeries.data.frames[edgeSeries.data.frames.length - 1]
                      : 0} of {sim.data.n_fields}
                  </strong>{' '}frames. Nothing to the right of the pen has been
                  measured, so nothing is drawn there. It is screened against
                  the WMO rails on the board, screened again on arrival, and
                  differenced against{' '}
                  {edgeStanding?.neighbours ?? 6} simulated neighbours.
                </p>
              </>)
            : nodeSelected && node.data && sim.data
            ? (<>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-5 pb-3 text-sm text-ink-2">
                  <span className="tnum font-mono text-xs text-ink-3">
                    {node.data.state} · {node.data.elev} m ·{' '}
                    {Math.abs(node.data.lat).toFixed(2)}N{' '}
                    {Math.abs(node.data.lon).toFixed(2)}E
                  </span>
                  <span className="badge" style={{ color: 'var(--ink-2)' }}>
                    {live.status === 'open' ? 'reporting' : live.status}
                  </span>
                  {/* The only control the node needs. There is no start
                      button: a weather station does not have one, it is
                      either reporting or it is broken, and broken is
                      something the detector should notice rather than
                      something the operator arranges. */}
                  <label className="mono faultsel">
                    Inject
                    <select value={live.fault} onChange={(e) => {
                      resetTrace()
                      liveCommand(import.meta.env.VITE_API_BASE ?? '',
                        '/api/live/fault?kind=' + e.target.value).catch(() => {})
                    }}>
                      <option value="none">nothing — healthy</option>
                      <option value="drift">drift</option>
                      <option value="offset">offset</option>
                      <option value="stuck">stuck</option>
                      <option value="spike">spike</option>
                      <option value="dropout">dropout</option>
                    </select>
                  </label>
                </div>

                {/* The SAME chart the other 344 use. Its readings are at the
                    same fifteen-minute steps and belong on the same axis; the
                    only difference is that the pen stops where the node has
                    reported rather than where the slider is. */}
                <StationChannels
                  sim={sim.data}
                  s={nodeStation!}
                  hour={hour}
                  windowH={windowH}
                  live={{ byFrame: live.byFrame, grades: live.grades,
                          upto: live.frame }} />

                <p className="small muted">
                  This node was switched on when the service started, so it
                  has no past — the axis is the same thirty days every station
                  here is drawn on, and the pen has reached{' '}
                  <strong>{live.frame} of {sim.data.n_fields}</strong> frames.
                  It fills as the node reports, about twelve minutes for the
                  month. Nothing to the right of the pen has been measured, so
                  nothing is drawn there.
                  {' '}Readings arrive at <code>/api/ingest</code>, are screened
                  against the WMO rails, differenced against six neighbours
                  within 120 km, and stored.
                </p>
              </>)
            : !chosen || !sim.data
            ? <p className="muted small">Pick a station on the map or in the index below.</p>
            : (<>
                {/* One line, not a heading plus a meta block plus a paragraph.
                    Name, where it is, and whether a fault was planted here --
                    everything else was prose the reader had already read. */}
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-5 pb-3 text-sm text-ink-2">
                  <span className="tnum font-mono text-xs text-ink-3">
                    {chosen.state} · {chosen.elev} m ·{' '}
                    {Math.abs(chosen.lat).toFixed(2)}{chosen.lat < 0 ? 'S' : 'N'}{' '}
                    {Math.abs(chosen.lon).toFixed(2)}{chosen.lon < 0 ? 'W' : 'E'}
                  </span>
                  {chosen.fault && (
                    <span className="badge" style={{ color: 'var(--ink-2)' }}>
                      injected {chosen.fault.kind} · {chosen.fault.channel} · h{chosen.fault.onset_hour}
                    </span>
                  )}
                  {sim.data && (
                    <span className="tnum ml-auto font-mono text-xs text-ink-3">
                      {timeLabel(sim.data, hour)}
                    </span>
                  )}
                </div>
                <StationChannels sim={sim.data} s={chosen} hour={hour} windowH={windowH} />
              </>)}
        </details>
      )}

      {net === 'sim' && (
        <details className="mt-6 rounded-[--radius-lg] border border-rule bg-surface" open>
          <summary className={SUMMARY}>
            Alerts
            <span className="ml-2 font-normal text-ink-3">
              {ledgerWithNode.filter((a) => a.status === 'OPEN').length} open of{' '}
              {ledgerWithNode.length} raised
            </span>
          </summary>
          <AlertList sim={sim.data} rows={ledgerWithNode} hour={hour} onSelect={setSelected} />
        </details>
      )}

      {net === 'sim' && (
        <details className="mt-6 rounded-[--radius-lg] border border-rule bg-surface" open>
          <summary className={SUMMARY}>
            Station index
            <span className="ml-2 font-normal text-ink-3">
              {graded.length} stations{node.data ? ' + 1 live node' : ''}
              {edge.data && Object.keys(edge.data.stations).length
                ? ` + ${Object.keys(edge.data.stations).length} hardware node`
                  + (Object.keys(edge.data.stations).length > 1 ? 's' : '')
                : ''} ·{' '}
              {flagged.length} flagged right now
            </span>
          </summary>

          <div className="flex flex-wrap items-center gap-4 px-5 pb-3">
            <input type="search" value={query}
                   placeholder="Find a station or state"
                   aria-label="Find a station or state"
                   onChange={(e) => setQuery(e.target.value)}
                   className="h-9 w-full max-w-[280px] rounded-[--radius-md] border border-rule
                              bg-paper px-3 text-sm outline-none
                              placeholder:text-ink-3 focus-visible:ring-2
                              focus-visible:ring-[var(--color-brand)]" />
            <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
              <input type="checkbox" className="size-4 accent-[var(--color-brand)]"
                     checked={flaggedOnly}
                     onChange={(e) => setFlaggedOnly(e.target.checked)} />
              Flagged only
            </label>
            {(query || flaggedOnly) && (
              <span className="tnum font-mono text-xs text-ink-3">
                {indexRows.length + edgeRows.length} of {graded.length + Object.keys(edge.data?.stations ?? {}).length}
              </span>
            )}
          </div>
          {/* A TABLE, NOT AN ACCORDION.
            *
            * This was 33 collapsible state groups flowing in text columns, and
            * it was wrong in a way no amount of tuning fixed: opening any group
            * changes its height, a multi-column flow reflows everything after
            * it, and the whole index jumps under the cursor. Which group starts
            * open only decided WHERE the jump happens.
            *
            * An index is a list you scan and search, not a set of drawers. One
            * row per station, every row the same height, nothing to open. The
            * state is a column rather than a container, so it can be sorted by
            * and searched on without hiding anything behind it. */}
          <div className={TWRAP + ' max-h-[520px]'}>
            <table className={TABLE}>
              <thead>
                <tr>
                  <Th col="name" sort={sort} set={setSort}>Station</Th>
                  <Th col="state" sort={sort} set={setSort}>State</Th>
                  <Th col="elev" sort={sort} set={setSort}>Elev</Th>
                  <Th col="status" sort={sort} set={setSort}>Status</Th>
                </tr>
              </thead>
              <tbody>
                {node.data && !query.trim() && !flaggedOnly && (
                  <tr className={TROW + (nodeSelected ? ' bg-brand-soft' : '')}
                      tabIndex={0}
                      onClick={() => setSelected(node.data!.id)}
                      onKeyDown={(e) => { if (e.key === 'Enter') setSelected(node.data!.id) }}>
                    <td className={TD + ' font-medium'}>{node.data.name}</td>
                    <td className={TD + ' text-ink-2'}>{node.data.state}</td>
                    <td className={TD + ' tnum text-right font-mono text-xs text-ink-2'}>
                      {node.data.elev} m
                    </td>
                    <td className={TD}>
                      <span className="badge" style={{ color: 'var(--ink-2)' }}>live</span>
                      {live.grade && live.grade.band !== 'ok'
                        && live.grade.band !== 'learning' && (
                        <span className="badge" style={{
                          color: HUE[live.grade.band === 'fault' ? 'FAULT' : 'WATCH']!,
                          borderColor: HUE[live.grade.band === 'fault' ? 'FAULT' : 'WATCH']!,
                        }}>{live.grade.band}</span>
                      )}
                    </td>
                  </tr>
                )}
                {edgeRows.map(({ st, g }) => (
                  <tr key={st.id} tabIndex={0}
                      className={TROW + (st.id === selected ? ' bg-brand-soft' : '')}
                      onClick={() => setSelected(st.id)}
                      onKeyDown={(e) => { if (e.key === 'Enter') setSelected(st.id) }}>
                    <td className={TD + ' font-medium'}>{st.name}</td>
                    <td className={TD + ' text-ink-2'}>{st.state}</td>
                    <td className={TD + ' tnum text-right font-mono text-xs text-ink-2'}>
                      {st.elev} m
                    </td>
                    <td className={TD}>
                      <span className="badge" style={{ color: 'var(--ink-2)' }}>node</span>
                      {g && g.case !== 'ok' && g.case !== 'learning' && (
                        <span className="badge" style={{
                          color: HUE[g.case === 'fault' ? 'FAULT' : 'WATCH']!,
                          borderColor: HUE[g.case === 'fault' ? 'FAULT' : 'WATCH']!,
                        }}>{g.case}</span>
                      )}
                    </td>
                  </tr>
                ))}
                {indexRows.map(({ s, band }) => (
                  <tr key={s.id} tabIndex={0}
                      className={TROW + (s.id === selected ? ' bg-brand-soft' : '')}
                      onClick={() => setSelected(s.id)}
                      onKeyDown={(e) => { if (e.key === 'Enter') setSelected(s.id) }}>
                    <td className={TD + ' font-medium'}>{s.name}</td>
                    <td className={TD + ' text-ink-2'}>{s.state}</td>
                    <td className={TD + ' tnum text-right font-mono text-xs text-ink-2'}>
                      {s.elev} m
                    </td>
                    <td className={TD}>
                      {band !== 'OK' && (
                        <span className="badge" title={why(band)}
                              style={{ color: HUE[band] ?? 'var(--ink-3)',
                                       borderColor: HUE[band] ?? 'var(--rule-edge)' }}>
                          {label(sim.data, s, channel, hour, band)}
                        </span>)}
                      {s.fault && (
                        <span className="mono idxinj">injected {s.fault.kind}</span>
                      )}
                    </td>
                  </tr>
                ))}
                {/* The empty state counts the hardware rows too. It used to
                    count only the simulated ones, so searching for the node
                    showed its row and "nothing matches" underneath it. */}
                {!indexRows.length && !edgeRows.length && (
                  <tr><td colSpan={4} className="muted small">
                    Nothing matches. {flaggedOnly && 'Nothing is flagged at this hour. '}
                    {query && `No station or state contains "${query}".`}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {net === 'sim' && sim.data && (
        <section className="netfoot">
          {/* The by-state table was here. It counted flags per state, which the
              map already shows and the alert ledger already lists by state --
              three answers to one question, and the least useful of them was
              taking a section to itself. */}
          <p className="small muted">
            Grades are this project's own verdict from neighbour differencing,
            standardised against a trailing 15-day spread, not the injected
            truth. Bands are 6σ and 8σ, calibrated against a fault-free control
            run. Ten stations — the Andaman, Nicobar and Lakshadweep groups —
            have no neighbours within 250 km and cannot be graded at all.
          </p>
        </section>
      )}
    </div>
  )
}

/** One station's three channels across the month, with the hours this project
 *  graded as watch or fault shaded behind each trace. The reading and the
 *  verdict on the reading, on one axis. */

/* WHAT IS WRONG RIGHT NOW.
 *
 * The Acknowledge button is gone. It set a flag in one browser tab: no store,
 * no assignment, no work order, and nothing downstream ever read it. A control
 * that does nothing is worse than no control, because it teaches the operator
 * that pressing things here has no effect -- and this list exists to be acted
 * on. When there is a real queue behind it, acknowledgement can come back
 * meaning something.
 *
 * What replaces it is the thing a watcher actually wanted: the row opens the
 * station.
 */

/* ONE TABLE STYLE, USED BY BOTH TABLES.
 *
 * The alert ledger and the station index were the last two things on this page
 * still drawn entirely by the old stylesheet: 10px mono in every cell, no
 * separation between header and body, and rows that gave no sign they could be
 * clicked. They are the two places a reader actually goes hunting, so they were
 * the worst two to leave dense. */
const TWRAP = 'overflow-auto border-t border-rule'
const TABLE = 'w-full border-collapse text-sm'
const TH = 'sticky top-0 z-10 whitespace-nowrap border-b border-rule bg-sunk px-4 py-2.5 '
         + 'text-left font-mono text-[10px] font-semibold uppercase tracking-widest text-ink-3'
const TD = 'border-b border-rule/60 px-4 py-2.5 align-middle'
const TROW = 'cursor-pointer transition-colors hover:bg-sunk'

function AlertList({ sim, rows, hour, onSelect }: {
  sim: SimMap | undefined
  rows: ReturnType<typeof ledgerAt>
  hour: number
  onSelect: (id: string) => void
}) {
  const CH = { temp: 'temperature', rh: 'humidity', pres: 'pressure' }
  if (!rows.length) {
    // The same box, empty. Collapsing it would move the page exactly as
    // growing it does, which is what this box exists to stop.
    return (
      <p className="border-t border-rule px-5 py-8 text-center text-sm text-ink-3">
        No alert has been raised yet. Press Play to run the record.
      </p>
    )
  }
  return (
    <div className={TWRAP + ' max-h-[420px]'}>
      <table className={TABLE}>
        <thead>
          <tr>
            <th className={TH}>Raised</th>
            <th className={TH}>Station</th>
            <th className={TH}>State</th>
            <th className={TH}>Channel</th>
            <th className={TH}>Status</th>
            <th className={TH}>Grade</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}
                className={TROW + (a.status === 'CLOSED' ? ' opacity-60' : '')}
                onClick={() => onSelect(a.s.id)} tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter') onSelect(a.s.id) }}>
              <td className={TD + ' tnum whitespace-nowrap font-mono text-xs text-ink-3'}>
                {sim ? timeLabel(sim, a.from) : '—'}
              </td>
              <td className={TD + ' font-medium'}>{a.s.name}</td>
              <td className={TD + ' text-ink-2'}>{a.s.state}</td>
              <td className={TD + ' text-ink-2'}>{CH[a.ch]}</td>
              <td className={TD + ' whitespace-nowrap font-mono text-xs'}>
                {a.status === 'OPEN'
                  ? <span className="st-open">
                      open · {(a as { openLabel?: string | null }).openLabel
                        ?? `${hour - a.from + 1} h`}
                    </span>
                  : <span className="st-closed">closed · {a.closedAt! - a.from} h</span>}
              </td>
              <td className={TD}>
                <span className="badge" style={{ color: HUE[a.band]!, borderColor: HUE[a.band]! }}>
                  {BAND_LABEL[a.band]}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
