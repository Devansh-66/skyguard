/* WHERE THE WORK HAPPENS, WHICH IS NOT ALL IN ONE PLACE.
 *
 * The page already claims a two-tier design in prose. This is the picture of
 * it: readings crossing the node, where anything physically impossible is
 * stopped before it costs a byte of bandwidth, and then crossing the network,
 * where the ones that merely look unusual are finally compared against their
 * neighbours.
 *
 * WHY NOT A PHOTOGRAPH OF THE BOARD
 *
 * Because a dev board on a breadboard reads as a student project, and the
 * claim being made is architectural, not physical. Nobody shows you the
 * hardware their software runs on. What is worth showing is the thing the
 * competition mostly does not do: screening at the sensor rather than in the
 * cloud, and a judgement that needs the network deferred until the network is
 * actually there.
 *
 * THE CAST IS FIXED.
 *
 * Which readings survive the node is the argument, not a simulation of it, so
 * the packets are a written list on staggered delays rather than anything
 * generated. That also means the whole animation is CSS -- see the sg-edge-*
 * keyframes -- and a stalled tab shows a still of the same diagram rather than
 * an empty box.
 */

const W = 960, H = 300
const LANE = 150          // the flow line everything travels along
const START = 46          // where a reading enters
const GATE = 261          // the node's screen, where the impossible stops
const LINK = 470          // the uplink -- everything right of here cost bandwidth
const END = 906
const DUR = '9s'

interface Packet {
  /** 0..1 through the loop, so the traffic is not a metronome. */
  at: number
  /** Stopped at the node, carried to the network, or flagged once there. */
  fate: 'drop' | 'pass' | 'flag'
  /** Why, in the fewest words that are still true. */
  why?: string
  /** Which resting place in the bin, so rejects do not stack. */
  slot?: number
}

const TRAFFIC: Packet[] = [
  { at: 0.00, fate: 'pass' },
  { at: 0.12, fate: 'drop', why: '−81 °C', slot: 0 },
  { at: 0.26, fate: 'pass' },
  { at: 0.38, fate: 'flag' },
  { at: 0.52, fate: 'pass' },
  { at: 0.63, fate: 'drop', why: 'frozen 64×', slot: 1 },
  { at: 0.77, fate: 'pass' },
  { at: 0.88, fate: 'drop', why: 'RH 104 %', slot: 2 },
]

/* Where each reject comes to rest, measured back from the gate. Spaced wide
   enough that the reasons beside them do not touch -- they are the useful part
   of the bin, and three labels on one point is three labels nobody can read. */
const SLOT = [-16, -104, -190]

