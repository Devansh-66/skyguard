/* THE ATMOSPHERE, BECAUSE THAT IS WHAT THIS PRODUCT IS ABOUT.
 *
 * The page was paper and ink and nothing else -- two colours, entirely
 * monochrome, and for a product whose whole subject is the sky that is a
 * strange thing to look at. This is a sky: a dawn gradient through indigo,
 * violet and amber, sun glow low on the horizon, three layers of cloud
 * drifting at different speeds, and isobars curving across the whole thing.
 *
 * WHY THE LAYERS MOVE AT DIFFERENT SPEEDS
 *
 * Parallax is what makes a flat gradient read as depth. High cirrus barely
 * moves, mid-level cloud drifts, low scud crosses quickly. Giving all three
 * the same speed would produce a sliding poster instead of weather.
 *
 * ALL MOTION IS `transform` ONLY, and every animation is CSS.
 *
 * No JavaScript decides whether any of this is visible. A stalled or disabled
 * animation leaves a still sky, which is a perfectly good picture -- the same
 * rule that stopped five sections shipping at opacity zero earlier.
 *
 * The stations are on it because the sky is the thing being measured and they
 * are the things measuring it. One of them is amber, which is the only nod to
 * the rest of the page.
 */
export function SkyPanel() {
  return (
    <div className="relative overflow-hidden rounded-[--radius-lg] border border-rule">
      <svg
        viewBox="0 0 1200 420"
        className="block h-[clamp(240px,34vw,400px)] w-full"
        preserveAspectRatio="xMidYMid slice"
        role="img"
        aria-label="A dawn sky over a plain, with drifting cloud layers, curving isobars and a scatter of weather stations. One station glows amber."
      >
        <defs>
          <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#1B2A5B" />
            <stop offset="34%" stopColor="#4A3B7A" />
            <stop offset="60%" stopColor="#A85C77" />
            <stop offset="80%" stopColor="#E08A5C" />
            <stop offset="100%" stopColor="#F3B77C" />
          </linearGradient>

          <radialGradient id="sun" cx="0.72" cy="0.86" r="0.42">
            <stop offset="0%" stopColor="#FFD9A0" stopOpacity="0.95" />
            <stop offset="45%" stopColor="#F0A265" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#F0A265" stopOpacity="0" />
          </radialGradient>

          <linearGradient id="cloudHi" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.30" />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0.06" />
          </linearGradient>
          <linearGradient id="cloudMid" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#FFE2C4" stopOpacity="0.42" />
            <stop offset="100%" stopColor="#E9A6A0" stopOpacity="0.10" />
          </linearGradient>
          <linearGradient id="cloudLow" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#5C3F6E" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#3A2A55" stopOpacity="0.30" />
          </linearGradient>

          <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2E2440" stopOpacity="0.85" />
            <stop offset="100%" stopColor="#1A1428" stopOpacity="1" />
          </linearGradient>
        </defs>

        <rect width="1200" height="420" fill="url(#sky)" />
        <rect width="1200" height="420" fill="url(#sun)" />

        {/* ISOBARS. The lines a synoptic chart is made of, curving across the
            whole frame -- the one piece of meteorological grammar here. */}
        <g fill="none" stroke="#FFFFFF" strokeOpacity="0.13" strokeWidth="1.1">
          {[70, 122, 176, 232, 290].map((y, i) => (
            <path key={i}
                  d={`M-40 ${y} C 220 ${y - 34 - i * 5}, 520 ${y + 30 + i * 6}, 800 ${y - 16}
                      S 1120 ${y + 22}, 1240 ${y - 6}`} />
          ))}
        </g>

        {/* CLOUD LAYERS. Each band is duplicated end to end and slides by
            exactly its own width, so the loop has no seam. */}
        <g className="sg-drift-slow">
          <CloudBand y={96} fill="url(#cloudHi)" scale={1} />
          <CloudBand y={96} fill="url(#cloudHi)" scale={1} offset={1200} />
        </g>
        <g className="sg-drift-mid">
          <CloudBand y={168} fill="url(#cloudMid)" scale={1.25} />
          <CloudBand y={168} fill="url(#cloudMid)" scale={1.25} offset={1200} />
        </g>
        <g className="sg-drift-fast">
          <CloudBand y={252} fill="url(#cloudLow)" scale={1.6} />
          <CloudBand y={252} fill="url(#cloudLow)" scale={1.6} offset={1200} />
        </g>

        {/* the plain below, so the sky has something to be above */}
        <path d="M0 330 C 180 312, 340 342, 520 330 S 900 316, 1200 336 L1200 420 L0 420 Z"
              fill="url(#ground)" />

        {/* THE NETWORK ON THE GROUND. Small, quiet, and one of them amber --
            the only place the page's severity palette appears in the sky. */}
        <g>
          {STATIONS.map(([sx, sy], i) => {
            const bad = i === 6
            return (
              <g key={i}>
                {bad && (
                  <circle cx={sx} cy={sy} r="11" fill="none"
                          stroke="#F3B23F" strokeOpacity="0.55" strokeWidth="1.2"
                          className="sg-ping" />
                )}
                <circle cx={sx} cy={sy} r={bad ? 3.6 : 2.4}
                        fill={bad ? '#F7C566' : '#FFFFFF'}
                        fillOpacity={bad ? 1 : 0.72} />
              </g>
            )
          })}
        </g>
      </svg>
    </div>
  )
}

/** One band of cloud: a few soft humps that tile end to end. */
function CloudBand({ y, fill, scale, offset = 0 }: {
  y: number; fill: string; scale: number; offset?: number
}) {
  return (
    <path
      transform={`translate(${offset} 0)`}
      fill={fill}
      d={`M0 ${y + 40 * scale}
          C 90 ${y + 6 * scale}, 150 ${y - 14 * scale}, 250 ${y + 10 * scale}
          S 400 ${y - 20 * scale}, 520 ${y + 4 * scale}
          S 690 ${y - 16 * scale}, 810 ${y + 12 * scale}
          S 980 ${y - 10 * scale}, 1200 ${y + 8 * scale}
          L1200 ${y + 70 * scale} L0 ${y + 70 * scale} Z`}
    />
  )
}

/** Fixed positions, so the picture is the same every visit. */
const STATIONS: [number, number][] = [
  [120, 352], [232, 344], [318, 360], [430, 348], [532, 356],
  [636, 342], [742, 352], [846, 346], [948, 358], [1064, 350],
]
