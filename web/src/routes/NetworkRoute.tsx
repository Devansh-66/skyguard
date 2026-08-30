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
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  useArmMap, useSimMap, useStatesGeo, useTileStatus, useWdqmsMap,
} from '../api/queries'
import { BAND_ORDER, type Band, type SimMap, type SimStation } from '../api/mapTypes'
import { bandAt, frameOf, timeLabel } from '../lib/sim'
import { BAND_LABEL, HUE, label, why } from '../lib/bands'
import { StationChannels } from '../components/StationChannels'
import { MAP_BOX, fieldRange, paintField, rampCss } from '../lib/field'
import L from 'leaflet'
import { Async } from '../components/Async'

type Net = 'sim' | 'wdqms' | 'arm'
type BaseKey = 'imagery' | 'muted' | 'dark'
  | 'field_temp' | 'field_rh' | 'field_pres'
type Channel = 'health' | 'temp' | 'rh' | 'pres'
type View = 'india' | 'flagged'

/** How many of these carry no grade at all.
 *
 * A group where every station is ungraded has not been found "clear" -- nothing
 * looked at it. Saying "all 3 clear" of the Andaman stations claimed a verdict
 * the pipeline never reached. */
function ungradedCount(rows: { band: Band }[]): number {
  return rows.filter((r) => r.band === 'NODATA').length
}

type BaseDef = {
  label: string; filter: string; ok: string; okOpacity: number
  /** Set on the three channel fields; absent on the plain bases. */
  field?: 'temp' | 'rh' | 'pres'
}

/* The base is a FILTER over the tiles plus, for three of them, an interpolated
 * field painted on top. The channel maps used to be three small panels beside
 * the main one; folding them in here is what let the map go full width, and it
 * is the same question asked of the same ground rather than four grounds. */
const BASES: Record<BaseKey, BaseDef> = {
  imagery: { label: 'Imagery', filter: 'none', ok: '#FFFFFF', okOpacity: 0.6 },
  muted: { label: 'Muted', filter: 'grayscale(1) brightness(1.08) contrast(0.82)', ok: '#171A1E', okOpacity: 0.42 },
  dark: { label: 'Dark', filter: 'grayscale(1) brightness(0.42) contrast(1.15)', ok: '#FFFFFF', okOpacity: 0.5 },
  // The fields sit ON TOP of a darkened basemap rather than replacing it, so
  // coastline and terrain are still there to place a station against.
  field_temp: { label: 'Temperature field', field: 'temp', filter: 'grayscale(1) brightness(0.30)', ok: '#FFFFFF', okOpacity: 0.55 },
  field_rh: { label: 'Humidity field', field: 'rh', filter: 'grayscale(1) brightness(0.30)', ok: '#FFFFFF', okOpacity: 0.55 },
  field_pres: { label: 'Pressure field (MSL)', field: 'pres', filter: 'grayscale(1) brightness(0.30)', ok: '#FFFFFF', okOpacity: 0.55 },
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
    if (pane) pane.style.filter = filter
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
  { ch, rows, frame }:
  { ch: 'temp' | 'rh' | 'pres' | undefined; rows: SimStation[]; frame: number },
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
    const url = paintField(ch, rows, frame)
    if (!url) return
    layer.current = L.imageOverlay(
      url,
      [[MAP_BOX.lat0, MAP_BOX.lon0], [MAP_BOX.lat1, MAP_BOX.lon1]],
      { pane: 'fieldPane', opacity: 0.92, interactive: false },
    ).addTo(map)
    return () => {
      if (layer.current) { map.removeLayer(layer.current); layer.current = null }
    }
  }, [map, ch, rows, frame])
  return null
}

/** Where the map looks.
 *
 * "All India" is the opening view and the one that keeps the country in
 * proportion. "Fit to flagged" answers the other question a watcher has -- how
 * spread out is the trouble -- and it deliberately does nothing when nothing is
 * flagged, because zooming to an empty set lands the map in the ocean. */
