/* WHY THE MODEL EXPECTED THAT READING.
 *
 * The panel's Shapley waterfall says which AGENT decided. This says where the
 * number it decided on came from -- and it is the only place in the product
 * where a learned model appears at all.
 *
 * Two references are drawn against the same reading, deliberately. The shipped
 * detector still differences against the neighbour median; the model is a
 * measured improvement on it and not yet the decision path. Showing only the
 * model would claim a swap that has not been made, and showing only the median
 * would hide the work. Showing both, on one reading, is the comparison a
 * reader can act on -- and the shorter bar is the better reference.
 *
 * The bars are TreeSHAP contributions, which for a tree ensemble are exact
 * rather than sampled and sum to the prediction. That sum is printed, because
 * an attribution that does not add up is a picture rather than an account.
 */
import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'

interface Contribution {
  feature: string
  value: number
  contribution: number
}

interface Explain {
  station: string
  channel: string
  step: number
  observed_anomaly: number | null
  learned: { prediction: number; residual: number | null
             sigma: number | null; z: number | null }
  neighbour_median: { prediction: number; residual: number | null
                      sigma: number | null; z: number | null }
  base_value: number
  contributions: Contribution[]
}

/** Plain-language names. `nb_median_near3` is honest and unreadable; the
 *  feature name stays in the tooltip for anyone checking the model. */
const LABEL: Record<string, string> = {
  nb_median: 'Median of all six neighbours',
  nb_median_near3: 'Median of the three nearest',
  nb_trimmed_mean: 'Trimmed mean of the neighbours',
  nb_spread: 'How much the neighbours disagree',
  nb_count: 'How many neighbours reported',
  nb_mean_km: 'Mean distance to them',
  nearest_km: 'Distance to the nearest',
  hour_sin: 'Hour of day',
  hour_cos: 'Hour of day',
  season_sin: 'Time of year',
  season_cos: 'Time of year',
  elev_m: 'Station elevation',
  elev_above_nb: 'Height above its neighbours',
}

const UNIT: Record<string, string> = { temp: '°C', rh: '%', pres: 'hPa' }

export function ReferenceExplain({ station, channel, step }: {
  station: string; channel: 'temp' | 'rh' | 'pres'; step: number
}) {
  const q = useQuery({
    queryKey: ['reference', station, channel, step] as const,
    queryFn: ({ signal }) => get<Explain>(
      `/api/reference/explain?station=${encodeURIComponent(station)}`
      + `&channel=${channel}&step=${step}`, signal),
    staleTime: Infinity,
    // No model built, or no simulated network to build features from. The
    // section simply does not appear; nothing else on the board changes.
    retry: false,
  })

  if (q.isError || (!q.data && !q.isLoading)) return null
  if (!q.data) {
    return <p className="text-sm text-ink-3">Asking the reference model…</p>
  }

  const d = q.data
  const u = UNIT[channel] ?? ''
  const span = Math.max(
    ...d.contributions.map((c) => Math.abs(c.contribution)), 1e-6)

  const lr = d.learned.residual
  const mr = d.neighbour_median.residual
  /* THE COMPARISON IS IN SIGMA, NOT IN THE RAW RESIDUAL.
   *
   * A better reference tracks the weather more tightly, so it leaves a smaller
   * residual on a healthy station AND on a faulty one. Compared as raw numbers
   * that reads as less signal, which is backwards: what decides detection is
   * the residual measured against the spread of residuals, and the model's
   * spread is smaller too. */
  const lz = d.learned.z
  const mz = d.neighbour_median.z
  const better = lz != null && mz != null && lz > mz

  return (
    <div className="flex flex-col gap-4">
      {/* The two references on one reading. */}
      <div className="grid gap-px overflow-hidden rounded-[--radius-md]
                      border border-rule bg-rule sm:grid-cols-3">
        <Cell label="What it read"
              value={fmt(d.observed_anomaly, u)}
              sub="anomaly, against its own hourly normal" />
        <Cell label="Neighbour median expected"
              value={fmt(d.neighbour_median.prediction, u)}
              sub={`leaves ${fmt(mr, u)}${mz != null ? ` · ${mz.toFixed(2)}σ` : ''}`} />
        <Cell label="Model expected"
              value={fmt(d.learned.prediction, u)}
              sub={`leaves ${fmt(lr, u)}${lz != null ? ` · ${lz.toFixed(2)}σ` : ''}`}
              tone={better ? 'ok' : undefined} />
      </div>

      <p className="max-w-[68ch] text-sm text-ink-2">
        Both numbers are a prediction of the same reading from the same six
        neighbours. Compare them in sigma rather than in units: a better
        reference tracks the weather more tightly, so it leaves less behind on
        a healthy station and on a broken one alike, and it is the residual
        measured against its own spread that decides whether anything is
        detected
        {better ? ' — here the model puts this reading further out.' : '.'}
      </p>

      {/* The account of the model's number. */}
      <div className="flex flex-col gap-1.5">
        {d.contributions.map((c) => {
          const w = (Math.abs(c.contribution) / span) * 100
          const up = c.contribution >= 0
          return (
            <div key={c.feature}
                 className="grid grid-cols-[minmax(0,15rem)_1fr_auto] items-center gap-3">
              <span className="truncate text-sm text-ink-2" title={c.feature}>
                {LABEL[c.feature] ?? c.feature}
              </span>
              <span className="relative flex h-3 items-center">
                {/* Zero in the middle: a contribution has a sign, and a bar
                    that only grows rightwards throws it away. */}
                <span className="absolute left-1/2 top-0 h-3 w-px bg-rule" />
                <span
                  className="absolute h-3 rounded-[2px]"
                  style={{
                    width: `${w / 2}%`,
                    left: up ? '50%' : `${50 - w / 2}%`,
                    background: up ? 'var(--color-fault)' : 'var(--color-brand)',
                    opacity: 0.75,
                  }} />
              </span>
              <span className="tnum whitespace-nowrap font-mono text-xs text-ink-2">
                {c.contribution >= 0 ? '+' : ''}{c.contribution.toFixed(3)}
              </span>
            </div>
          )
        })}
      </div>

      <p className="max-w-[68ch] text-xs text-ink-3">
        TreeSHAP, exact for a tree ensemble rather than sampled. The
        contributions sum with a base of{' '}
        <span className="tnum font-mono">{d.base_value.toFixed(3)}</span> to the
        model's prediction of{' '}
        <span className="tnum font-mono">{d.learned.prediction.toFixed(3)}</span>
        {' '}{u} — so the arithmetic can be checked rather than taken on trust.
      </p>

      <p className="max-w-[68ch] text-xs text-ink-3">
        <strong>This model is measured, not deployed.</strong> The verdict above
        was reached by differencing against the neighbour median, as every
        number in this project is. Swapping that term changes every measured
        result, so it is shown beside the decision rather than inside it.
      </p>
    </div>
  )
}

function fmt(v: number | null | undefined, unit: string) {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)} ${unit}`
}

function Cell({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: 'ok'
}) {
  return (
    <div className="bg-surface px-4 py-3">
      <span className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
        {label}
      </span>
      <span className={'mt-1 block text-lg font-semibold tabular-nums '
                       + (tone === 'ok' ? 'text-ok' : '')}>
        {value}
      </span>
      {sub && <span className="mt-0.5 block text-xs text-ink-3">{sub}</span>}
    </div>
  )
}
