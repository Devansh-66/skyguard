/* A boxed caveat.
 *
 * This component exists because the API returns prose that MUST be displayed:
 * `scorecard.caveat` says the precision figure is a lower bound,
 * `reference.warning` says the estimate is compromised by its own window, and
 * `action_note` says why every row shows the same action. Rendering the numbers
 * without them would be the exact failure mode this project is built to argue
 * against. Making the caveat a first-class component makes it harder to drop.
 */
import type { Tone } from './Badge'

export function Callout({ tone = 'neutral', title, children }:
  { tone?: Tone; title?: string; children: React.ReactNode }) {
  return (
    <div className={`callout ${tone}`}>
      {title && <strong>{title}</strong>}
      <div>{children}</div>
    </div>
  )
}
