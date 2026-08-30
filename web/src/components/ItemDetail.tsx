/* The evidence behind one board item.
 *
 * Extracted from the old detail page so it can render inside the board's right
 * pane. The order is deliberate: what we concluded, then why, then the raw
 * record, then what a human said about the same window. The analyst note comes
 * LAST because it is the answer key -- putting it first turns every reading of
 * this panel into confirmation of a label already seen.
 */
import type { QueueItemDetail } from '../api/types'
import { useQueueItem } from '../api/queries'
import { siteInfo } from '../api/sites'
import { Async } from './Async'
import { Badge, severityTone } from './Badge'
import { BeliefChart } from './BeliefChart'
import { Callout } from './Callout'
import { Field } from './Field'

export function ItemDetail({ id }: { id: string }) {
  const q = useQueueItem(id)
  return (
    <Async query={q}>
      {(it) => {
        const site = siteInfo(it.station)
        return (
        <article className="detail">
          <header className="detail-head">
            <div>
              <h2>
                {siteInfo(it.station)?.place ?? it.station}{' '}
                <span className="sep">·</span> {it.label}
              </h2>
              <p className="muted small">
                {site ? site.region + ' · ' + site.observatory + ' ' + site.facility + ' · ' : ''}
                {it.station}
              </p>
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

          <h3>The record</h3>
          <BeliefChart series={it.series} unit={it.unit} label={it.label} />

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

          {it.model?.probability != null && (
            <ModelOpinionBlock m={it.model} action={it.action} />
          )}

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
        )
      }}
    </Async>
  )
}

/** The learned model's opinion, beside the panel's rather than instead of it.
 *
 * Two things are deliberately awkward here and both are the point.
 *
 * The probability is shown against its THRESHOLD, not on its own, because 0.29
 * means nothing until you know the model only calls something faulty above
 * 0.97. And where the model and the queue disagree the disagreement is stated
 * out loud: they answer the same question by different means, and a reader who
 * cannot see them diverge will assume they never do.
 */
function ModelOpinionBlock({ m, action }: {
  m: NonNullable<QueueItemDetail['model']>
  action: string
}) {
  const p = m.probability ?? 0
  const thr = m.threshold ?? 1
  const modelSays = p >= thr
  const queueSays = action === 'DISPATCH'
  const agree = modelSays === queueSays

  return (
    <section className="modelop">
      <h3>What the learned model makes of it</h3>
      <div className="fields">
        <Field label="Probability" value={p.toFixed(3)} />
        <Field label="Its threshold" value={thr.toFixed(3)} />
        <Field label="Model says" value={modelSays ? 'faulty' : 'not faulty'} />
        <Field label="Queue says" value={action} />
      </div>

      {!agree && (
        <Callout tone="sus" title="The model and the queue disagree here">
          The panel reached {action} from six hand-written checks; the model
          scored {p.toFixed(3)} against a threshold of {thr.toFixed(3)}. Neither
          is the answer. The panel is what this system acts on, and the model is
          a second opinion trained on nine instruments — which is exactly the
          amount of authority it has earned.
        </Callout>
      )}

      {m.contributions && m.contributions.length > 0 && (
        <>
          <p className="muted small">
            Exact Shapley values from the tree ensemble, not a surrogate&rsquo;s
            approximation. Positive pushes towards faulty.
          </p>
          <div className="tablewrap">
            <table className="shaptab">
              <thead>
                <tr><th>Feature</th><th>Value</th><th>Contribution</th></tr>
              </thead>
              <tbody>
                {m.contributions.map((c) => (
                  <tr key={c.feature}>
                    <td className="mono">{c.feature}</td>
                    <td className="mono num">
                      {c.value == null ? '—' : c.value.toFixed(3)}
                    </td>
                    <td className="mono num"
                        style={{ color: c.shap >= 0 ? 'var(--oxide)' : 'var(--ink-3)' }}>
                      {c.shap >= 0 ? '+' : ''}{c.shap.toFixed(3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="muted small">{m.caveat}</p>
    </section>
  )
}
