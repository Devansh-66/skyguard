import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'

/* THE STATION AGAINST ITS REGION, WHICH IS THE ACTUAL EVIDENCE.
 *
 * WHAT THIS REPLACES AND WHY
 *
 * The detail pane showed the station's three raw channels with their ranges.
 * That is a picture of the weather, not of the verdict: three plausible lines,
 * no reference, and nothing in any of them that could tell a reader why anyone
 * had been dispatched. You could swap a healthy station's chart for a faulty
 * one and nobody would notice.
 *
 * The evidence was never the reading. It is the reading MINUS what every
 * station nearby was doing at the same moment. So both halves are drawn on one
 * axis, and the gap between them is the entire case:
 *
 *   - the two lines together, moving as one   -> weather, nobody is dispatched
 *   - one line leaving the other              -> the instrument
 *
 * ANOMALIES, NOT RAW VALUES.
 *
 * A mast at 4,196 m and one at 200 m differ by a large constant and by the
 * shape of their daily swing, so raw lines could never share an axis honestly.
 * Each station's own hour-of-day climatology, learned on the early clean
 * stretch, is removed first -- the same operation the grader performs, for the
 * same reason.
 *
 * The shaded band is the region's own quiet spread. A station inside it is
 * doing what its neighbours are doing; leaving it is what "6 sigma" means,
 * drawn rather than asserted.
 */

interface Region {
  available: boolean
  station?: (number | null)[]
  region?: (number | null)[]
  neighbours?: number
  sigma?: number
  every?: number
  channel?: string
}

const UNIT: Record<string, string> = { temp: '°C', rh: '%', pres: 'hPa' }

export function RegionCompare({ station, channel, from, to }: {
  station: string
  channel: 'temp' | 'rh' | 'pres'
  /** The flagged window, in grade steps, shaded on the chart. */
  from?: number | null
  to?: number | null
}) {
  const q = useQuery({
    queryKey: ['region', station, channel] as const,
    queryFn: ({ signal }) =>
      get<Region>(`/api/board/region?station=${encodeURIComponent(station)}`
                  + `&channel=${channel}`, signal),
    staleTime: Infinity,
  })

  if (q.isLoading) {
    return <Frame><p className="p-5 text-sm text-ink-3">Reading the neighbours…</p></Frame>
  }
  const d = q.data
  if (!d?.available || !d.station || !d.region) {
    /* Said plainly rather than drawn empty. A station with too few neighbours
       within range genuinely cannot be compared, and that is a fact about the
       network worth reading, not a loading state. */
    return (
      <Frame>
        <p className="p-5 text-sm text-ink-2">
          Too few neighbouring stations within range to compare against.
        </p>
      </Frame>
    )
  }

  const W = 720, H = 190
  const PAD = { l: 34, r: 10, t: 12, b: 18 }
  const n = d.station.length
  const vals = [...d.station, ...d.region].filter((v): v is number => v != null)
  const lim = Math.max(1e-6, ...vals.map(Math.abs))
  const x = (i: number) => PAD.l + (i / Math.max(1, n - 1)) * (W - PAD.l - PAD.r)
  const y = (v: number) => {
    const h = H - PAD.t - PAD.b
    return PAD.t + h / 2 - (v / lim) * (h / 2) * 0.92
  }

  const path = (arr: (number | null)[]) => {
    let out = '', pen = false
    arr.forEach((v, i) => {
      if (v == null) { pen = false; return }
      out += `${pen ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`
      pen = true
    })
    return out
  }

  // The flagged stretch, converted from grade steps to points on this chart.
  const every = d.every || 1
  const fi = from != null ? Math.max(0, Math.min(n - 1, Math.round(from / every))) : null
  const ti = to != null ? Math.max(0, Math.min(n - 1, Math.round(to / every))) : (fi != null ? n - 1 : null)

  const sig = d.sigma || 0
  const unit = UNIT[d.channel || channel] ?? ''

  return (
    <Frame>
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img"
           aria-label={`This station's anomaly against the median of its ${d.neighbours} neighbours. Where the two lines separate, the station is out of step with its region.`}>

        {/* the region's own quiet spread */}
        {sig > 0 && (
          <rect x={PAD.l} width={W - PAD.l - PAD.r}
                y={y(sig)} height={Math.max(1, y(-sig) - y(sig))}
                fill="var(--color-ok)" fillOpacity="0.12" />
        )}

        {/* zero: doing exactly what the region is doing */}
        <line x1={PAD.l} x2={W - PAD.r} y1={y(0)} y2={y(0)}
              stroke="var(--color-ink)" strokeOpacity="0.2" strokeWidth="1" />

        {/* the flagged window */}
        {/* `>=`, not `>`. A short episode -- five steps, seventy-five minutes --
            is narrower than a single point on a chart covering thirty days, so
            a strict test collapsed it to nothing and the shading silently never
            appeared on exactly the rows whose window mattered most. It is
            floored to a visible width instead. */}
        {fi != null && ti != null && ti >= fi && (
          <rect x={x(fi)} width={Math.max(3, x(ti) - x(fi))} y={PAD.t}
                height={H - PAD.t - PAD.b}
                fill="var(--color-fault)" fillOpacity="0.1" />
        )}

        {/* what the region did */}
        <path d={path(d.region)} fill="none" stroke="var(--color-ok)"
              strokeWidth="1.6" strokeLinejoin="round" />
        {/* what this station did */}
        <path d={path(d.station)} fill="none" stroke="var(--color-fault)"
              strokeWidth="1.8" strokeLinejoin="round" />

        {/* the axis, in the channel's own units */}
        {[lim, 0, -lim].map((v) => (
          <text key={v} x={PAD.l - 6} y={y(v) + 3} textAnchor="end"
                fill="var(--color-ink-3)"
                style={{ font: '9px var(--font-mono, monospace)' }}>
            {v > 0 ? '+' : ''}{v === 0 ? '0' : v.toFixed(lim < 5 ? 1 : 0)}
          </text>
        ))}
      </svg>

      <div className="flex flex-wrap items-center justify-between gap-x-5 gap-y-2
                      border-t border-rule px-4 py-2.5">
        <span className="flex flex-wrap items-center gap-4 text-xs text-ink-2">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4 rounded-sm bg-fault" />
            this station
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4 rounded-sm bg-ok" />
            median of {d.neighbours} neighbours
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-4 rounded-sm bg-ok/25" />
            the region's normal spread
          </span>
        </span>
        <span className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
          anomaly, {unit} · ±1σ = {sig.toFixed(1)}
        </span>
      </div>
    </Frame>
  )
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
      {children}
    </div>
  )
}
