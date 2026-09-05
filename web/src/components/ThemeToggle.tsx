import { useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { applyTheme, readTheme, type Theme } from '@/lib/theme'
import { cn } from '@/lib/cn'

/** Light by default, dark on request. The control says which state you are IN
 *  by showing the icon of the state you would move TO, which is the convention
 *  every OS uses and the one people already know. */
export function ThemeToggle() {
  const [t, setT] = useState<Theme>(() => readTheme())
  const next: Theme = t === 'light' ? 'dark' : 'light'
  return (
    <button
      type="button"
      aria-label={`Switch to ${next} theme`}
      onClick={() => { setT(next); applyTheme(next) }}
      className={cn(
        'inline-flex size-9 items-center justify-center rounded-[--radius-pill]',
        'text-ink-2 transition-colors hover:bg-sunk hover:text-ink',
      )}
    >
      {t === 'light' ? <Moon size={17} /> : <Sun size={17} />}
    </button>
  )
}
