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
  useArmMap, useBoundaryGeo, useLiveStation, useSimMap, useStatesGeo,
  useTileStatus, useWdqmsMap,
} from '../api/queries'
import { BAND_ORDER, type Band, type SimMap, type SimStation } from '../api/mapTypes'
import { bandAt, frameOf, stepsPerMinutes, timeLabel } from '../lib/sim'
import { BAND_LABEL, HUE, UNGRADED_WHY, label, why } from '../lib/bands'
import { allAlerts, ledgerAt } from '../lib/alerts'
import { StationChannels } from '../components/StationChannels'
import { MAP_BOX, fieldRange, paintField, rampCss } from '../lib/field'
import L from 'leaflet'
import { Async } from '../components/Async'
import { liveCommand, resetTrace, useLive } from '../lib/useLive'
import { usePageTitle } from '../lib/title'

type Net = 'sim' | 'wdqms' | 'arm'
type BaseKey = 'imagery' | 'muted' | 'dark'
type Channel = 'health' | 'temp' | 'rh' | 'pres'

/** How many of these carry no grade at all.
 *
 * A group where every station is ungraded has not been found "clear" -- nothing
 * looked at it. Saying "all 3 clear" of the Andaman stations claimed a verdict
 * the pipeline never reached. */
function ungradedCount(rows: { band: Band }[]): number {
  return rows.filter((r) => r.band === 'NODATA').length
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

export function NetworkRoute() {
  usePageTitle('Network')
  const tiles = useTileStatus()
  const sim = useSimMap()
  const wdqms = useWdqmsMap()
  const arm = useArmMap()
  const states = useStatesGeo()
  const boundary = useBoundaryGeo()
  const node = useLiveStation()
  const live = useLive(import.meta.env.VITE_API_BASE ?? '')

  const [net, setNet] = useState<Net>('sim')
  const [base, setBase] = useState<BaseKey>('imagery')
  const [channel, setChannel] = useState<Channel>('health')
  const [showStates, setShowStates] = useState(false)
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

  const ledgerWithNode = useMemo(() => {
    const b = live.grade?.band
    if (!nodeStation || !b || (b !== 'watch' && b !== 'fault')) return ledger
    return [{
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
    const worst = [...graded].sort((a, c) => BAND_ORDER[c.band] - BAND_ORDER[a.band])[0]
    setSelected(worst.s.id)
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
          <button type="button" className="btn ghost" onClick={() => setPlaying((p) => !p)}>
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
      {field && sim.data && (
        <div className="fieldkey">
          <span className="mono">{fieldRange(sim.data, field).lo} {fieldRange(sim.data, field).unit}</span>
          <span className="fieldramp" style={{ background: rampCss(field) }} />
          <span className="mono">{fieldRange(sim.data, field).hi} {fieldRange(sim.data, field).unit}</span>
          <span className="small muted">
            Interpolated from 344 stations by inverse distance weighting,
            clipped to the coastline. The surface is drawn; only the dots are
            measured.
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
            {nodeSelected && node.data ? node.data.name
              : chosen ? chosen.name : 'Selected station'}
          </summary>
          {nodeSelected && node.data && sim.data
            ? (<>
                <div className="stnhead">
                  <span className="mono muted">
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
                  Readings arrive at <code>/api/ingest</code>, are screened
                  against the WMO rails, differenced against six neighbours
                  within 120 km, and stored. The pen reaches as far as the node
                  has reported — {live.frame} frames — rather than to the
                  slider, because it cannot draw a reading it has not sent.
                </p>
              </>)
            : !chosen || !sim.data
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
            <span className="muted"> · {ledgerWithNode.filter((a) => a.status === 'OPEN').length} open
            of {ledgerWithNode.length} raised so far</span>
          </summary>
          <AlertList sim={sim.data} rows={ledgerWithNode} hour={hour} onSelect={setSelected} />
        </details>
      )}

      {net === 'sim' && (
        <details className="netsec" open>
          <summary className="belowhead">
            Station index
            <span className="muted"> · {graded.length} simulated
              {node.data ? ' + 1 live' : ''}, {flagged.length} flagged now</span>
          </summary>
          <div className="netrail">
              {/* THE LIVE NODE IN THE INDEX, not only on the map. It is a
                  station in this network and someone working down a list
                  should find it there. First, because it is the only one
                  reporting now. */}
              {node.data && (
                <details open>
                  <summary>
                    <span>Live</span>
                    <span className="state-count mono">
                      {live.running ? <b className="flagged">reporting</b> : '1'}
                    </span>
                  </summary>
                  <button type="button"
                    className={'stn' + (nodeSelected ? ' on' : '')}
                    onClick={() => setSelected(node.data!.id)}>
                    <span className="spine" style={{
                      background: live.grade?.band === 'fault' ? HUE.FAULT!
                        : live.grade?.band === 'watch' ? HUE.WATCH!
                          : 'var(--rule)',
                    }} />
                    <span className="card-main">
                      <span className="card-station">{node.data.name}</span>
                      <span className="card-meta num">
                        {node.data.elev} m · {node.data.state}
                      </span>
                    </span>
                    {live.grade && live.grade.band !== 'ok'
                      && live.grade.band !== 'learning' && (
                      <span className="badge" style={{
                        color: HUE[live.grade.band === 'fault' ? 'FAULT' : 'WATCH']!,
                        borderColor: HUE[live.grade.band === 'fault' ? 'FAULT' : 'WATCH']!,
                      }}>{live.grade.band}</span>
                    )}
                  </button>
                </details>
              )}
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
                      <button type="button" key={s.id}
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
                  ? <span className="st-open">
                      open · {(a as { openLabel?: string | null }).openLabel
                        ?? `${hour - a.from + 1} h`}
                    </span>
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
