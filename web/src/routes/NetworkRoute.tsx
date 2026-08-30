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
  useArmMap, useBoundaryGeo, useSimMap, useStatesGeo, useTileStatus, useWdqmsMap,
} from '../api/queries'
import { BAND_ORDER, type Band, type SimMap, type SimStation } from '../api/mapTypes'
import { bandAt, frameOf, stepsPerMinutes, timeLabel } from '../lib/sim'
import { BAND_LABEL, HUE, UNGRADED_WHY, label, why } from '../lib/bands'
import { allAlerts, ledgerAt } from '../lib/alerts'
import { StationChannels } from '../components/StationChannels'
import { MAP_BOX, fieldRange, paintField, rampCss } from '../lib/field'
import L from 'leaflet'
import { Async } from '../components/Async'
import { usePageTitle } from '../lib/title'

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
  usePageTitle('Network')
  const tiles = useTileStatus()
  const sim = useSimMap()
  const wdqms = useWdqmsMap()
  const arm = useArmMap()
  const states = useStatesGeo()
  const boundary = useBoundaryGeo()

  const [net, setNet] = useState<Net>('sim')
  const [base, setBase] = useState<BaseKey>('imagery')
  const [channel, setChannel] = useState<Channel>('health')
  const [showStates, setShowStates] = useState(false)
  const [view, setView] = useState<View>('india')
  /* HOW FAR THE CLOCK MOVES, and HOW MUCH CHART IS SHOWN. Both were fixed
   * constants -- an hour per tick and the whole month on every axis -- which
   * are reasonable defaults and terrible rules. A drift is invisible at
   * 30 days and obvious at 24 hours. */
  const [stepMin, setStepMin] = useState(60)
  const [windowH, setWindowH] = useState(0)      // 0 = the whole record
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
    const by = sim.data ? stepsPerMinutes(sim.data, stepMin) : 4
    timer.current = window.setInterval(
      () => setHour((h) => (h + by) % nSteps), 90)
    return () => { if (timer.current) window.clearInterval(timer.current) }
  }, [playing, nSteps, stepMin, sim.data])

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

  /* ALERTS ARE EPISODES, NOT HOURS. See lib/alerts.ts: a grade is recomputed
   * from scratch every hour with no memory, so thresholding it directly gave
   * 2,484 "alerts" of which 1,318 lasted a single hour. These are debounced
   * into conditions with a beginning and an end. Computed once for the whole
   * record -- it does not depend on where the clock is. */
  const alerts = useMemo(
    () => (sim.data ? allAlerts(sim.data.stations) : []), [sim.data])
  const ledger = useMemo(() => ledgerAt(alerts, hour), [alerts, hour])
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
    const worst = [...graded].sort((a, c) => BAND_ORDER[c.band] - BAND_ORDER[a.band])[0]
    setSelected(worst.s.id)
    // graded is deliberately absent from the deps: this must run on the first
    // load and never again, and listing it would re-arm the effect every hour.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.data])

  const chosen = sim.data?.stations.find((s) => s.id === selected) ?? null

  return (
    <div className="sheet network">
      {/* No VISIBLE page title: the top bar already says which page this is,
          and a page-sized heading repeating it pushed the map -- the actual
          content -- below the fold on a laptop.
          The heading still has to exist. A document with no h1 gives a screen
          reader nothing to announce and no way to jump to the content, and
          removing the visible one had quietly removed the only one. */}
      <h1 className="sr-only">Network</h1>

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
        <label>Step
          <select value={stepMin} onChange={(e) => setStepMin(+e.target.value)}>
            <option value={15}>15 min</option>
            <option value={30}>30 min</option>
            <option value={60}>1 hour</option>
            <option value={180}>3 hours</option>
          </select>
        </label>
        <label>Chart
          <select value={windowH} onChange={(e) => setWindowH(+e.target.value)}>
            <option value={24}>Last 24 hours</option>
            <option value={72}>Last 3 days</option>
            <option value={168}>Last 7 days</option>
            <option value={0}>Whole record</option>
          </select>
        </label>
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
            {flagged.filter((r) => r.band === 'WATCH').length} watch · day{' '}
            {(hour * (sim.data?.step_minutes ?? 15) / 1440).toFixed(1)} of{' '}
            {(nSteps * (sim.data?.step_minutes ?? 15) / 1440).toFixed(0)}
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
        <details className="netsec" open>
          <summary className="belowhead">
            {chosen ? chosen.name : 'Selected station'}
          </summary>
          {!chosen || !sim.data
            ? <p className="muted small">Pick a station on the map or in the index below.</p>
            : (<>
                {/* One line, not a heading plus a meta block plus a paragraph.
                    Name, where it is, and whether a fault was planted here --
                    everything else was prose the reader had already read. */}
                <div className="stnhead">
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
                <StationChannels sim={sim.data} s={chosen} hour={hour} windowH={windowH} />
              </>)}
        </details>
      )}

      {net === 'sim' && (
        <details className="netsec" open>
          <summary className="belowhead">
            Alerts
            <span className="muted"> · {ledger.filter((a) => a.status === 'OPEN').length} open
            of {ledger.length} raised so far</span>
          </summary>
          <AlertList sim={sim.data} rows={ledger} hour={hour} onSelect={setSelected} />
        </details>
      )}

      {net === 'sim' && (
        <details className="netsec" open>
          <summary className="belowhead">
            Station index
            <span className="muted"> · {graded.length} stations, {flagged.length} flagged now</span>
          </summary>
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
                        {bad > 0 && <b className="flagged">{bad}</b>}
                        {ungradedCount(rows) === rows.length && (
                          <em className="ungraded" title={UNGRADED_WHY}>ungraded</em>)}
                        <span className="n">{rows.length}</span>
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
    return <div className="alertbox"><p className="muted small empty">
      No alert has been raised yet. Run the clock.
    </p></div>
  }
  return (
    <div className="alertbox">
      <table className="alerttab">
        <thead>
          <tr>
            <th>Raised</th><th>Station</th><th>State</th>
            <th>Channel</th><th>Status</th><th>Grade</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id} className={a.status === 'CLOSED' ? 'closed' : undefined}
                onClick={() => onSelect(a.s.id)} tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter') onSelect(a.s.id) }}>
              <td className="mono when">{sim ? timeLabel(sim, a.from) : '—'}</td>
              <td className="stncell">{a.s.name}</td>
              <td className="mono muted">{a.s.state}</td>
              <td className="mono">{CH[a.ch]}</td>
              <td className="mono status">
                {a.status === 'OPEN'
                  ? <span className="st-open">open · {hour - a.from + 1} h</span>
                  : <span className="st-closed">closed · {a.closedAt! - a.from} h</span>}
              </td>
              <td>
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
