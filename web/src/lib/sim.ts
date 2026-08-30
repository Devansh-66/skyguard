/* Decoding and grading helpers for the simulated network.
 *
 * Kept out of the component because none of it is about rendering: it is the
 * inverse of what simulate/faults_and_export.py wrote, and it has to stay the
 * exact inverse. Every function here has a counterpart in that file, and the
 * two are only correct together.
 */
import { BAND, type Band, type SimMap, type SimStation } from '../api/mapTypes'

/** Base64 to bytes. The readings are stored this way because 344 stations by
 *  240 frames by three channels is a quarter of a million numbers, and JSON
 *  arrays of those cost roughly six times what the bytes do. */
export function b64bytes(s: string): Uint8Array {
  const bin = atob(s)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

/** Decoded readings, cached on the station object.
 *
 * Decoding is cheap but not free, and the clock repaints on every frame; doing
 * this per frame per station showed up as a stutter while scrubbing. */
const cache = new WeakMap<SimStation, Record<string, Uint8Array>>()

export function readings(s: SimStation, ch: 'temp' | 'rh' | 'pres'): Uint8Array {
  let byStation = cache.get(s)
  if (!byStation) { byStation = {}; cache.set(s, byStation) }
  if (!byStation[ch]) {
    byStation[ch] = b64bytes(ch === 'temp' ? s.vt : ch === 'rh' ? s.vh : s.vp)
  }
  return byStation[ch]
}

/** One reading in its own units, or null where the station did not report.
 *  Byte 0 is the missing marker, so the usable band is 1..255. */
export function readingAt(
  sim: SimMap, s: SimStation, ch: 'temp' | 'rh' | 'pres', frame: number,
): number | null {
  const b = readings(s, ch)[frame]
  if (b === undefined || b === 0) return null
  const [lo, hi] = sim.range[ch]
  return lo + ((b - 1) / 254) * (hi - lo)
}

/** The grade at an hour, for one channel or for the worst of them. */
export function bandAt(
  s: SimStation, key: 'health' | 'temp' | 'rh' | 'pres', hour: number,
): Band {
  const str = key === 'health' ? s.g
    : key === 'temp' ? s.gt : key === 'rh' ? s.gh : s.gp
  return BAND[str?.[hour]] ?? 'NODATA'
}

/** THE RECORD IS INDEXED IN STEPS, NOT HOURS.
 *
 * A step is `step_minutes` long -- 15 in the current export. Grades exist at
 * every step; readings are shipped every `field_every` steps because they cost
 * a hundred times more to send. Conflating the two indexes silently plots the
 * wrong day, which is why neither is ever called "hour" any more.
 */
export function frameOf(sim: SimMap, step: number): number {
  return Math.min(Math.floor(step / (sim.field_every || 1)), (sim.n_fields || 1) - 1)
}

/** How many steps make up a given number of minutes. */
export function stepsPerMinutes(sim: SimMap, minutes: number): number {
  return Math.max(1, Math.round(minutes / (sim.step_minutes || 15)))
}

export function timeLabel(sim: SimMap, step: number): string {
  const t = new Date(sim.t0 + 'Z')
  t.setUTCMinutes(t.getUTCMinutes() + step * (sim.step_minutes || 15))
  return t.toISOString().slice(0, 16).replace('T', ' ') + 'Z'
}

/** Did the station report anything at this hour?
 *
 * This separates the two situations a "-" grade covers. A station that sent
 * nothing has no reading; a station whose grade could not be COMPUTED still has
 * one. The island groups are the second case -- neighbour differencing needs
 * three stations within 250 km and Andaman, Nicobar and Lakshadweep do not have
 * them -- and calling that "no data" beside a valid 35.7 C reading reads as a
 * dead sensor, which is the opposite of the truth.
 */
export function reported(
  sim: SimMap, s: SimStation, key: 'health' | 'temp' | 'rh' | 'pres', hour: number,
): boolean {
  const f = frameOf(sim, hour)
  const chans: ('temp' | 'rh' | 'pres')[] =
    key === 'health' ? ['temp', 'rh', 'pres'] : [key]
  return chans.some((c) => readingAt(sim, s, c, f) != null)
}
