/* One station's three channels across the month, with the hours this project
 * graded as watch or fault shaded behind each trace.
 *
 * Its own module because two pages draw it now -- the network map and the
 * maintenance board -- and reaching into the network page for it pulled Leaflet
 * into the board's bundle.
 */
import { type SimMap, type SimStation } from '../api/mapTypes'
import { bandAt, frameOf, readingAt, timeLabel } from '../lib/sim'
import type { Band } from '../api/mapTypes'
import { BAND_LABEL, HUE, UNGRADED, why } from '../lib/bands'

export function StationChannels({ sim, s, hour, windowH = 0, live }: {
  sim: SimMap
  s: SimStation
  /** Current position, in record steps. */
  hour: number
  /** Hours of history to draw, ending at the clock. 0 draws everything. */
  windowH?: number
  /* A STATION WHOSE READINGS ARRIVE, drawn by exactly this component.
   *
   * The live node reports at the same fifteen-minute steps as every simulated
   * station, so it belongs on the same axis with the same window control and
   * the same pen. Giving it a chart of its own implied two different kinds of
   * time where there is only one, and made a station look like a feature.
   *
   * Values are indexed by FRAME and sparse: a frame that has not arrived is
   * null and the pen lifts, which is what it already does for a gap in the
   * record. `upto` is how far the node has reported, which stands in for the
   * clock -- it cannot draw ahead of what it has sent. */
  live?: {
    byFrame: { temp: (number | null)[]; rh: (number | null)[]; pres: (number | null)[] }
    grades: string[]
    upto: number
  }
}) {
  const CH: ('temp' | 'rh' | 'pres')[] = ['temp', 'rh', 'pres']
  const NAME = { temp: 'Temperature', rh: 'Relative humidity', pres: 'Pressure (MSL)' }
  const UNIT = { temp: '°C', rh: '%', pres: 'hPa' }
  const every = sim.field_every || 1
  const nf = sim.n_fields || 1
  const cur = live ? live.upto : frameOf(sim, hour)
  /* THE WINDOW. The axis used to be the whole record, always. A slow drift
   * across a month is a smudge at that scale and unmistakable across a day, so
   * how much paper to show is the reader's decision, not the file's.
   * The window ENDS at the clock and reaches back, which is the direction a
   * recorder works in. */
  const span = windowH > 0
    ? Math.max(2, Math.round((windowH * 60) / ((sim.step_minutes || 15) * every)))
    : nf
  const first = Math.max(0, Math.min(cur - span + 1, nf - span))
  const last = Math.min(first + span - 1, nf - 1)

  return (
    <>
      <div className="chanrow">
      {CH.map((ch) => {
        const vals = live
          ? Array.from({ length: nf }, (_, i) => live.byFrame[ch][i] ?? null)
          : Array.from({ length: nf }, (_, i) => readingAt(sim, s, ch, i))
        // Scale over the WINDOW, not the record: a day of readings squeezed
        // into a month's y-range is a flat line.
        const fin = vals.slice(first, last + 1).filter((v): v is number => v != null)
        if (!fin.length) return null
        const rawLo = Math.min(...fin), rawHi = Math.max(...fin)
        const pad = (rawHi - rawLo) * 0.1 || 1
        const lo = rawLo - pad, hi = rawHi + pad

        /* GEOMETRY. The chart used to be stretched with
         * preserveAspectRatio="none", which is fine for a bare trace and
         * impossible once there is text on it -- the labels would have been
         * squashed by whatever width the column happened to be. It scales
         * uniformly now, with a gutter for the axis. */
        /* Taller relative to its width than it was. At 620x150 in a three-up
         * grid each chart rendered about 78px high, and a month of diurnal
         * cycles in 78px is a band of ink with no shape in it. The point of
         * these is to make a drift visible against a rhythm, which needs
         * vertical room. */
        const W = 620, H = 215
        const L = 50, R = 10, T = 10, B = 24        // gutters
        const x = (i: number) => L + ((i - first) / Math.max(span - 1, 1)) * (W - L - R)
        const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B)

        /* THE PEN DRAWS UP TO NOW, AND NO FURTHER.
         *
         * This used to print the whole month at once and slide a dashed line
         * across it, which is a finished chart with a cursor on it -- not a
         * recorder. A barograph does not know what Thursday looks like on
         * Tuesday. Drawing only as far as the clock has reached is what makes
         * running the clock mean anything: the trace grows, a drift appears as
         * it develops rather than being visible from the first frame, and the
         * shaded verdict arrives at the moment this project would have raised
         * it.
         *
         * The SCALE is still computed over the whole record. Rescaling to
         * what has been drawn so far would make the axis jump on every tick
         * and the trace would writhe in place instead of extending. The paper
         * is ruled before the pen touches it. */
        let d = '', pen = false
        for (let i = first; i <= cur && i <= last; i++) {
          const v = vals[i]
          if (v == null) { pen = false; continue }   // the pen lifts at gaps
          d += (pen ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1) + ' '
          pen = true
        }
        // Where the nib is sitting right now.
        const tipY = vals[cur] != null ? y(vals[cur]!) : null

        // Shading only over paper the pen has passed, for the same reason.
        const bands = []
        for (let i = first; i <= cur && i <= last; i++) {
          const g = live
            ? ({ '0': 'OK', '1': 'WATCH', '2': 'FAULT' }[live.grades[i] ?? '0'] ?? 'OK')
            : bandAt(s, ch, Math.min(i * every, s.g.length - 1))
          if (g === 'WATCH' || g === 'FAULT') {
            bands.push(<rect key={i} x={x(i)} y={T} width={Math.max((W - L - R) / span, 1.2)}
                             height={H - T - B}
                             fill={HUE[g]!} opacity={g === 'FAULT' ? 0.26 : 0.16} />)
          }
        }

        // Three ticks: the two extremes the reader needs for scale, and a
        // middle one so the trace can be read off without arithmetic.
        /* A REAL GRID, not three stray rules.
         *
         * There were three horizontal lines and no verticals at all, so a
         * reading could be placed against the y axis only roughly and against
         * time not at all. Chart paper is ruled both ways; that is what makes
         * it chart paper. Five horizontal divisions and six vertical ones, the
         * verticals labelled at every other line so the axis does not crowd. */
        const NY = 5, NX = 6
        const ticks = Array.from({ length: NY }, (_, i) => hi - (i / (NY - 1)) * (hi - lo))
        const vlines = Array.from({ length: NX + 1 },
          (_, i) => first + Math.round((i / NX) * (span - 1)))

        // A day label is useless on a 24-hour window and a clock is useless on
        // a month; the axis says whichever one is changing.
        const shortSpan = span * every * (sim.step_minutes || 15) <= 48 * 60
        const dayLabel = (frame: number) => {
          const t = timeLabel(sim, frame * every)
          return shortSpan ? t.slice(11, 16) : t.slice(5, 10).replace('-', '/')
        }

        /* WHAT THE TRACE ALONE DOES NOT SAY.
         *
         * The extremes over the window, and the mean, because "is this high?"
         * is the first question anyone asks of a reading and the answer is not
         * in the shape of the line. And the onset of the injected fault where
         * one exists and falls inside the window -- drawn from the truth, which
         * the grader never saw, so the verdict can be checked against the thing
         * that caused it. */
        const win = vals.slice(first, last + 1)
        const drawn = win.filter((v): v is number => v != null)
        const mean = drawn.length ? drawn.reduce((a, b) => a + b, 0) / drawn.length : null
        const onsetFrame = s.fault && s.fault.channel === ch
          ? Math.floor((s.fault.onset_hour * 60) / ((sim.step_minutes || 15) * every))
          : null
        const showOnset = onsetFrame != null && onsetFrame >= first && onsetFrame <= last

        const now = vals[cur]
        const band = live
          ? ({ '0': 'OK', '1': 'WATCH', '2': 'FAULT' }[live.grades[cur] ?? '0'] ?? 'OK') as Band
          : bandAt(s, ch, hour)
        // A reading with no grade is not a missing reading.
        const ungraded = band === 'NODATA' && now != null
        return (
          <div className="chan" key={ch}>
            <div className="chan-head">
              <strong>{NAME[ch]}</strong>
              {band !== 'OK' && (
                <span className="badge" title={why(band)}
                      style={{ color: HUE[band] ?? 'var(--ink-3)',
                               borderColor: HUE[band] ?? 'var(--rule-edge)' }}>
                  {ungraded ? UNGRADED : BAND_LABEL[band]}
                </span>)}
              <span className="chan-range mono">
                {drawn.length
                  ? `${Math.min(...drawn).toFixed(1)}–${Math.max(...drawn).toFixed(1)}`
                  : '—'}
              </span>
              <span className="chan-now-val mono">
                {now == null ? 'no data' : now.toFixed(1) + ' ' + UNIT[ch]}
              </span>
            </div>
            <svg viewBox={`0 0 ${W} ${H}`} className="chansvg" role="img"
                 aria-label={`${NAME[ch]} at ${s.name} over 30 days, `
                   + `${rawLo.toFixed(1)} to ${rawHi.toFixed(1)} ${UNIT[ch]}`}>
              <rect x={L} y={T} width={W - L - R} height={H - T - B} className="chan-stock" />

              {/* Ruling, both ways. */}
              {vlines.map((f, i) => (
                <line key={'v' + i} x1={x(f)} x2={x(f)} y1={T} y2={H - B}
                      className="chan-rule" />
              ))}
              {ticks.map((v, i) => (
                <g key={'h' + i}>
                  <line x1={L} x2={W - R} y1={y(v)} y2={y(v)}
                        className={i === 0 || i === NY - 1 ? 'chan-rule-major' : 'chan-rule'} />
                  <text x={L - 6} y={y(v) + 3} className="chan-axis" textAnchor="end">
                    {v.toFixed(ch === 'pres' ? 0 : 1)}
                  </text>
                </g>
              ))}

              {mean != null && (
                <line x1={L} x2={W - R} y1={y(mean)} y2={y(mean)} className="chan-mean" />
              )}

              {bands}

              {showOnset && (
                <g>
                  <line x1={x(onsetFrame!)} x2={x(onsetFrame!)} y1={T} y2={H - B}
                        className="chan-onset" />
                  <text x={x(onsetFrame!) + 3} y={T + 9} className="chan-axis chan-onset-t">
                    fault injected
                  </text>
                </g>
              )}

              <path d={d.trim()} className="chan-pen" />

              <line x1={x(cur)} x2={x(cur)} y1={T} y2={H - B} className="chan-now" />
              {tipY != null && <circle cx={x(cur)} cy={tipY} r={3} className="chan-nib" />}

              {vlines.filter((_, i) => i % 2 === 0).map((f, i, arr) => (
                <text key={'x' + f} x={x(f)} y={H - 6} className="chan-axis"
                      textAnchor={i === 0 ? 'start' : i === arr.length - 1 ? 'end' : 'middle'}>
                  {dayLabel(f)}
                </text>
              ))}
              <rect x={L} y={T} width={W - L - R} height={H - T - B} className="chan-frame" />
            </svg>
          </div>
        )
      })}
      </div>
      <p className="small muted">
        Shading is this project's own verdict, not the injected truth.
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
/** The open alerts.
 *
 * An alert is not just a station and a colour. A person deciding whether to act
 * needs to know WHEN it fired, WHICH channel fired, and where the station is --
 * a name on its own sends them back to the map to look all three up. The
 * console said all of that and the port had dropped it to a name and a badge.
 *
 * There is no store behind any of this and the note at the bottom says so.
 */