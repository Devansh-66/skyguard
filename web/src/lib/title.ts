/* The page title.
 *
 * Every route rendered as "SkyGuard" because index.html sets it once and a
 * single-page app never reloads. That is invisible in development and matters
 * the moment the site is hosted: a browser tab, a bookmark, a shared link and
 * a search result all show this string, and three pages that cannot be told
 * apart in a tab strip is a real cost for one line of code.
 */
import { useEffect } from 'react'

const SITE = 'SkyGuard'

export function usePageTitle(page?: string) {
  useEffect(() => {
    document.title = page ? `${page} · ${SITE}` : SITE
    return () => { document.title = SITE }
  }, [page])
}
