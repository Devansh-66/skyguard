/* WHERE THE WORK HAPPENS, AND WHAT THE NODE ACTUALLY DECIDES.
 *
 * The first version of this figure said the node throws impossible readings
 * away -- "dropped at the pole, never transmitted". That was wrong, and it was
 * wrong in the direction that matters: it described the system doing the one
 * thing it deliberately refuses to do.
 *
 * The firmware reads `if (flagged || due)`. A flag does not suppress an uplink,
 * it TRIGGERS one -- a suspect reading is sent sooner than a clean one. And the
 * server does not take the node's word for it: `api/ingest.py` recomputes the
 * screen, records `edge_screen_disagreement` when the two differ, and stores
 * the reading either way. Nothing is discarded anywhere in the system.
 *
 * SO WHAT DOES THE NODE DECIDE? WHEN TO SPEND RADIO POWER.
 *
 * That is the honest claim and it is also the better one. Radio transmission
 * dominates an AWS power budget, so a clean reading between heartbeats simply
 * waits; a flagged one goes immediately. Same physics screen, but it is routing
 * bandwidth rather than censoring data -- which is what lets the server still
 * reason about the shape of a fault, because it received the fault.
 *
 * THE CAST IS FIXED, and the whole animation is CSS: which readings are flagged
 * is the argument, not a simulation of it. A stalled tab shows a still of the
 * same diagram rather than an empty box.
 */

const W = 960, H = 300
const LANE = 150          // the line a reading arrives on
const START = 46
const GATE = 261          // the node's screen -- answerable with no network
const LINK = 470          // the uplink: everything right of here cost power
const END = 906
const DUR = '9s'

/** How far a reading moves off the arrival line after the gate. */
const LANE_NOW = -46      // flagged: up to the fast lane, sent at once
const LANE_WAIT = 54      // clean: down to the slow lane, waits for a heartbeat

interface Packet {
  /** 0..1 through the loop, so the traffic is not a metronome. */
  at: number
  /** Sent immediately because it is suspect, or held for the heartbeat. */
  fate: 'now' | 'wait'
  /** Why it was flagged, in the fewest words that are still true. */
  why?: string
}

const TRAFFIC: Packet[] = [
  { at: 0.00, fate: 'wait' },
  { at: 0.12, fate: 'now', why: '−81 °C' },
  { at: 0.26, fate: 'wait' },
  { at: 0.38, fate: 'wait' },
  { at: 0.52, fate: 'now', why: 'frozen 64×' },
  { at: 0.66, fate: 'wait' },
  { at: 0.79, fate: 'now', why: 'RH 104 %' },
  { at: 0.90, fate: 'wait' },
]

