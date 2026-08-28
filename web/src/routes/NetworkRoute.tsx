/* The network page: where SkyGuard is deployed, and where it was proved.
 *
 * WHY THERE ARE TWO LISTS AND ONLY ONE MAP
 *
 * These are two different claims and merging them would state a third that is
 * false. The map is the DEPLOYMENT network -- Indian stations, simulated from
 * ERA5, the thing this is built to watch. The table below it is the VALIDATION
 * set: real instruments at ARM observatories in Oklahoma, Alaska and the
 * Azores, used because ARM publishes fault reports written by engineers who
 * physically inspected the hardware, and no Indian network publishes anything
 * equivalent.
 *
 * Plotting the ARM masts on the same map would say "we monitor stations in
 * Oklahoma", which we do not. Leaving them out entirely leaves `sgpmetE37`
 * unexplained, which is how a real reader ended up asking what the name meant.
 * So both appear, named in full, and clearly separated.
 *
 * This page also replaces the link out to /console/console.html, which left the
 * application shell entirely -- the top bar disappeared and the visitor had no
 * way back except the browser's back button.
 */
import { MapContainer, CircleMarker, TileLayer, Tooltip } from 'react-leaflet'
import { useStations, useTileStatus } from '../api/queries'
import { SITES } from '../api/sites'
import { Async } from '../components/Async'
import { Callout } from '../components/Callout'
import type { Station } from '../api/types'

/** Health string to a token class. The station dot is also sized by health, so
 *  colour is never the only channel carrying it. */
function healthTone(h: string): 'ok' | 'sus' | 'bad' {
  const s = (h || '').toUpperCase()
  if (s.startsWith('FAIL')) return 'bad'
  if (s.startsWith('HEALTH')) return 'ok'
  return 'sus'
}

const TONE_COLOR: Record<string, string> = {
  ok: 'var(--verdigris)',
  sus: 'var(--amber)',
  bad: 'var(--oxide)',
}

export function NetworkRoute() {
  const stations = useStations()
  const tiles = useTileStatus()

  return (
    <div className="sheet network">
      <header className="masthead">
        <div>
          <h1 className="wordmark">Network</h1>
          <p className="masthead-sub">
            Where SkyGuard is deployed, and the instruments it was proved
            against.
          </p>
        </div>
      </header>

      {/* ---------------- deployment ---------------- */}
      <section className="plate">
        <span className="engraved">I · Deployment network</span>
        <h2 className="plate-title">The stations this watches</h2>
        <p className="plate-body">
          Ten stations across Assam and Maharashtra, simulated from ERA5
          reanalysis with realistic instrument noise. They stand in for an IMD
          network because no Indian operator publishes a per-instrument fault
          archive — which is exactly the gap this project exists to fill.
        </p>

        <div className="map-wrap">
          <Async query={tiles}>
            {(t) =>
              t.available ? (
                <MapContainer
                  center={[21.5, 82]}
                  zoom={5}
                  maxZoom={t.max_zoom}
                  scrollWheelZoom={false}
                  className="map"
                >
                  <TileLayer url={t.tile_template} maxZoom={t.max_zoom} attribution={t.attribution} />
                  {/* The official boundary is a separate overlay, served from
                      NCMRWF rather than drawn by us -- the depiction of a
                      national border is not something an application should
                      improvise. */}
                  <TileLayer url={t.boundary_template} maxZoom={t.max_zoom} />
                  {stations.data?.map((s) => {
                    const tone = healthTone(s.health?.station)
                    return (
                      <CircleMarker
                        key={s.name}
                        center={[s.latitude, s.longitude]}
                        radius={tone === 'bad' ? 8 : tone === 'sus' ? 6.5 : 5}
                        pathOptions={{
                          color: TONE_COLOR[tone],
                          fillColor: TONE_COLOR[tone],
                          fillOpacity: 0.55,
                          weight: 2,
                        }}
                      >
                        <Tooltip direction="top" offset={[0, -6]}>
                          <strong>{s.name}</strong>
                          <br />
                          {s.state} · {s.elevation} m
                          <br />
                          {s.health?.station}
                        </Tooltip>
                      </CircleMarker>
                    )
                  })}
                </MapContainer>
              ) : (
                <Callout tone="sus" title="The map cannot draw">
                  The tile service reports unavailable
                  {t.upstream_reachable && !t.upstream_reachable.basemap
                    ? ' and no route to the imagery upstream'
                    : ''}
                  . The station list below is unaffected — it does not come from
                  the tile service.
                </Callout>
              )
            }
          </Async>
        </div>

        <Async query={stations}>
          {(rows) => (
            <>
              <table className="stations">
                <thead>
                  <tr>
                    <th>Station</th>
                    <th>State</th>
                    <th className="r">Elev.</th>
                    <th>Neighbours</th>
                    <th>Health</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((s: Station) => (
                    <tr key={s.name}>
                      <td>{s.name}</td>
                      <td className="muted">{s.state}</td>
                      <td className="r num">{s.elevation} m</td>
                      <td className="muted small">{s.neighbours.join(', ') || '—'}</td>
                      <td>
                        <span className={'dot ' + healthTone(s.health?.station)} aria-hidden="true" />
                        <span className="mono small">{s.health?.station ?? '—'}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="small muted plate-caption">
                Neighbours are what makes differencing possible: a station with
                none cannot be checked against anything but its own past.
              </p>
            </>
          )}
        </Async>
      </section>

      {/* ---------------- validation ---------------- */}
      <section className="plate">
        <span className="engraved">II · Validation instruments</span>
        <h2 className="plate-title">Where the detector was actually proved</h2>
        <p className="plate-body">
          Every number on the maintenance board comes from these nine masts, not
          from the map above. They belong to the US Department of Energy's ARM
          programme, which publishes something no Indian network does: fault
          reports written by engineers who went out and inspected the instrument.
          Without a human-written answer key there is nothing to measure recall
          against.
        </p>
        <Callout tone="neutral" title="Why they are not on the map">
          They are in Oklahoma, Alaska and the Azores. Drawing them beside the
          Indian stations would say this network monitors them, which it does
          not. Two claims, two lists.
        </Callout>

        <table className="stations">
          <thead>
            <tr>
              <th>Code</th>
              <th>Place</th>
              <th>Observatory</th>
              <th>Facility</th>
              <th className="r">Lat</th>
              <th className="r">Lon</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(SITES).map(([code, s]) => (
              <tr key={code}>
                <td className="mono small">{code}</td>
                <td>
                  {s.place}
                  <span className="muted"> · {s.region}</span>
                </td>
                <td className="muted small">{s.observatory}</td>
                <td className="muted small">{s.facility}</td>
                <td className="r num small">{s.lat.toFixed(3)}</td>
                <td className="r num small">{s.lon.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small muted plate-caption">
          The code reads site · platform · facility: <span className="mono">sgp</span> is
          the Southern Great Plains observatory, <span className="mono">met</span> the
          surface meteorology system carrying temperature, pressure and humidity,
          and <span className="mono">E37</span> Extended Facility 37. Values read from
          the data files' own attributes, not looked up.
        </p>
      </section>
    </div>
  )
}
