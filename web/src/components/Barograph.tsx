/* One ruled plot: chart paper, a pen trace, and the marks that mean something.
 *
 * The ruling is an SVG pattern rather than a thousand <line> elements, so a plot
 * of several thousand samples still has a small DOM. Minor rules every 9px and
 * major every fifth, which is the proportion on real recorder stock and is also
 * what makes a value readable off the grid without labelling every line.
 *
 * `threshold` draws two things: a faint band inside which the instrument is in
 * specification, and the trace redrawn in oxide red wherever it leaves that
 * band. Colour is doing one job here and only one, which is why it can be read
 * instantly.
 */
import { useId } from 'react'
import {
  type Extent,
  type Frame,
  exceedPath,
  penPath,
  px,
  py,
  runs,
} from './chart'

export interface BarographProps {
  values: (number | null)[]
  e: Extent
  /** Height of the plot area in user units. */
  height?: number
  /** In-specification band, drawn as +/-threshold and used to colour the pen. */
  threshold?: number
  /** The analyst's fault interval, shaded behind everything. */
  faulty?: boolean[]
  /** Engraved caption in the top-left of the plate. */
  label?: string
  /** Left and right time stamps under the plot. */
  from?: string
  to?: string
  /** Draw the pen advancing across the paper on first paint. */
  animate?: boolean
  /** Thin plot for the hero wall: no axis numbers, no stamps. */
  bare?: boolean
}

const W = 1000
const PAD_L = 46
const PAD_R = 14

export function Barograph({
  values,
  e,
  height = 130,
  threshold,
  faulty,
  label,
  from,
  to,
  animate = false,
  bare = false,
}: BarographProps) {
  const uid = useId().replace(/:/g, '')
  const n = values.length
  const footer = bare ? 0 : 16
  const H = height + footer
  const f: Frame = { x0: bare ? 0 : PAD_L, y0: 0, w: (bare ? W : W - PAD_L - PAD_R), h: height, e, n }

  const trace = penPath(values, f)
  const over = threshold != null ? exceedPath(values, f, threshold) : ''

  return (
    <svg
      className={'baro' + (bare ? ' bare' : '')}
      viewBox={'0 0 ' + W + ' ' + H}
      preserveAspectRatio="none"
      role="img"
      aria-label={label ? label + ' recorder trace' : 'recorder trace'}
    >
      <defs>
        <pattern id={'rule' + uid} width="45" height="45" patternUnits="userSpaceOnUse">
          <rect width="45" height="45" className="baro-stock" />
          <path d="M0 9H45M0 18H45M0 27H45M0 36H45" className="baro-rule-minor" />
          <path d="M9 0V45M18 0V45M27 0V45M36 0V45" className="baro-rule-minor" />
          <path d="M0 0H45M0 0V45" className="baro-rule-major" />
        </pattern>
      </defs>

      <rect x={f.x0} y={0} width={f.w} height={height} fill={'url(#rule' + uid + ')'} />

      {/* the analyst's interval, behind the pen */}
      {faulty &&
        runs(faulty).map(([a, b], k) => (
          <rect
            key={uid + 'f' + k}
            x={px(f, a)}
            y={0}
            width={Math.max(px(f, b) - px(f, a), 1.5)}
            height={height}
            className="baro-observed"
          />
        ))}

      {/* in-specification band */}
      {threshold != null && (
        <>
          <rect
            x={f.x0}
            y={py(f, threshold)}
            width={f.w}
            height={Math.abs(py(f, -threshold) - py(f, threshold))}
            className="baro-band"
          />
          <line x1={f.x0} x2={f.x0 + f.w} y1={py(f, 0)} y2={py(f, 0)} className="baro-zero" />
        </>
      )}

      <path d={trace} className={'baro-pen' + (animate ? ' drawing' : '')} />
      {over && <path d={over} className={'baro-pen over' + (animate ? ' drawing' : '')} />}

      {!bare && (
        <>
          <rect x={f.x0} y={0} width={f.w} height={height} className="baro-frame" />
          <text x={4} y={11} className="baro-axis">{e.hi.toFixed(1)}</text>
          <text x={4} y={height - 2} className="baro-axis">{e.lo.toFixed(1)}</text>
          {label && <text x={f.x0 + 7} y={13} className="baro-label">{label}</text>}
          {from && <text x={f.x0} y={H - 4} className="baro-axis">{from}</text>}
          {to && (
            <text x={f.x0 + f.w} y={H - 4} textAnchor="end" className="baro-axis">
              {to}
            </text>
          )}
        </>
      )}
    </svg>
  )
}
