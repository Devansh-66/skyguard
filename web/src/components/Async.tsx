/* One loading/error presentation for every query in the app.
 *
 * Written as a component rather than copied into each route so that a backend
 * that is down looks the same everywhere, and so there is a single place to
 * change when it should look like something better.
 */
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'

interface Props<T> {
  query: { isPending: boolean; error: unknown; data: T | undefined }
  children: (data: T) => ReactNode
}

export function Async<T>({ query, children }: Props<T>) {
  if (query.isPending) return <p className="muted">Loading…</p>
  if (query.error) {
    const e = query.error
    const msg = e instanceof ApiError ? e.message : String(e)
    return (
      <div className="callout bad">
        <strong>Could not load this.</strong>
        <div className="mono small">{msg}</div>
      </div>
    )
  }
  return <>{query.data !== undefined ? children(query.data) : null}</>
}
