/* The band vocabulary, shared by every surface that shows a grade.
 *
 * Lifted out of the network page when the maintenance board began showing the
 * same simulated sensors: importing it from there dragged Leaflet into the
 * board's bundle, and a page with no map should not pay for one.
 */
import { type Band, type SimMap, type SimStation } from '../api/mapTypes'
import { reported } from './sim'

/* Only two of these are colours. A station with nothing wrong carries no hue at
 * all, so every coloured dot on the map is one worth looking at. */
export const HUE: Record<Band, string | null> = {
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
export const BAND_LABEL: Record<Band, string> = {
  OK: 'OK', WATCH: 'WATCH', FAULT: 'FAULT', NODATA: 'NOT REPORTING',
}
export const UNGRADED = 'NO NEIGHBOURS'
export const UNGRADED_WHY =
  'Fewer than three stations within 250 km, so there is nothing to difference '
  + 'against. The reading is fine; the method does not reach here.'

/** A grade of "-" beside a real reading means UNGRADED, not missing. */

export function label(
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

export function why(band: Band): string | undefined {
  return band === 'NODATA' ? UNGRADED_WHY : undefined
}
