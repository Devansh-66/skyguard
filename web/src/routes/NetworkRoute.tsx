/* The network map, ported from the static console into the app.
 *
 * WHY THIS EXISTS TWICE, BRIEFLY
 *
 * The map, the clock and the station list were built in dashboard/console.html
 * while the app carried the landing page and the board. That was a mistake --
 * two frontends that diverged -- and this is the first half of undoing it. The
 * console is not deleted until this reaches parity, because the console is the
 * half with the recent work in it.
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
import { bandAt, frameOf, readingAt, reported, timeLabel } from '../lib/sim'
import { Async } from '../components/Async'

type Net = 'sim' | 'wdqms' | 'arm'
type BaseKey = 'imagery' | 'muted' | 'dark'
type Channel = 'health' | 'temp' | 'rh' | 'pres'

/* Only two of these are colours. A station with nothing wrong carries no hue at
 * all, so every coloured dot on the map is one worth looking at. */
const HUE: Record<Band, string | null> = {
  OK: null, WATCH: '#1D6FE0', FAULT: '#E01B24', NODATA: '#8C8172',
}

/* NODATA IS NOT ONE SITUATION. It covers a station that reported nothing, and a
 * station that reported perfectly well and cannot be GRADED -- and those need
 * different words, because the second was showing "NODATA" beside a valid
 * 35.7 C reading and reading as a broken sensor.
 *
 * Ten stations can never be graded at all: the island groups, Andaman & Nicobar
 * and Lakshadweep, have fewer than three stations within 250 km, and neighbour
 * differencing has nothing to difference against. That is a real limit of the
 * method rather than a gap in the data, and it is exactly where a single-station
 * check has to take over. Naming it is more useful than hiding it. */
const BAND_LABEL: Record<Band, string> = {
  OK: 'OK', WATCH: 'WATCH', FAULT: 'FAULT', NODATA: 'NOT REPORTING',
}
const UNGRADED = 'NO NEIGHBOURS'
const UNGRADED_WHY =
  'Fewer than three stations within 250 km, so there is nothing to difference '
  + 'against. The reading is fine; the method does not reach here.'

/** A grade of "-" beside a real reading means UNGRADED, not missing. */
function label(
  sim: SimMap | undefined, s: SimStation,
  ch: 'health' | 'temp' | 'rh' | 'pres', hour: number, band: Band,
): string {
  if (band !== 'NODATA') return BAND_LABEL[band]
  if (!sim) return BAND_LABEL.NODATA
  return reported(sim, s, ch, hour) ? UNGRADED : BAND_LABEL.NODATA
}

/** How many of these carry no grade at all.
 *
 * A group where every station is ungraded has not been found "clear" -- nothing
 * looked at it. Saying "all 3 clear" of the Andaman stations claimed a verdict
 * the pipeline never reached. */
function ungradedCount(rows: { band: Band }[]): number {
  return rows.filter((r) => r.band === 'NODATA').length
}

function why(band: Band): string | undefined {
  return band === 'NODATA' ? UNGRADED_WHY : undefined
}

const BASES: Record<BaseKey, { label: string; filter: string; ok: string; okOpacity: number }> = {
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
    if (pane) pane.style.filter = filter
  }, [map, filter])
  return null
}

