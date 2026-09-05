import { cn } from '@/lib/cn'

/* Content that arrives as the page loads.
 *
 * NO JAVASCRIPT, DELIBERATELY.
 *
 * The first version gated opacity on an IntersectionObserver, so anywhere the
 * callback did not arrive -- a frozen tab, an embedded view, a headless
 * capture -- entire sections stayed at opacity 0 permanently. The page looked
 * empty and nothing in the console said why.
 *
 * This is a CSS animation with no fill mode. The resting state is visible; the
 * animation plays from hidden to visible if and when it runs. If it never
 * runs, the content is simply there. Decoration must never be load-bearing.
 */
export function Reveal({ children, delay = 0, className }: {
  children: React.ReactNode
  delay?: number
  className?: string
}) {
  return (
    <div
      className={cn('sg-reveal', className)}
      style={delay ? { animationDelay: `${delay}ms` } : undefined}
    >
      {children}
    </div>
  )
}
