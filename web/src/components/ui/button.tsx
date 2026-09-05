import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

const button = cva(
  'inline-flex items-center justify-center gap-2 rounded-[--radius-md] ' +
  'font-medium transition-colors disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        solid: 'bg-brand text-white hover:opacity-90',
        outline: 'border border-rule bg-surface text-ink hover:bg-sunk',
        ghost: 'text-ink-2 hover:bg-sunk hover:text-ink',
      },
      size: {
        sm: 'h-8 px-3 text-sm',
        md: 'h-9 px-4 text-sm',
        lg: 'h-11 px-6 text-base',
      },
    },
    defaultVariants: { variant: 'outline', size: 'md' },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {}

export function Button({ className, variant, size, type = 'button', ...props }: ButtonProps) {
  // type defaults to "button". Every one of these once defaulted to "submit",
  // which inside a form reloads the page on click.
  return <button type={type} className={cn(button({ variant, size }), className)} {...props} />
}