function FitIndiaOnce() {
  const map = useMap()
  useEffect(() => { map.fitBounds(INDIA, { padding: [24, 24] }) }, [map])
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
  const [hour, setHour] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  // Both of these belong to the reader, not to the data, so neither is derived
  // from it and neither resets when the clock moves.
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [acked, setAcked] = useState<Set<string>>(new Set())

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
  const chosen = sim.data?.stations.find((s) => s.id === selected) ?? null

  return (
    <div className="sheet network">
      <header className="masthead">
        <div>
          <h1 className="wordmark">Network</h1>
          <p className="masthead-sub">
            {net === 'sim'
              ? 'Simulated readings at 344 real IMD locations, 30 days at 15 minutes.'
              : net === 'wdqms'
                ? "Real stations operated by India, graded from WMO's quality monitoring."
                : 'The nine ARM instruments the detector was measured against.'}
          </p>
        </div>
      </header>

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
        <label className="cbx">
          <input type="checkbox" checked={showStates}
                 onChange={(e) => setShowStates(e.target.checked)} />
          State outlines
        </label>
      </div>

      <Async query={tiles}>
        {(t) => (
          <div className="mapwrap">
            <MapContainer center={[22.5, 82]} zoom={4} scrollWheelZoom
                          zoomSnap={0.25} zoomDelta={0.5} wheelPxPerZoomLevel={170}
                          className="netmap">
              <FitIndiaOnce />
              <TilePaneFilter filter={b.filter} />
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
                 onChange={(e) => setHour(+e.target.value)} />
          <span className="mono">{timeLabel(sim.data, hour)}</span>
          <span className="mono muted">
            {flagged.filter((r) => r.band === 'FAULT').length} fault ·{' '}
            {flagged.filter((r) => r.band === 'WATCH').length} watch · hour {hour + 1}/{nSteps}
          </span>
        </div>
      )}

      {net === 'sim' && (
        <div className="netbelow">
          <section>
            <div className="belowhead">All stations · {flagged.length} flagged of {graded.length}</div>
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

          <section>
            <div className="belowhead">
              {chosen ? chosen.name : 'Selected station'}
            </div>
            {!chosen || !sim.data
              ? <p className="muted small">Click a station on the map, or a row in the
                  list, to see its three channels across the whole month.</p>
              : <StationChannels sim={sim.data} s={chosen} hour={hour} />}
          </section>

          <section>
            <div className="belowhead">
              Alerts · {flagged.filter((r) => !acked.has(r.s.id + ':' + r.band)).length} open
            </div>
            <AlertList rows={flagged} acked={acked} onAck={(k) => {
              const next = new Set(acked)
              if (next.has(k)) next.delete(k); else next.add(k)
              setAcked(next)
            }} onSelect={setSelected} />
          </section>
        </div>
      )}
    </div>
  )
}

/** One station's three channels across the month, with the hours this project
 *  graded as watch or fault shaded behind each trace. The reading and the
 *  verdict on the reading, on one axis. */