export function EdgeTiers() {
  return (
    <div className="overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="img"
           aria-label="Readings travel left to right. At the node a physics screen tags each one. Flagged readings move to a fast lane and are transmitted immediately; clean readings move to a slow lane and wait for the next heartbeat. Both cross the uplink and reach the server, which re-runs the same screen and stores everything.">

        {/* The two territories. A wash rather than a box, so it reads as
            'where you are' and not as another component. */}
        <rect x="0" y="0" width={LINK} height={H} fill="var(--color-ink)" fillOpacity="0.025" />

        {/* THE UPLINK. Dashed, because it is the one part that can be down --
            and everything right of it cost power and someone's data plan. */}
        <line x1={LINK} y1="34" x2={LINK} y2={H - 34}
              stroke="var(--color-ink)" strokeOpacity="0.22"
              strokeWidth="1" strokeDasharray="3 4" />
        <g transform={`translate(${LINK - 7} ${H - 44}) rotate(-90)`}>
          <Label x="0" y="0" dim>the uplink</Label>
        </g>

        <Label x="26" y="24">on the node</Label>
        <Label x={LINK + 24} y="24">in the network</Label>

        {/* the arrival line, and the two lanes it splits into */}
        <line x1={START} y1={LANE} x2={GATE} y2={LANE}
              stroke="var(--color-ink)" strokeOpacity="0.14" strokeWidth="1" />
        <line x1={GATE} y1={LANE + LANE_NOW} x2={END} y2={LANE + LANE_NOW}
              stroke="var(--color-fault)" strokeOpacity="0.22" strokeWidth="1" />
        <line x1={GATE} y1={LANE + LANE_WAIT} x2={END} y2={LANE + LANE_WAIT}
              stroke="var(--color-ink)" strokeOpacity="0.14" strokeWidth="1"
              strokeDasharray="3 4" />

        {/* THE GATE. WMO limits, a self-test and the station's own housekeeping
            -- all of it answerable without a network. */}
        <g>
          <line x1={GATE} y1={LANE + LANE_NOW - 18} x2={GATE} y2={LANE + LANE_WAIT + 18}
                stroke="var(--color-ink)" strokeOpacity="0.45" strokeWidth="1.5" />
          <Label x={GATE} y={LANE + LANE_NOW - 28} anchor="middle">range · self-test</Label>
          <text x={GATE} y={LANE + LANE_WAIT + 34} textAnchor="middle"
                fill="var(--color-ink-3)"
                style={{ font: 'italic 11px var(--font-serif, serif)' }}>
            no network needed
          </text>
        </g>

        {/* What each lane means. This is the correction: neither is a bin. */}
        <Label x={GATE + 26} y={LANE + LANE_NOW - 12}>flagged — sent at once</Label>
        <Label x={GATE + 26} y={LANE + LANE_WAIT + 20} dim>clean — waits for the heartbeat</Label>

        {/* THE SERVER, which does not take the node's word for any of it. */}
        <g>
          <rect x={END - 168} y={LANE - 34} width="150" height="68" rx="6"
                fill="none" stroke="var(--color-ink)" strokeOpacity="0.28" strokeWidth="1" />
          <text x={END - 93} y={LANE - 8} textAnchor="middle" fill="var(--color-ink-2)"
                style={{ font: '600 12px var(--font-sans, sans-serif)' }}>
            screened again
          </text>
          <text x={END - 93} y={LANE + 10} textAnchor="middle" fill="var(--color-ink-3)"
                style={{ font: '11px var(--font-sans, sans-serif)' }}>
            stored with its flags
          </text>
          <text x={END - 93} y={LANE + 26} textAnchor="middle" fill="var(--color-ink-3)"
                style={{ font: 'italic 10.5px var(--font-serif, serif)' }}>
            nothing is discarded
          </text>
        </g>

        {TRAFFIC.map((p, i) => <Reading key={i} p={p} />)}
      </svg>

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2
                      border-t border-rule px-5 py-3">
        <p className="max-w-[62ch] text-sm text-ink-2">
          The node does not decide what to keep. It decides when to spend radio
          power — a suspect reading goes immediately, a clean one waits — and the
          server screens everything again on arrival.
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
  /* Negative delay rather than positive: the loop opens already populated, so
     the first pass looks like traffic that was always there instead of a queue
     forming from an empty diagram. */
  const vars = {
    '--sg-dur': DUR,
    '--sg-run': `${END - START}px`,
    '--sg-lane': `${p.fate === 'now' ? LANE_NOW : LANE_WAIT}px`,
    animationDelay: `${-p.at * parseFloat(DUR)}s`,
  } as React.CSSProperties

  return (
    <g className="sg-edge-run" style={vars}>
      <g className="sg-edge-lane" style={vars}>
        <circle cx={START} cy={LANE} r={p.fate === 'now' ? 5 : 4.5}
                fill={p.fate === 'now' ? 'var(--color-fault)' : 'var(--color-ink)'}
                fillOpacity={p.fate === 'now' ? 1 : 0.5} />
        {p.fate === 'now' && (
          <>
            <g className="sg-edge-flag" style={vars}>
              <circle cx={START} cy={LANE} r="12" fill="none"
                      stroke="var(--color-fault)" strokeOpacity="0.4" strokeWidth="1.2" />
            </g>
            {p.why && (
              <text x={START} y={LANE - 14} textAnchor="middle"
                    fill="var(--color-fault)"
                    style={{ font: '600 10px var(--font-mono, monospace)' }}>
                {p.why}
              </text>
            )}
          </>
        )}
      </g>
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
