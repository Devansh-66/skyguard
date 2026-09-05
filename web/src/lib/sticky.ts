import { useCallback, useState } from 'react'

/* State that survives leaving the page.
 *
 * WHY THIS EXISTS
 *
 * The network page kept every control in plain useState, so switching to the
 * maintenance tab unmounted the route and threw all of it away: the channel
 * you were colouring by, the base map, the chart window, the station you had
 * picked, where you had scrubbed the clock to. Coming back put you at the
 * defaults again. On a page whose whole purpose is to set something up and
 * then look at it, that is not a small annoyance -- it makes the page
 * impossible to use alongside the board, which is exactly how it is meant to
 * be used.
 *
 * sessionStorage rather than localStorage, deliberately. These are working
 * settings, not preferences: they should survive navigating around the app and
 * an accidental reload, and they should NOT still be there tomorrow, silently
 * showing a colleague a view they never chose. The theme, which IS a
 * preference, uses localStorage and lives elsewhere.
 *
 * Every access is wrapped: private windows and blocked site data throw on
 * access rather than returning null, and a remembered dropdown is not worth a
 * blank page.
 */
const PREFIX = 'skyguard:'

function read<T>(key: string, fallback: T): T {
  try {
    const raw = sessionStorage.getItem(PREFIX + key)
    if (raw == null) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function write<T>(key: string, value: T) {
  try {
    sessionStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    /* full, blocked, or private -- the app carries on without it */
  }
}

/** Like useState, but remembered for the rest of the browsing session. */
export function useSticky<T>(key: string, initial: T) {
  const [v, setV] = useState<T>(() => read(key, initial))

  const set = useCallback((next: T | ((prev: T) => T)) => {
    setV((prev) => {
      const value = typeof next === 'function'
        ? (next as (p: T) => T)(prev)
        : next
      write(key, value)
      return value
    })
  }, [key])

  return [v, set] as const
}