function StationChannels({ sim, s, hour }: {
  sim: NonNullable<ReturnType<typeof useSimMap>['data']>
  s: SimStation
  hour: number
}) {
  const CH: ('temp' | 'rh' | 'pres')[] = ['temp', 'rh', 'pres']
  const NAME = { temp: 'Temperature', rh: 'Relative humidity', pres: 'Pressure (MSL)' }
  const UNIT = { temp: '°C', rh: '%', pres: 'hPa' }
  const every = sim.field_every || 3
  const nf = sim.n_fields || 1
  const cur = frameOf(sim, hour)

  return (
    <>
      {CH.map((ch) => {
        const vals = Array.from({ length: nf }, (_, i) => readingAt(sim, s, ch, i))
        const fin = vals.filter((v): v is number => v != null)
        if (!fin.length) return null
        let lo = Math.min(...fin), hi = Math.max(...fin)
        const pad = (hi - lo) * 0.12 || 1
        lo -= pad; hi += pad
        const W = 620, H = 84, P = 4
        const x = (i: number) => P + (i / Math.max(nf - 1, 1)) * (W - 2 * P)
        const y = (v: number) => P + ((hi - v) / (hi - lo)) * (H - 2 * P)
        let d = '', pen = false
        vals.forEach((v, i) => {
          if (v == null) { pen = false; return }
          d += (pen ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1) + ' '
          pen = true
        })
        const bands = []
        for (let i = 0; i < nf; i++) {
          const g = bandAt(s, ch, Math.min(i * every, s.g.length - 1))
          if (g === 'WATCH' || g === 'FAULT') {
            bands.push(<rect key={i} x={x(i)} y={0} width={Math.max(W / nf, 1.2)} height={H}
                             fill={HUE[g]!} opacity={g === 'FAULT' ? 0.2 : 0.12} />)
          }
        }
        const now = vals[cur]
        const band = bandAt(s, ch, hour)
        // A reading with no grade is not a missing reading.
        const ungraded = band === 'NODATA' && now != null
        return (
          <div className="chan" key={ch}>
            <div className="chan-head">
              <strong>{NAME[ch]}</strong>
              <span className="mono muted">{UNIT[ch]}</span>
              {band !== 'OK' && (
                <span className="badge" title={why(band)}
                      style={{ color: HUE[band] ?? 'var(--ink-3)',
                               borderColor: HUE[band] ?? 'var(--rule-edge)' }}>
                  {ungraded ? UNGRADED : BAND_LABEL[band]}
                </span>)}
              <span className="mono" style={{ marginLeft: 'auto' }}>
                {now == null ? 'no data' : now.toFixed(1) + ' ' + UNIT[ch]}
              </span>
            </div>
            <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="chansvg">
              <rect width={W} height={H} fill="var(--surface)" />
              {bands}
              <path d={d.trim()} fill="none" stroke="var(--ink)" strokeWidth={1.1}
                    vectorEffect="non-scaling-stroke" />
              <line x1={x(cur)} x2={x(cur)} y1={0} y2={H} stroke="var(--ink)"
                    strokeWidth={1} strokeDasharray="3 2" />
            </svg>
          </div>
        )
      })}
      <p className="small muted">
        Shading is this project's own verdict, not the injected truth.
        {s.fault
          ? ` Injected: ${s.fault.kind} on ${s.fault.channel} from hour ${s.fault.onset_hour} — shown for checking; the grader never saw it.`
          : ' No fault was injected into this station.'}
      </p>
    </>
  )
}

/** Open and acknowledged, and honest about the difference.
 *
 * An alert closes BY ITSELF when the station returns to OK, which is a real
 * closure -- the condition ended -- and is not the same as anyone having dealt
 * with it. Acknowledgement is keyed to the station AND its band, so a station
 * escalating from watch to fault re-opens rather than staying silenced. None of
 * it is persisted; there is no store and no work order behind it, and saying so
 * is better than implying otherwise. */
function AlertList({ rows, acked, onAck, onSelect }: {
  rows: { s: SimStation; band: Band }[]
  acked: Set<string>
  onAck: (k: string) => void
  onSelect: (id: string) => void
}) {
  const open = rows.filter((r) => !acked.has(r.s.id + ':' + r.band))
  const quiet = rows.filter((r) => acked.has(r.s.id + ':' + r.band))
  const item = (r: { s: SimStation; band: Band }, isAck: boolean) => (
    <div className="alertrow" key={r.s.id + r.band}
         style={{ borderLeftColor: HUE[r.band] ?? 'var(--rule)' }}>
      <button className="alertname" onClick={() => onSelect(r.s.id)}>{r.s.name}</button>
      <span className="badge" style={{ color: HUE[r.band]!, borderColor: HUE[r.band]! }}>{BAND_LABEL[r.band]}</span>
      <button className="btn ghost tiny" onClick={() => onAck(r.s.id + ':' + r.band)}>
        {isAck ? 'Reopen' : 'Acknowledge'}
      </button>
    </div>
  )
  return (
    <>
      {open.length ? open.map((r) => item(r, false))
        : <p className="muted small">Nothing open at this hour. An alert closes by
            itself when the station returns to OK.</p>}
      {quiet.length > 0 && (
        <>
          <div className="belowhead" style={{ marginTop: 14 }}>Acknowledged · {quiet.length}</div>
          {quiet.map((r) => item(r, true))}
        </>
      )}
      <p className="small muted">
        Acknowledgement is held in this tab only — no store, no assignment, no
        work order. A station escalating from watch to fault re-opens.
      </p>
    </>
  )
}
