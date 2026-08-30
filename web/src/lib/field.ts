/* The channel fields: temperature, humidity and pressure as continuous surfaces.
 *
 * Ported from the static console. The stations are points and the weather is
 * not, so a map of coloured dots asks the reader to do the interpolation in
 * their head -- which is exactly the thing a field map is for.
 *
 * Inverse distance weighting, power 2, over the eight nearest stations to each
 * cell. It is the standard first choice for scattered meteorological data, it
 * honours the observations exactly at the stations, and it needs no fitting.
 * Kriging would be defensible and would cost a variogram per frame per channel
 * for a difference nobody would see at this size.
 */
import type { SimMap, SimStation } from '../api/mapTypes'
import { readings } from './sim'

export const FIELD_W = 116, FIELD_H = 128, FIELD_K = 8

/** The grid's extent. Fixed, and India-sized: the field is interpolated from
 *  Indian stations, so painting it across an ocean would be inventing weather
 *  from nothing. The basemap under it still shows the world. */
export const MAP_BOX = { lon0: 67.3, lon1: 97.8, lat0: 6.4, lat1: 37.4 }

/* Meteorological ramps. Temperature runs cold blue to hot red through the
 * conventional cyan-green-yellow; humidity runs dry brown to wet blue-green;
 * pressure runs low purple through white to high orange.
 *
 * These are the one place the five-colour rule does not hold, deliberately: a
 * continuous quantity needs a continuous scale, and red/green/blue/white/black
 * cannot express "slightly warmer". The rule governs the STATION markers, where
 * every colour has to mean a verdict. */
const RAMPS: Record<string, number[][]> = {
  temp: [[8, 32, 120], [20, 110, 200], [60, 180, 190], [120, 200, 110],
         [240, 220, 90], [240, 150, 50], [210, 60, 40], [140, 20, 30]],
  rh: [[120, 80, 40], [180, 150, 90], [225, 215, 175], [170, 215, 200],
       [70, 175, 180], [30, 110, 165], [15, 55, 120]],
  pres: [[70, 30, 110], [60, 90, 180], [150, 190, 225], [245, 245, 240],
         [245, 200, 130], [230, 140, 60], [170, 70, 35]],
}

export function rampAt(name: string, u: number): [number, number, number] {
  const c = RAMPS[name]
  const x = Math.max(0, Math.min(0.9999, u)) * (c.length - 1)
  const i = Math.floor(x), f = x - i
  const a = c[i], b = c[Math.min(i + 1, c.length - 1)]
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f,
          a[2] + (b[2] - a[2]) * f]
}

/** Which stations feed each grid cell, and how much.
 *
 * Depends only on geometry, so it survives every frame and every channel.
 * Computing it per frame made scrubbing the clock crawl: it is 15,000 cells
 * against 344 stations, and the clock repaints on every step. */
let _idx: { idx: Int16Array; wt: Float32Array; n: number } | null = null

export function fieldIndex(rows: SimStation[]) {
  if (_idx && _idx.n === rows.length) return _idx
  const idx = new Int16Array(FIELD_W * FIELD_H * FIELD_K)
  const wt = new Float32Array(FIELD_W * FIELD_H * FIELD_K)
  const n = rows.length
  const d = new Float64Array(n)
  for (let gy = 0; gy < FIELD_H; gy++) {
    const lat = MAP_BOX.lat1 - ((gy + 0.5) / FIELD_H) * (MAP_BOX.lat1 - MAP_BOX.lat0)
    for (let gx = 0; gx < FIELD_W; gx++) {
      const lon = MAP_BOX.lon0 + ((gx + 0.5) / FIELD_W) * (MAP_BOX.lon1 - MAP_BOX.lon0)
      for (let i = 0; i < n; i++) {
        const dx = (rows[i].lon - lon) * Math.cos((lat * Math.PI) / 180)
        const dy = rows[i].lat - lat
        d[i] = dx * dx + dy * dy
      }
      const order = Array.from({ length: n }, (_, i) => i)
        .sort((a, b) => d[a] - d[b]).slice(0, FIELD_K)
      const base = (gy * FIELD_W + gx) * FIELD_K
      let sum = 0
      for (let k = 0; k < FIELD_K; k++) {
        const w = 1.0 / Math.max(d[order[k]], 1e-4)   // power 2 on distance
        idx[base + k] = order[k]
        wt[base + k] = w
        sum += w
      }
      for (let k = 0; k < FIELD_K; k++) wt[base + k] /= sum
    }
  }
  _idx = { idx, wt, n }
  return _idx
}

/** One field, as a data URL ready for an image overlay.
 *
 * The values are interpolated in their ENCODED form -- 0..1 across the
 * channel's fixed range -- rather than in units. The ramp only needs a
 * position, converting 15,000 cells to degrees would change nothing on screen,
 * and the encoded band is where the missing marker lives. */
export function paintField(
  ch: 'temp' | 'rh' | 'pres', rows: SimStation[], frame: number,
): string | null {
  if (!rows.length) return null
  const { idx, wt } = fieldIndex(rows)
  const vals = new Float32Array(rows.length)
  const ok = new Uint8Array(rows.length)
  for (let i = 0; i < rows.length; i++) {
    const b = readings(rows[i], ch)[frame]
    ok[i] = !b ? 0 : 1
    vals[i] = !b ? 0 : (b - 1) / 254
  }
  const cv = document.createElement('canvas')
  cv.width = FIELD_W; cv.height = FIELD_H
  const ctx = cv.getContext('2d')
  if (!ctx) return null
  const img = ctx.createImageData(FIELD_W, FIELD_H)
  const d = img.data
  for (let c = 0; c < FIELD_W * FIELD_H; c++) {
    const base = c * FIELD_K
    let acc = 0, wsum = 0
    for (let k = 0; k < FIELD_K; k++) {
      const si = idx[base + k]
      if (!ok[si]) continue
      acc += vals[si] * wt[base + k]
      wsum += wt[base + k]
    }
    const p = c * 4
    // No station reported anywhere near this cell: leave it transparent rather
    // than painting the ramp's low end, which would read as real cold.
    if (wsum <= 0) { d[p + 3] = 0; continue }
    const col = rampAt(ch, acc / wsum)
    d[p] = col[0]; d[p + 1] = col[1]; d[p + 2] = col[2]; d[p + 3] = 255
  }
  ctx.putImageData(img, 0, 0)
  return cv.toDataURL()
}

/** The ramp as CSS, for the legend under the map. */
export function rampCss(ch: string): string {
  const stops = Array.from({ length: 24 }, (_, i) => {
    const c = rampAt(ch, i / 23)
    return `rgb(${c[0] | 0},${c[1] | 0},${c[2] | 0})`
  })
  return `linear-gradient(to right, ${stops.join(',')})`
}

/** What each field is, in units, for the legend ends. */
export function fieldRange(sim: SimMap, ch: 'temp' | 'rh' | 'pres') {
  const [lo, hi] = sim.range[ch]
  const unit = ch === 'temp' ? '°C' : ch === 'rh' ? '%' : 'hPa'
  return { lo, hi, unit }
}
