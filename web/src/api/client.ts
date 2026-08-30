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

/* STATIC BUILDS.
 *
 * Nothing this app asks for is live. There is no ingest yet, so every endpoint
 * is a deterministic function of a fixed archive, and a server that only ever
 * returns the same bytes is a server that does not need to exist. With
 * VITE_STATIC=1 the same paths are answered by JSON files exported at build
 * time and shipped beside the bundle -- which is what lets the whole site run
 * on a static host with no Python at all.
 *
 * The alternative -- hosting the frontend and pointing it at a backend on
 * someone's laptop -- only works on that laptop, so it is hosting that nobody
 * else can use.
 *
 * When live ingest lands this flag is how you tell the two apart: the archive
 * stays static, the live network needs the API.
 */
const STATIC = import.meta.env.VITE_STATIC === '1'

/** Where a given API path lives in a static build.
 *
 * A one-to-one mapping onto files, except the queue item: its id contains
 * colons ("sgpmetE37:D160930.5:rh"), which are illegal in Windows filenames
 * and awkward on several hosts, so all sixteen details ship in one object
 * keyed by id. That is 385 kB, which is smaller than arguing about it. */
function staticUrl(path: string): string {
  const base = import.meta.env.BASE_URL
  if (path.startsWith('/api/queue/')) return base + 'api/queue-items.json'
  return base + path.replace(/^\/api\//, 'api/') + '.json'
}

/** Relative on purpose. In dev, Vite proxies /api to uvicorn; served by
 *  FastAPI it is the same origin; on a static host it is a file beside the
 *  bundle. No base URL to configure and no environment variable to get wrong. */
export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response
  const url = STATIC ? staticUrl(path) : path
  try {
    res = await fetch(url, { signal, headers: { Accept: 'application/json' } })
  } catch (e) {
    // fetch() rejects only on network failure. The overwhelmingly likely cause
    // during development is that uvicorn is not running, so say that rather
    // than "Failed to fetch", which sends people to look at their wifi.
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, path, STATIC
      ? `Missing ${url}. Run: python -m scripts.export_static`
      : 'Cannot reach the API. Is uvicorn running on :8000?')
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
  const body = await res.json()
  // The queue-item bundle is an object keyed by id; pull out the one asked for
  // so callers see exactly what the live endpoint would have returned.
  if (STATIC && path.startsWith('/api/queue/')) {
    const id = decodeURIComponent(path.slice('/api/queue/'.length))
    const hit = (body as Record<string, unknown>)[id]
    if (!hit) throw new ApiError(404, path, `no such queue item: ${id}`)
    return hit as T
  }
  return body as T
}
