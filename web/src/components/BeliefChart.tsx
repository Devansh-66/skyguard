/* Two recorder plates on one time axis: what the instrument reported, and what
 * we have concluded about the instrument.
 *
 * WHY TWO PLATES AND NOT ONE
 *
 * The reading and the bias estimate are in different units and answer different
 * questions. Overlaying them on a shared vertical scale invites "the line went
 * up" to be read as "the sensor drifted", which is precisely the confusion the
 * belief state exists to resolve. A real recorder used one drum per quantity;
 * so does this.
 */
import { Barograph } from './Barograph'
import { extent, inSigma, include, stamp } from './chart'
import type { Series } from '../api/types'

/** From BIAS_TOLERANCE in detect/belief.py. An item is raised when |bias|
 *  exceeds this many noise sigma, so the band is the decision drawn. */
const BIAS_TOLERANCE = 2

export function BeliefChart({
  series,
  unit,
  label,
}: {
  series: Series
  unit: string
  label: string
}) {
  const n = series.t.length
  if (!n) return <p className="muted">No record for this item.</p>

  const from = stamp(series.t[0])
  const to = stamp(series.t[n - 1])
  // Bias in units of the sensor's own noise. See inSigma: raw bias against a
  // constant band draws instruments inside thresholds they have crossed.
  const sigma = inSigma(series.bias, series.noise)

  return (
    <figure className="plates">
      <Barograph
        values={series.v}
        e={extent(series.v)}
        faulty={series.faulty}
        label={label + ' (' + unit + ')'}
        height={132}
        from={from}
        to={to}
      />
      <Barograph
        values={sigma}
        // Keep the tolerance band on the paper even when the pen never
        // approaches it, or the plate silently rescales and a calm instrument
        // is drawn looking alarming.
        e={include(extent(sigma), -BIAS_TOLERANCE * 1.25, BIAS_TOLERANCE * 1.25)}
        faulty={series.faulty}
        threshold={BIAS_TOLERANCE}
        label={'estimated bias (σ) · band = ±' + BIAS_TOLERANCE + 'σ, the raise threshold'}
        height={104}
        from={from}
        to={to}
      />
      <figcaption className="small muted">
        The shaded span is the interval an analyst reported as faulty. It is
        drawn for comparison only — nothing in the estimate uses it. The pen
        lifts at gaps in the record rather than joining across them.
      </figcaption>
    </figure>
  )
}
