/* ONE FIGURE, HELD STILL, WHILE THE ARGUMENT WALKS PAST IT.
 *
 * The drift argument is the whole project in one picture, and the page was
 * giving it three seconds: a chart, a paragraph above it, and a scroll past.
 * A reader who has not already understood neighbour differencing does not
 * learn it from a caption.
 *
 * So the figure is pinned and the reasoning moves. Each step is one sentence,
 * and the step nearest the middle of the screen is the one lit; the others
 * stay legible but recede. Scrolling IS the explanation -- which is the only
 * honest use of the effect, because it makes the reader set the pace.
 *
 * WHY THIS DOES NOT DEPEND ON JAVASCRIPT TO BE READABLE
 *
 * `position: sticky` is the whole pin -- no scroll handler, no measurement, no
 * observer. The steps are ordinary paragraphs in ordinary flow. Where the
 * browser supports scroll-driven animations the active one brightens as it
 * passes the middle; where it does not, every step is simply at full contrast
 * and the section reads as a figure beside a list. Nothing here can leave
 * content invisible, which is the rule the reveal animation was rewritten for.
 *
 * Below `lg` the pin is dropped entirely. A sticky panel on a phone eats the
 * screen the text needs, and a figure that covers its own explanation is
 * worse than a figure that scrolls away.
 */
import { cn } from '@/lib/cn'

export interface StoryStep {
  /** The claim, in one sentence. Two at the most -- this is read while moving. */
  text: React.ReactNode
  /** Optional short label that names the step, for the rail on the left. */
  label?: string
}

export function ScrollStory({ steps, figure, className }: {
  steps: StoryStep[]
  /** Optional. The figure used to be a chart pinned beside the steps; the page
   *  now draws the argument in the field of dots behind it, so the usual case
   *  is no figure at all and a single column of steps that the field moves
   *  under. The pinned-figure layout is kept because it is still the right
   *  answer for a section whose picture cannot be a field of dots. */
  figure?: React.ReactNode
  className?: string
}) {
  if (!figure) {
    return (
      <div className={cn(className)}>
        <Steps steps={steps} />
      </div>
    )
  }
  return (
    <div className={cn('lg:grid lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.25fr)] lg:gap-12',
                       className)}>
      {/* The steps. Tall enough that the figure stays pinned while they pass;
          the height comes from the steps themselves rather than a fixed
          spacer, so editing the copy cannot leave the pin running past the
          end of the text. */}
      {/* THE GAPS SET THE PACE, AND THEY CAN BE TOO GENEROUS.
          At 42vh apart with 18vh of padding there was a scroll position where
          the last step had left the top of the screen and the section end had
          not arrived -- a completely empty viewport, which reads as a broken
          page rather than as a pause. Since the pinned chart went and the
          steps became a single column, even 28vh was too much air: the gaps
          are 16vh, which still separates the claims and never leaves the
          screen with nothing on it. */}
      <Steps steps={steps} />

      {/* The figure. Order-first on small screens so it is seen before the
          reasoning about it, pinned beside the reasoning on large ones. */}
      {/* Pinned a fifth of the way down, which is where the eye sits while
          reading the step beside it -- not at the very top, where the figure
          and the sentence it explains end up looking at each other across an
          empty middle. */}
      <div className="row-start-1 mb-10 lg:sticky lg:top-[20vh] lg:mb-0 lg:self-start
                      lg:h-fit lg:[grid-column:2]">
        {figure}
      </div>
    </div>
  )
}

/** The steps themselves, in ordinary flow. `sg-story-step` brightens the one
 *  nearest the middle of the screen where the browser supports scroll-driven
 *  animation, and does nothing at all where it does not. */
function Steps({ steps }: { steps: StoryStep[] }) {
  return (
    <ol className="flex flex-col gap-[16vh] py-[6vh] lg:py-[9vh]">
      {steps.map((s, i) => (
        <li key={i} className="sg-story-step">
          {s.label && (
            <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-ink-3">
              {String(i + 1).padStart(2, '0')} · {s.label}
            </span>
          )}
          <p className="mt-3 max-w-[38ch] font-serif text-lg leading-relaxed text-ink
                        sm:text-xl">
            {s.text}
          </p>
        </li>
      ))}
    </ol>
  )
}
