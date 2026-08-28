/* The evidence behind one board item.
 *
 * Extracted from the old detail page so it can render inside the board's right
 * pane. The order is deliberate: what we concluded, then why, then the raw
 * record, then what a human said about the same window. The analyst note comes
 * LAST because it is the answer key -- putting it first turns every reading of
 * this panel into confirmation of a label already seen.
 */
import { useQueueItem } from '../api/queries'
import { Async } from './Async'
import { Badge, severityTone } from './Badge'
import { BeliefChart } from './BeliefChart'
import { Callout } from './Callout'
import { Field } from './Field'

export function ItemDetail({ id }: { id: string }) {
  const q = useQueueItem(id)
  return (
    <Async query={q}>
      {(it) => (
        <article className="detail">
          <header className="detail-head">
            <div>
              <h2>
                {it.station} <span className="sep">·</span> {it.label}
              </h2>
              <p className="muted small">
                Report {it.window.dqr} · {it.window.start.slice(0, 10)} to{' '}
                {it.window.end.slice(0, 10)}
              </p>
            </div>
            <div className="detail-badges">
              <Badge tone={severityTone(it.severity)}>{it.severity.toFixed(1)}σ</Badge>
              <Badge tone={it.action === 'DISPATCH' ? 'bad' : 'sus'}>{it.action}</Badge>
            </div>
          </header>

          <p className="lede">{it.why}</p>

          {it.reference.compromised && (
            <Callout tone="sus" title="This estimate is weakened by its own reference">
              {it.reference.warning}
            </Callout>
          )}

          <h3>What we believe about this instrument</h3>
          <div className="fields">
            <Field
              label="Bias"
              value={it.bias.toFixed(3) + ' σ'}
              hint="Offset of the sensor from expectation, in units of its own noise."
            />
            <Field
              label="Drift"
              value={it.drift_per_day.toFixed(4) + ' σ/day'}
              hint="Rate at which the bias is growing."
            />
            <Field label="Noise" value={it.noise.toFixed(3)} />
            <Field
              label="Trust"
              value={it.trust.toFixed(3)}
              hint="Beta-reputation posterior: the share of recent checks this sensor passed."
            />
            <Field
              label="Weight of evidence"
              value={it.evidence.toFixed(0)}
              hint="alpha + beta. A low trust on low evidence says very little."
            />
            <Field label="Checks" value={it.checks} />
            <Field label="Onset" value={it.onset.slice(0, 16).replace('T', ' ')} />
            <Field label="Days since onset" value={it.days_since_onset.toFixed(1)} />
          </div>

          <h3>The checker panel</h3>
          <p className="muted small">
            Evaluated at {it.at.slice(0, 16).replace('T', ' ')} — the hour the evidence
            was strongest for this sensor. {it.panel_note}
          </p>
          <table className="panel">
            <thead>
              <tr>
                <th>Checker</th>
                <th>Fired</th>
                <th className="r">Score</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {it.verdicts.map((v) => (
                <tr key={v.checker} className={v.fired ? 'fired' : ''}>
                  <td className="mono">{v.checker}</td>
                  <td>
                    {v.fired ? <Badge tone="bad">FIRED</Badge> : <span className="muted">—</span>}
                  </td>
                  <td className="r num">{v.score == null ? '—' : v.score.toFixed(2)}</td>
                  <td>{v.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="verdict">
            <strong>Adjudication: {it.decision.toUpperCase()}</strong>
            {it.note ? ' — ' + it.note : null}
          </p>

          <h3>The record</h3>
          <BeliefChart series={it.series} unit={it.unit} label={it.label} />

          <h3>What the analyst wrote</h3>
          <p className="muted small">
            Shown last on purpose: it is the answer key, and reading it first turns
            everything above into confirmation.
          </p>
          <blockquote>
            <strong>{it.analyst_subject}</strong>
            <p>{it.analyst_note}</p>
          </blockquote>
        </article>
      )}
    </Async>
  )
}
