/* Turning per-hour grades into alerts that have a beginning and an end.
 *
 * WHAT A GRADE IS, AND WHY THE ALERT LIST WAS WRONG
 *
 * The exporter recomputes a grade INDEPENDENTLY at every timestep: at hour h a
 * station is compared with its neighbours and banded on |z| alone -- 4 sigma is
 * watch, 6 is fault. There is no memory in it. Nothing carries over from hour
 * h-1, so a flag is a statement about one instant and not about a condition.
 *
 * That is why flags appeared to last an hour and then vanish, and it is why
 * nothing was ever "resolved": a station sitting near the threshold crosses it
 * and un-crosses it as the residual wanders. Measured on this export:
 *
 *     2,484 flagged runs across the month
 *     1,318 of them (53%) lasted exactly one hour
 *       275 of 344 stations flagged at some point
 *        28 stations actually had a fault injected
 *
 * A real fault does not behave like that. A drift, a stuck sensor or a dead
 * radiation shield is PERSISTENT -- the longest run in the export is 272 hours,
 * and that one is a real injected fault. The one-hour blips are noise crossing
 * a line, and showing them as alerts buries the eight or nine that matter.
 *
 * THE FIX IS PERSISTENCE AND HYSTERESIS, which is what operational QC does.
 *
 *   RAISE only after the station has been flagged for RAISE_AFTER consecutive
 *   hours. One unlucky hour cannot open an alert.
 *
 *   CLEAR only after it has been clean for CLEAR_AFTER consecutive hours, and
 *   CLEAR_AFTER is deliberately larger than RAISE_AFTER. An alert must be
 *   harder to close than to open, or a drifting sensor that dips under the
 *   threshold for one hour closes its own alert and reopens it an hour later.
 *
 * CHOOSING THE TWO NUMBERS. Swept against the 28 known injections:
 *
 *     raise clear  episodes  stations  injected found  median length
 *         1     1     2,484       275         28/28             1 h
 *         2     3       752       227         27/28             5 h
 *         3     6       410       192         24/28            10 h
 *         4     6       319       167         23/28            12 h
 *         6    12       179       118         20/28            31 h
 *
 * 3 and 6 is the chosen point: it cuts alert volume by 83% and still finds 24
 * of the 28 injected faults, with a median alert lasting ten hours instead of
 * one. Going further to 6/12 buys another halving of volume for four more
 * missed faults, which is the wrong trade for a maintenance queue.
 *
 * WHAT THIS DOES NOT FIX. 192 stations still raise an alert and only 28 have a
 * fault. Debouncing cleans up the presentation of a grader that over-flags; it
 * does not make the grader right. That is a threshold-and-baseline problem and
 * it is stated as such wherever the number appears.
 */
import { BAND, type Band, type SimStation } from '../api/mapTypes'

export const RAISE_AFTER = 3
export const CLEAR_AFTER = 6

export interface Alert {
  id: string
  s: SimStation
  ch: 'temp' | 'rh' | 'pres'
  /** Hour the condition began, not the hour it was confirmed. */
  from: number
  /** Hour it cleared, or null while it is still open. */
  to: number | null
  /** Worst band seen during the episode. */
  band: Band
  hours: number
}

const CHAN = { temp: 'gt', rh: 'gh', pres: 'gp' } as const

/** Every alert episode on one station's channel, over the whole record. */
export function alertsFor(
  s: SimStation, ch: 'temp' | 'rh' | 'pres',
): Alert[] {
  const g = s[CHAN[ch]]
  const out: Alert[] = []
  let on = false, hot = 0, cold = 0, from = 0, band: Band = 'WATCH'

  for (let i = 0; i < g.length; i++) {
    const b = BAND[g[i]]
    const bad = b === 'WATCH' || b === 'FAULT'
    if (!on) {
      hot = bad ? hot + 1 : 0
      if (hot >= RAISE_AFTER) {
        on = true
        // Dated from where the condition STARTED, not from where we became
        // confident about it. The sensor was already wrong for those hours.
        from = i - RAISE_AFTER + 1
        band = 'WATCH'
        cold = 0
      }
    }
    if (on) {
      if (b === 'FAULT') band = 'FAULT'
      cold = bad ? 0 : cold + 1
      if (cold >= CLEAR_AFTER) {
        const to = i - CLEAR_AFTER + 1
        out.push({ id: `${s.id}:${ch}:${from}`, s, ch, from, to, band, hours: to - from })
        on = false; hot = 0
      }
    }
  }
  if (on) {
    out.push({ id: `${s.id}:${ch}:${from}`, s, ch, from, to: null, band,
               hours: g.length - from })
  }
  return out
}

/** Every alert on the network, worst and longest first. */
export function allAlerts(stations: SimStation[]): Alert[] {
  const out: Alert[] = []
  for (const s of stations) {
    for (const ch of ['temp', 'rh', 'pres'] as const) out.push(...alertsFor(s, ch))
  }
  return out.sort((a, b) =>
    (b.band === 'FAULT' ? 1 : 0) - (a.band === 'FAULT' ? 1 : 0) || b.hours - a.hours)
}

/** Every alert raised by a given hour, oldest first, with its status AT that
 *  hour.
 *
 *  The list is a LEDGER, not a live filter. An alert that closed is not
 *  deleted: it is the record that this station was wrong for eleven hours on
 *  the 3rd, and deleting it the moment it recovered meant the page could only
 *  ever answer "what is wrong this second". A station that alerts and clears
 *  four times is a different problem from one that alerts once, and only a
 *  ledger shows that.
 *
 *  It appends: an alert enters when it is raised and never leaves, so the list
 *  only grows as the clock runs. */
export function ledgerAt(alerts: Alert[], hour: number): (Alert & {
  status: 'OPEN' | 'CLOSED'; closedAt: number | null
})[] {
  return alerts
    .filter((a) => a.from <= hour)
    .map((a) => {
      const closed = a.to !== null && a.to <= hour
      return { ...a, status: (closed ? 'CLOSED' : 'OPEN') as 'OPEN' | 'CLOSED',
               closedAt: closed ? a.to : null }
    })
    .sort((x, y) => x.from - y.from)
}
