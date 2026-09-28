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
  figure: React.ReactNode
  className?: string
}) {
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
          page rather than as a pause. 28vh keeps one step always in view. */}
      <ol className="flex flex-col gap-[28vh] py-[8vh] lg:py-[12vh]">
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
