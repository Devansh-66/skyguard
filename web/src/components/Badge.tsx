/* A short coloured label. `tone` is the semantic, never the colour -- callers
 * say what they mean and this file decides how it looks. */
export type Tone = 'ok' | 'sus' | 'bad' | 'neutral' | 'accent'

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: React.ReactNode }) {
  return <span className={`badge ${tone}`}>{children}</span>
}

/** Severity to tone, in ONE place. These thresholds are read off
 *  BIAS_TOLERANCE in detect/belief.py: an item is raised at 2 sigma, so 2 is
 *  the boundary between "watch" and "act", not a number chosen to look right. */
export function severityTone(severity: number): Tone {
  if (severity >= 4) return 'bad'
  if (severity >= 2) return 'sus'
  return 'ok'
}