/** Ctrl (or Cmd) plus the wheel zooms; the wheel alone scrolls the page. */
function CtrlWheelZoom() {
  const map = useMap()
  useEffect(() => {
    const el = map.getContainer()
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return
      e.preventDefault()
      map.setZoom(map.getZoom() - Math.sign(e.deltaY) * 0.5)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [map])
  return null
}

function Extent({ view, flagged }: {
  view: View; flagged: [number, number][]
}) {
  const map = useMap()
  useEffect(() => {
    if (view === 'india' || flagged.length === 0) {
      map.fitBounds(INDIA, { padding: [24, 24] })
      return
    }
    map.fitBounds(L.latLngBounds(flagged.map(([a, b]) => L.latLng(a, b))),
                  { padding: [48, 48], maxZoom: 7 })
    // Only when the CHOICE changes, never on every clock tick: refitting as
    // stations flag and clear would make the map lurch while it is being read.
  }, [map, view])
  return null
}

export function NetworkRoute() {
  const tiles = useTileStatus()
  const sim = useSimMap()
  const wdqms = useWdqmsMap()
  const arm = useArmMap()
  const states = useStatesGeo()

  const [net, setNet] = useState<Net>('sim')
  const [base, setBase] = useState<BaseKey>('imagery')
  const [channel, setChannel] = useState<Channel>('health')
  const [showStates, setShowStates] = useState(false)
  const [view, setView] = useState<View>('india')
  const [hour, setHour] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  // Which state groups are expanded. This belongs to the reader, not to the
  // data, so it is not derived from it and does not reset when the clock moves.
  const [open, setOpen] = useState<Set<string>>(new Set())

  const nSteps = sim.data?.n_steps ?? 1
  const timer = useRef<number | null>(null)
  useEffect(() => {
    if (!playing) return
    timer.current = window.setInterval(
      () => setHour((h) => (h + 1) % nSteps), 90)
    return () => { if (timer.current) window.clearInterval(timer.current) }
  }, [playing, nSteps])

  const b = BASES[base]

  /* Graded once per hour, not once per marker: 344 stations times a lookup per
   * render is the difference between scrubbing and stuttering. Worst last so a
   * fault is never painted under a healthy neighbour. */
  const graded = useMemo(() => {
    if (net !== 'sim' || !sim.data) return []
    const rows = sim.data.stations.map((s) => ({ s, band: bandAt(s, channel, hour) }))
    rows.sort((x, y) => BAND_ORDER[x.band] - BAND_ORDER[y.band])
    return rows
  }, [net, sim.data, channel, hour])

  const byState = useMemo(() => {
    const m = new Map<string, { s: SimStation; band: Band }[]>()
    for (const r of graded) {
      const k = r.s.state || 'Unassigned'
      if (!m.has(k)) m.set(k, [])
      m.get(k)!.push(r)
    }
    // Alphabetical, always. See the header note.
    return [...m.entries()].sort((a, c) => a[0].localeCompare(c[0]))
  }, [graded])

  const flagged = graded.filter((r) => r.band === 'WATCH' || r.band === 'FAULT')
  /* THE PAGE OPENED WITH NO GRAPH ON IT.
   *
   * Nothing was selected until the reader clicked, so the middle column held an
   * instruction where the charts belong -- and the instruction is only readable
   * by someone who already knows what it is offering. Falling back to the worst
   * station at this hour puts a real trace on screen immediately, and it is the
   * one worth looking at rather than an arbitrary first row. */
  const fallback = graded.length
    ? [...graded].sort((a, c) => BAND_ORDER[c.band] - BAND_ORDER[a.band])[0].s.id
    : null
  const chosen = sim.data?.stations.find((s) => s.id === (selected ?? fallback)) ?? null

  return (
    <div className="sheet network">
      {/* No page title. The top bar already says which page this is, and a
          page-sized heading repeating it pushed the map -- the actual content --
          below the fold on a laptop. What the network IS belongs on the control
          row beside the selector that changes it. */}

      <div className="mapctl">
        <label>Network
          <select value={net} onChange={(e) => setNet(e.target.value as Net)}>
            <option value="sim">Simulated — 344 locations</option>
            <option value="wdqms">Real — IMD via WDQMS</option>
            <option value="arm">Validation — 9 ARM masts</option>
          </select>
        </label>
        <label>Base
          <select value={base} onChange={(e) => setBase(e.target.value as BaseKey)}>
            {Object.entries(BASES).map(([k, v]) =>
              <option key={k} value={k}>{v.label}</option>)}
          </select>
        </label>
        <label>View
          <select value={view} onChange={(e) => setView(e.target.value as View)}>
            <option value="india">All India</option>
            <option value="flagged">Fit to flagged</option>
          </select>
        </label>
        {net === 'sim' && (
          <label>Channel
            <select value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
              <option value="health">Worst channel</option>
              <option value="temp">Temperature</option>
              <option value="rh">Humidity</option>
              <option value="pres">Pressure</option>
            </select>
          </label>
        )}
        <span className="ctxnote">
          {net === 'sim' ? '344 IMD locations · 30 days · simulated'
            : net === 'wdqms' ? 'Real IMD stations · WMO quality monitoring'
              : '9 ARM instruments · validation'}
        </span>
        <label className="cbx">
          <input type="checkbox" checked={showStates}
                 onChange={(e) => setShowStates(e.target.checked)} />
          State outlines
        </label>
      </div>

      <Async query={tiles}>
        {(t) => (
          <div className="mapwrap">
            {/* THE WHEEL SCROLLS THE PAGE, not the map.
              *
              * A full-width map with wheel zoom on is a trap: the reader
              * scrolls down, the cursor crosses the map, the page stops and
              * the map zooms out instead. Ctrl/Cmd and the wheel still zooms,
              * the +/- buttons still work, and drag still pans. */}
            <MapContainer center={[22.5, 82]} zoom={4} scrollWheelZoom={false}
                          zoomSnap={0.25} zoomDelta={0.5} wheelPxPerZoomLevel={170}
                          className="netmap">
              <CtrlWheelZoom />
              <Extent view={view}
                      flagged={flagged.map((r) => [r.s.lat, r.s.lon] as [number, number])} />
              <TilePaneFilter filter={b.filter} />
              <FieldOverlay ch={b.field}
                            rows={net === 'sim' && sim.data ? sim.data.stations : []}
                            frame={sim.data ? frameOf(sim.data, hour) : 0} />
              {t.available && (
                <>
                  <TileLayer url={t.tile_template} maxZoom={t.max_zoom}
                             attribution={t.attribution} />
                  {/* The official boundary, served from NCMRWF rather than drawn
                      by us: the depiction of a national border is not something
                      an application should improvise. */}
                  <TileLayer url={t.boundary_template} maxZoom={t.max_zoom} />
                </>
              )}
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

              {net === 'arm' && arm.data?.stations.map((s) => (
                <CircleMarker key={s.id} center={[s.latitude, s.longitude]}
                  radius={s.reports > 0 ? 7 : 5}
                  pathOptions={{ color: '#E01B24', fillColor: '#E01B24',
                                 fillOpacity: 0.95, weight: 0, stroke: false }}>
                  <Tooltip direction="top" offset={[0, -6]}>
                    <b>{s.place}</b><br />{s.observatory} {s.facility}<br />
                    {s.reports} analyst fault report{s.reports === 1 ? '' : 's'} held
                  </Tooltip>
                </CircleMarker>
              ))}
            </MapContainer>
          </div>
        )}
      </Async>

      {net === 'sim' && sim.data && (
        <div className="simbar">
          <button className="btn ghost" onClick={() => setPlaying((p) => !p)}>
            {playing ? 'Pause' : 'Play'}
          </button>
          <input type="range" min={0} max={nSteps - 1} value={hour}
                 aria-label="Hour of the replay"
                 onChange={(e) => setHour(+e.target.value)} />
          <span className="mono">{timeLabel(sim.data, hour)}</span>
          <span className="mono muted">
            {flagged.filter((r) => r.band === 'FAULT').length} fault ·{' '}
            {flagged.filter((r) => r.band === 'WATCH').length} watch · hour {hour + 1}/{nSteps}
          </span>
        </div>
      )}

      {/* A field with no scale is decoration. The ends are the channel's own
          encoding range, which is what the ramp is stretched across. */}
      {b.field && sim.data && (
        <div className="fieldkey">
          <span className="mono">{fieldRange(sim.data, b.field).lo} {fieldRange(sim.data, b.field).unit}</span>
          <span className="fieldramp" style={{ background: rampCss(b.field) }} />
          <span className="mono">{fieldRange(sim.data, b.field).hi} {fieldRange(sim.data, b.field).unit}</span>
          <span className="small muted">
            {BASES[base].label} — interpolated from 344 stations by inverse
            distance weighting. The surface is drawn; only the dots are measured.
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

      {net === 'sim' && (
        <section className="netsec">
          {!chosen || !sim.data
            ? <p className="muted small">Pick a station on the map or in the index below.</p>
            : (<>
                {/* One line, not a heading plus a meta block plus a paragraph.
                    Name, where it is, and whether a fault was planted here --
                    everything else was prose the reader had already read. */}
                <div className="stnhead">
                  <h2>{chosen.name}</h2>
                  <span className="mono muted">
                    {chosen.state} · {chosen.elev} m ·{' '}
                    {Math.abs(chosen.lat).toFixed(2)}{chosen.lat < 0 ? 'S' : 'N'}{' '}
                    {Math.abs(chosen.lon).toFixed(2)}{chosen.lon < 0 ? 'W' : 'E'}
                  </span>
                  {chosen.fault && (
                    <span className="badge" style={{ color: 'var(--ink-2)' }}>
                      injected {chosen.fault.kind} · {chosen.fault.channel} · h{chosen.fault.onset_hour}
                    </span>
                  )}
                  {sim.data && <span className="mono muted stnclock">{timeLabel(sim.data, hour)}</span>}
                </div>
                <StationChannels sim={sim.data} s={chosen} hour={hour} />
              </>)}
        </section>
      )}

      {net === 'sim' && (
        <section className="netsec">
          <div className="belowhead">
            Flagged now · {flagged.length}
          </div>
          <AlertList sim={sim.data} rows={flagged} hour={hour} onSelect={setSelected} />
        </section>
      )}

      {net === 'sim' && (
        <section className="netsec">
          <div className="belowhead">
            Station index · {flagged.length} flagged of {graded.length}
          </div>
          <div className="netrail">
              {byState.map(([state, rows]) => {
                const bad = rows.filter((r) => r.band === 'WATCH' || r.band === 'FAULT').length
                const isOpen = open.has(state)
                const sorted = [...rows].sort((a, c) =>
                  BAND_ORDER[c.band] - BAND_ORDER[a.band] || a.s.name.localeCompare(c.s.name))
                return (
                  <details key={state} open={isOpen} onToggle={(e) => {
                    const next = new Set(open)
                    if ((e.target as HTMLDetailsElement).open) next.add(state); else next.delete(state)
                    setOpen(next)
                  }}>
                    <summary>
                      <span>{state}</span>
                      <span className="state-count mono">
                        {bad ? `${bad} of ${rows.length}`
                          : ungradedCount(rows) === rows.length
                            ? `${rows.length} ungraded`
                            : `all ${rows.length} clear`}
                      </span>
                    </summary>
                    {sorted.map(({ s, band }) => (
                      <button key={s.id}
                        className={'stn' + (s.id === selected ? ' on' : '')}
                        onClick={() => setSelected(s.id)}>
                        <span className="spine" style={{ background: HUE[band] ?? 'var(--rule)' }} />
                        <span className="card-main">
                          <span className="card-station">{s.name}</span>
                          <span className="card-meta num">
                            {s.elev} m{s.fault ? ` · injected ${s.fault.kind}` : ''}
                          </span>
                        </span>
                        {band !== 'OK' && (
                          <span className="badge" title={why(band)}
                                style={{ color: HUE[band] ?? 'var(--ink-3)',
                                         borderColor: HUE[band] ?? 'var(--rule-edge)' }}>
                            {label(sim.data, s, channel, hour, band)}
                          </span>)}
                      </button>
                    ))}
                  </details>
                )
              })}
          </div>
        </section>
      )}

      {net === 'sim' && sim.data && (
        <section className="netfoot">
          <div className="belowhead">Where it is wrong, by state</div>
          <WrongByState rows={graded} />
          <p className="small muted">
            {sim.data.note}
          </p>
          <p className="small muted">
            Grades are this project's own verdict from neighbour differencing
            against a fifteen-day baseline, not the injected truth. Health is the
            worst of the three channels, never the mean. Ten stations — the
            Andaman, Nicobar and Lakshadweep groups — have no neighbours within
            250 km and cannot be graded at all.
          </p>
        </section>
      )}
    </div>
  )
}

/** How the flags are distributed across the country.
 *
 * The map answers "where", badly, for anything below about five stations: a
 * single red dot in Assam and a single red dot in Kerala look identical to a
 * cluster. This counts them. States with nothing wrong are omitted rather than
 * listed as zero -- thirty rows of zero hide the four that matter. */
function WrongByState({ rows }: { rows: { s: SimStation; band: Band }[] }) {
  const by = new Map<string, { fault: number; watch: number; n: number }>()
  for (const r of rows) {
    const k = r.s.state || 'Unassigned'
    const e = by.get(k) ?? { fault: 0, watch: 0, n: 0 }
    e.n++
    if (r.band === 'FAULT') e.fault++
    if (r.band === 'WATCH') e.watch++
    by.set(k, e)
  }
  const hot = [...by.entries()].filter(([, e]) => e.fault || e.watch)
    .sort((a, b) => (b[1].fault * 2 + b[1].watch) - (a[1].fault * 2 + a[1].watch))
  if (!hot.length) {
    return <p className="muted small">Nothing flagged anywhere at this hour.</p>
  }
  return (
    <table className="wrongtab mono">
      <tbody>
        {hot.map(([state, e]) => (
          <tr key={state}>
            <td>{state}</td>
            <td style={{ color: e.fault ? HUE.FAULT! : 'var(--ink-3)' }}>
              {e.fault} fault
            </td>
            <td style={{ color: e.watch ? HUE.WATCH! : 'var(--ink-3)' }}>
              {e.watch} watch
            </td>
            <td className="muted">of {e.n}</td>
          </tr>
        ))}
      </tbody>
    </table>
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
function AlertList({ sim, rows, hour, onSelect }: {
  sim: SimMap | undefined
  rows: { s: SimStation; band: Band }[]
  hour: number
  onSelect: (id: string) => void
}) {
  if (!rows.length) {
    return <p className="muted small">Nothing flagged at this hour.</p>
  }
  const when = sim ? timeLabel(sim, hour) : '—'
  return (
    <div className="tabwrap">
      <table className="alerttab">
        <thead>
          <tr>
            <th>Raised</th><th>Station</th><th>State</th>
            <th>Channel</th><th>Grade</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.s.id + r.band} onClick={() => onSelect(r.s.id)} tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter') onSelect(r.s.id) }}>
              <td className="mono when">{when}</td>
              <td className="stncell">{r.s.name}</td>
              <td className="mono muted">{r.s.state}</td>
              <td className="mono">{firedChannel(r.s, r.band, hour)}</td>
              <td>
                <span className="badge" style={{ color: HUE[r.band]!, borderColor: HUE[r.band]! }}>
                  {BAND_LABEL[r.band]}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Which channel is responsible for a station's worst grade.
 *
 * The map colours a station by its WORST channel, which is the right summary
 * and a useless dispatch instruction: nobody drives out to fix "the station".
 * Reporting more than one where several tie is honest -- ties happen when a
 * whole logger goes. */
function firedChannel(s: SimStation, band: Band, hour: number): string {
  const NAMES = { temp: 'temperature', rh: 'humidity', pres: 'pressure' } as const
  const hit = (['temp', 'rh', 'pres'] as const)
    .filter((c) => bandAt(s, c, hour) === band).map((c) => NAMES[c])
  return hit.length ? hit.join(' + ') : 'no single channel'
}
