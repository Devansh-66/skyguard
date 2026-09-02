/* What to do, and which agent said so.
 *
 * The old detail pane opened with a sigma, a drift rate and a trust posterior.
 * Those are the right numbers for someone tuning the detector and the wrong
 * ones for someone being sent to a station: none of them says whether to bring
 * a replacement probe or a multimeter. This block answers the technician's
 * question first -- what is the job, how soon, and why -- and leaves the
 * numbers below for whoever wants to audit the call.
 */
import { Badge } from './Badge'
import {
  type Assessment, PRIORITY_LABEL, decisionTone, statusTone,
} from '../lib/triage'

export function ActionCard({ a }: { a: Assessment }) {
  return (
    <div className={'actioncard ' + decisionTone(a.decision)}>
      <div className="actioncard-top">
        <span className="actioncard-do">{a.action_label}</span>
        <Badge tone={decisionTone(a.decision)}>{PRIORITY_LABEL[a.priority]}</Badge>
      </div>
      <p className="actioncard-why">{a.why}</p>
      {a.can_fix_remotely && (
        <p className="actioncard-note">
          No site visit needed — this one can be corrected centrally.
        </p>
      )}
    </div>
  )
}

/* THREE OPINIONS, NOT ONE SCORE.
 *
 * Each row is an agent that looked at one kind of evidence and reported on its
 * own. Showing them separately is the explainability: a reader can see that
 * the hardware agent is the one that fired, and that the weather check did not
 * excuse it, without reading any code. */
export function AgentVerdicts({ a }: { a: Assessment }) {
  return (
    <div className="verdicts">
      {a.verdicts.map((v) => (
        <div key={v.agent} className={'verdict ' + statusTone(v.status)}>
          <span className="verdict-dot" aria-hidden="true" />
          <div className="verdict-body">
            <span className="verdict-title">{v.title}</span>
            <span className="verdict-head">{v.headline}</span>
          </div>
          <span className="verdict-status">{v.status}</span>
        </div>
      ))}
    </div>
  )
}

/* The case lifecycle, as the maintenance workflow defines it. It is drawn as a
 * progress spine rather than prose so a planner can see at a glance where a
 * case has got to. Steps after the current one are not yet true, and the
 * interface says so by dimming them rather than by claiming them. */
const STEPS = ['Detected', 'Validated', 'Case open', 'Assigned', 'Verified', 'Closed']

export function CaseProgress({ at }: { at: number }) {
  return (
    <ol className="caseflow">
      {STEPS.map((s, i) => (
        <li key={s} className={i <= at ? 'done' : ''}>
          <span className="caseflow-dot" aria-hidden="true" />
          <span className="caseflow-label">{s}</span>
        </li>
      ))}
    </ol>
  )
}
