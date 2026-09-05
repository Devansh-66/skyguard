import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Merge class names, letting later Tailwind utilities win over earlier ones.
 *  Plain string concatenation loses that: "p-2" and "p-4" would both survive
 *  and the winner would depend on stylesheet order rather than on the caller. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
