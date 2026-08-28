/* The single place this app talks to the backend.
 *
 * Every request goes through `get`, so there is exactly one definition of what
 * a failed call looks like. Scattering bare fetch() through components is how
 * you end up with three different error shapes and a UI that renders "[object
 * Object]" on the one path nobody tested.
 */

/** A failed API call, carrying enough to render something useful. */
export class ApiError extends Error {
  // Written as explicit fields rather than constructor parameter properties:
  // the tsconfig sets `erasableSyntaxOnly`, so every type annotation must be
  // strippable without changing runtime behaviour, and parameter properties
  // emit real assignments.
  readonly status: number
  readonly path: string

  constructor(status: number, path: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.path = path
  }
}

/** Relative on purpose. In dev, Vite proxies /api to uvicorn; in production
 *  FastAPI serves this bundle itself. Same origin both ways, so there is no
 *  base URL to configure and no environment variable to get wrong. */
export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { signal, headers: { Accept: 'application/json' } })
  } catch (e) {
    // fetch() rejects only on network failure. The overwhelmingly likely cause
    // during development is that uvicorn is not running, so say that rather
    // than "Failed to fetch", which sends people to look at their wifi.
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, path, 'Cannot reach the API. Is uvicorn running on :8000?')
  }
  if (!res.ok) {
    // FastAPI puts the useful text in `detail`; fall back to the status line
    // for anything that is not a FastAPI error (a proxy 502, say).
    let detail = res.statusText
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch { /* body was not JSON; the status line is all we have */ }
    throw new ApiError(res.status, path, detail)
  }
  return res.json() as Promise<T>
}
