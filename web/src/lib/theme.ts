/* Theme, chosen by the reader and remembered.
 *
 * Not prefers-color-scheme. A laptop set to dark was getting a dark site
 * nobody asked for -- including on a projector, where dark washes out and the
 * severity colours stop being readable at the moment they matter. Light is the
 * default; dark is a deliberate choice that sticks.
 */
export type Theme = 'light' | 'dark'

const KEY = 'skyguard-theme'

export function readTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'
  } catch {
    // Private windows and blocked site data throw on access rather than
    // returning null, and a theme preference is not worth a blank page.
    return 'light'
  }
}

export function applyTheme(t: Theme) {
  document.documentElement.setAttribute('data-theme', t)
  try { localStorage.setItem(KEY, t) } catch { /* nothing to do about it */ }
}