export function EdgeTiers() {
  return (
    <div className="overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img"
           aria-label="Readings travel left to right. At the node, readings outside physical limits are stopped and dropped into a bin. The rest cross the uplink into the network, where one is flagged after being compared with its neighbours.">

        {/* The two territories. A wash rather than a box, so it reads as
            'where you are' and not as another component. */}
        <rect x="0" y="0" width={LINK} height={H} fill="var(--color-ink)" fillOpacity="0.025" />

        {/* THE UPLINK. Dashed, because it is the one part of this diagram that
            can be down -- and everything to the right of it costs power,
            bandwidth and someone's data plan. */}
        <line x1={LINK} y1="34" x2={LINK} y2={H - 34}
              stroke="var(--color-ink)" strokeOpacity="0.22"
              strokeWidth="1" strokeDasharray="3 4" />
        {/* Along the line, not above it: centred at the top this label sat on
            top of "in the network", which begins 24px to its right. */}
        <g transform={`translate(${LINK - 7} ${H - 44}) rotate(-90)`}>
          <Label x="0" y="0" dim>the uplink</Label>
        </g>

        <Label x="26" y="24">on the node</Label>
        <Label x={LINK + 24} y="24">in the network</Label>

        {/* the lane itself */}
        <line x1={START} y1={LANE} x2={END} y2={LANE}
              stroke="var(--color-ink)" strokeOpacity="0.14" strokeWidth="1" />

        {/* THE GATE. WMO limits, a self-test, and the station's own
            housekeeping -- all of it answerable without a network. */}
        <g>
          <line x1={GATE} y1={LANE - 34} x2={GATE} y2={LANE + 34}
                stroke="var(--color-ink)" strokeOpacity="0.45" strokeWidth="1.5" />
          <Label x={GATE} y={LANE - 44} anchor="middle">range · self-test</Label>
          <text x={GATE} y={LANE + 52} textAnchor="middle"
                className="fill-[var(--color-ink-3)] text-[10px]"
                style={{ font: 'italic 11px var(--font-serif, serif)' }}>
            no network needed
          </text>
        </g>

        {/* THE BIN. What the node refuses to send, and the reason it refused.
            The reasons are the three fault classes a single station can settle
            on its own: out of range, frozen, out of physical bounds. */}
        <g>
          <line x1={START} y1={LANE + 84} x2={LINK - 24} y2={LANE + 84}
                stroke="var(--color-ink)" strokeOpacity="0.14"
                strokeWidth="1" strokeDasharray="2 4" />
          <Label x="26" y={LANE + 104} dim>stopped here — never transmitted</Label>
        </g>

        {/* THE COMPARISON, on the far side. Only here is there anything to
            compare against, which is the whole reason for the second tier. */}
        <g>
          <circle cx={END - 96} cy={LANE} r="30" fill="none"
                  stroke="var(--color-ink)" strokeOpacity="0.2" strokeWidth="1" />
          {[[-1, -1], [1, -1], [-1, 1], [1, 1]].map(([dx, dy], i) => (
            <circle key={i} cx={END - 96 + dx * 30} cy={LANE + dy * 30} r="2.6"
                    fill="var(--color-ink)" fillOpacity="0.35" />
          ))}
          <Label x={END - 96} y={LANE - 48} anchor="middle">vs neighbours</Label>
          <text x={END - 96} y={LANE + 58} textAnchor="middle"
                className="fill-[var(--color-ink-3)]"
                style={{ font: 'italic 11px var(--font-serif, serif)' }}>
            needs the network
          </text>
        </g>

        {/* THE TRAFFIC */}
        {TRAFFIC.map((p, i) => (
          <Reading key={i} p={p} />
        ))}
      </svg>

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2
                      border-t border-rule px-5 py-3">
        <p className="max-w-[60ch] text-sm text-ink-2">
          The impossible is settled where the sensor is. The merely unusual waits
          until there is something to compare it against.
        </p>
        <span className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
          ESP32 · same endpoint as the simulated network
        </span>
      </div>
    </div>
  )
}

/** One reading, on its own delay. */
function Reading({ p }: { p: Packet }) {
  const delay = `${-p.at * parseFloat(DUR)}s`
  const vars = {
    '--sg-dur': DUR,
    '--sg-run': `${END - START}px`,
    '--sg-halt': `${GATE - START - 12}px`,
    '--sg-sink': '84px',
    '--sg-slot': `${SLOT[p.slot ?? 0]}px`,
    animationDelay: delay,
  } as React.CSSProperties

  /* Negative delay rather than a positive one: the loop starts already
     populated, so the first pass looks like traffic that was always there
     instead of a queue forming from an empty diagram. */
  if (p.fate === 'drop') {
    return (
      <g className="sg-edge-halt" style={vars}>
        <g className="sg-edge-sink" style={vars}>
          <circle cx={START} cy={LANE} r="5" fill="var(--color-fault)" />
          {p.why && (
            <text x={START} y={LANE - 12} textAnchor="middle"
                  className="fill-[var(--color-fault)]"
                  style={{ font: '600 10px var(--font-mono, monospace)' }}>
              {p.why}
            </text>
          )}
        </g>
      </g>
    )
  }

  return (
    <g className="sg-edge-run" style={vars}>
      <circle cx={START} cy={LANE} r="4.5" fill="var(--color-ink)" fillOpacity="0.55" />
      {p.fate === 'flag' && (
        <g className="sg-edge-flag" style={vars}>
          <circle cx={START} cy={LANE} r="7.5" fill="var(--color-watch)" />
          <circle cx={START} cy={LANE} r="13" fill="none"
                  stroke="var(--color-watch)" strokeOpacity="0.45" strokeWidth="1.2" />
        </g>
      )}
    </g>
  )
}

function Label({ x, y, children, anchor = 'start', dim }: {
  x: number | string; y: number | string; children: string
  anchor?: 'start' | 'middle'; dim?: boolean
}) {
  return (
    <text x={x} y={y} textAnchor={anchor}
          fill={dim ? 'var(--color-ink-3)' : 'var(--color-ink-2)'}
          style={{ font: '10px var(--font-mono, monospace)', letterSpacing: '0.12em',
                   textTransform: 'uppercase' }}>
      {children.toUpperCase()}
    </text>
  )
}
