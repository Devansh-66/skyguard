/* The map datasets, as /api/map/* actually returns them.
 *
 * Written from the exporters that produce these files -- simulate/
 * faults_and_export.py, dashboard/export_wdqms.py, dashboard/export_arm_sites.py
 * -- and checked against a live response. Regenerate the files with the command
 * each endpoint names in its 404.
 *
 * THE ENCODINGS LOOK ODD AND ARE NOT ARBITRARY.
 *
 * A grade is one character per hour per station: 344 stations times 720 hours
 * times three channels is 743,000 values, and a string of "0"/"1"/"2"/"-" is the
 * smallest thing that survives JSON without a decoder. Readings are base64 bytes
 * against a fixed per-channel range for the same reason. Both are decoded once
 * per station on first use and cached on the object.
 */

/** One simulated station. Real IMD location, generated readings. */
export interface SimStation {
  id: string
  name: string
  /** Real state, assigned by point-in-polygon at export time. */
  state: string
  lat: number
  lon: number
  elev: number
  /** Grade of the worst channel, one char per STEP. "0" ok, "1" watch,
   *  "2" fault, "-" no data. */
  g: string
  /** The same, per channel. */
  gt: string
  gh: string
  gp: string
  /** Readings, base64 uint8, every `field_every` steps, scaled into `range`.
   *  0 means missing, so the usable band is 1..255. */
  vt: string
  vh: string
  vp: string
  /** The injected fault, present only where one was injected. Exported so the
   *  interface can show it BESIDE the detection; the grader never saw it. */
  fault: { kind: string; channel: string; onset_hour: number } | null
}

export interface SimMap {
  note: string
  /** ISO timestamp of hour 0. */
  t0: string
  step_hours: number
  /** Minutes per step. The record is indexed in steps, not hours. */
  step_minutes: number
  n_steps: number
  /** STEPS between reading frames. Grades exist every step; readings are
   *  shipped more sparsely because base64 bytes do not compress. */
  field_every: number
  n_fields: number
  range: Record<'temp' | 'rh' | 'pres', [number, number]>
  field_note?: Record<string, string>
  legend: Record<string, string>
  stations: SimStation[]
}

/** A real IMD station with WMO's observation-minus-background departures. */
export interface WdqmsStation {
  id: string
  name: string
  region: string
  state_source: 'polygon' | 'computed'
  latitude: number
  longitude: number
  in_india: boolean
  dep: Record<string, { mean: number; spread: number | null; n: number; centres: number; z: number }>
  health: { state: string; severity: number; channel: string; confident: boolean }
  near: { n: number; flagged: number; share: number | null; verdict: string | null }
  series: Record<string, (number | null)[] | string[]>
}

export interface WdqmsMap {
  note: string
  source: string
  centres: string[]
  date: string
  stations: WdqmsStation[]
}

/** An ARM validation instrument. */
export interface ArmSite {
  id: string
  place: string
  observatory: string
  facility: string
  latitude: number
  longitude: number
  reports: number
}

export interface ArmMap {
  source: string
  note: string
  stations: ArmSite[]
}

export type Band = 'OK' | 'WATCH' | 'FAULT' | 'NODATA'

/** Grade character to band. The exporter writes these four and nothing else. */
export const BAND: Record<string, Band> = {
  '0': 'OK', '1': 'WATCH', '2': 'FAULT', '-': 'NODATA',
}

/** Paint order: worst last, so a fault is never drawn under a healthy
 *  neighbour. */
export const BAND_ORDER: Record<Band, number> = {
  NODATA: -1, OK: 0, WATCH: 1, FAULT: 2,
}
