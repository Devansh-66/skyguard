/* Talking to the triage panel.
 *
 * The panel itself lives in api/orchestrator.py and it is the ONLY place the
 * rules exist. This file builds the evidence records the board can see and
 * sends them in one batch; it deliberately contains no judgement of its own.
 * Reimplementing "is this a fault" here to save a request is how two screens
 * end up disagreeing about the same sensor.
 */
import { useQuery } from '@tanstack/react-query'
import { post } from '../api/client'

export type AgentStatus = 'ok' | 'watch' | 'alarm' | 'unknown'

export interface AgentVerdict {
  agent: string
  title: string
  status: AgentStatus
  confidence: number
  headline: string
  metrics: Record<string, number | boolean>
}

/** One agent's exact Shapley value, and what the panel says without it. */
export interface Contribution {
  agent: string
  title: string
  /** Signed. Positive pushes toward a visit, negative argues against one. */
  phi: number
  without_action: 'INSPECT' | 'CALIBRATE' | 'COMMS' | 'MONITOR'
  without_decision: 'normal' | 'warning' | 'critical'
}

export interface Attribution {
  /** Escalation with nobody consulted. Zero, so the parts sum to the whole. */
  base: number
  /** Escalation as issued: 0 no visit, 0.5 this week, 1 today. */
  total: number
  contributions: Contribution[]
  exact: boolean
  coalitions: number
}

/** One rule the adjudicator reached, and the answer it got. */
export interface TraceStep {
  step: number
  question: string
  answer: 'yes' | 'no' | 'n/a'
  note: string
  agent: string | null
  /** True on the single step that ended the walk. */
  decided: boolean
}

export interface Assessment {
  decision: 'normal' | 'warning' | 'critical'
  action: 'INSPECT' | 'CALIBRATE' | 'COMMS' | 'MONITOR'
  action_label: string
  priority: 1 | 2 | 3
  confidence: number
  why: string
  can_fix_remotely: boolean
  verdicts: AgentVerdict[]
  attribution?: Attribution
  trace?: TraceStep[]
}

export interface EvidenceIn {
  id: string
  source: 'arm' | 'sim' | 'live'
  sensor?: string
  label?: string
  band?: string | null
  bias_sigma?: number | null
  drift_sigma_day?: number | null
  noise_sigma?: number | null
  trust?: number | null
  evidence_n?: number | null
  housekeeping_moved?: boolean | null
  neighbours_agree?: boolean | null
  analyst_confirmed?: boolean | null
  flat_fraction?: number | null
  gap_fraction?: number | null
  episodes?: number | null
  days_open?: number | null
  /** The flagged window in grade-string steps, so the service can measure
   *  what the neighbours were doing over exactly that stretch. */
  window_from?: number | null
  window_to?: number | null
}

interface TriageResponse {
  assessments: Record<string, Assessment>
  actions: Record<string, string>
}

/** Assess a whole board in one request. Keyed on the ids so the cache is not
 *  thrown away every time the clock advances by a frame. */
export function useTriage(items: EvidenceIn[]) {
  const key = items.map((i) => i.id).join(',')
  return useQuery({
    queryKey: ['triage', key] as const,
    enabled: items.length > 0,
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) =>
      post<TriageResponse>('/api/board/triage', items, signal),
  })
}

/** Priority label a technician reads, not a number they have to decode. */
export const PRIORITY_LABEL: Record<number, string> = {
  1: 'Today',
  2: 'This week',
  3: 'Next visit',
}

export const ACTION_SHORT: Record<string, string> = {
  INSPECT: 'Inspect',
  CALIBRATE: 'Calibrate',
  COMMS: 'Power / comms',
  MONITOR: 'Monitor',
}

export function decisionTone(d: string): 'bad' | 'sus' | 'ok' {
  return d === 'critical' ? 'bad' : d === 'warning' ? 'sus' : 'ok'
}

export function statusTone(s: AgentStatus): 'bad' | 'sus' | 'ok' | 'muted' {
  return s === 'alarm' ? 'bad' : s === 'watch' ? 'sus'
    : s === 'ok' ? 'ok' : 'muted'
}

/* WHICH AGENT ACTUALLY CARRIED THE CALL.
 *
 * Largest absolute Shapley value is the obvious rule and it is wrong on ties,
 * which are not rare: a vetoed row has one agent at +0.25 and another at
 * -0.25, and picking the first credited "data quality" for a verdict of "no
 * visit, this is weather" -- the exact opposite of what happened.
 *
 * The agent that carried a decision is the one whose absence would CHANGE it.
 * That is available directly: every contribution ships the action the panel
 * would have reached without that agent. Prefer those, then break by weight,
 * and fall back to weight alone where nobody is decisive on their own.
 */
export function carrierOf(a: Assessment | undefined): Contribution | null {
  const cs = a?.attribution?.contributions
  if (!a || !cs?.length) return null
  const rank = (c: Contribution) => Math.abs(c.phi)
  const decisive = cs.filter((c) => c.without_action !== a.action)
  const pool = decisive.length ? decisive : cs.filter((c) => rank(c) > 0.001)
  if (!pool.length) return null
  return [...pool].sort((x, y) => rank(y) - rank(x))[0]
}
