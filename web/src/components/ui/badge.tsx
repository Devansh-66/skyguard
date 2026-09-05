import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

/* Severity is a variant, not a colour the caller picks.
 *
 * Passing a colour in at the call site is how two screens end up disagreeing
 * about what amber means. The vocabulary is closed here so "watch" looks the
 * same everywhere it appears, and a new severity has to be added on purpose. */
const badge = cva(
  'inline-flex items-center gap-1 rounded-[--radius-sm] border px-1.5 py-0.5 ' +
  'font-mono text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap',
  {
    variants: {
      tone: {
        ok: 'border-ok/30 bg-ok-soft text-ok',
        watch: 'border-watch/30 bg-watch-soft text-watch',
        fault: 'border-fault/30 bg-fault-soft text-fault',
        brand: 'border-brand/30 bg-brand-soft text-brand',
        muted: 'border-rule bg-sunk text-ink-3',
      },
    },
    defaultVariants: { tone: 'muted' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badge> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badge({ tone }), className)} {...props} />
}
