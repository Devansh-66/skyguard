/* TanStack Query hooks -- one per endpoint, and nothing else.
 *
 * Components never call `get` directly. Keeping the query keys in this file is
 * what makes cache invalidation possible later: when ingest starts pushing live
 * readings over MQTT, the queue has to be invalidated from outside the
 * component that renders it, and that needs a key it can name.
 *
 * STALENESS, AND WHY IT IS SET SO HIGH
 *
 * /api/queue rescans every held ARM window and rebuilds the belief state for
 * every sensor. It is cached server-side with lru_cache, but the response is
 * still a survey of an archive that does not change while the process runs.
 * Refetching it on every window focus would be pure waste. When live ingest
 * lands, that path gets its own hook with its own much shorter staleness --
 * the archive and the live network are different data with different clocks,
 * and giving them one refresh policy would be wrong for both.
 */
import { useQuery } from '@tanstack/react-query'
import { get } from './client'
import type { CatalogResponse, QueueItemDetail, QueueResponse } from './types'
import type { ArmMap, SimMap, WdqmsMap } from './mapTypes'

const ARCHIVE_STALE_MS = 5 * 60 * 1000

export const keys = {
  queue: ['queue'] as const,
  queueItem: (id: string) => ['queue', id] as const,
  catalog: ['ai', 'catalog'] as const,
  map: (name: string) => ['map', name] as const,
  tiles: ['tiles', 'status'] as const,
}

export function useQueue() {
  return useQuery({
    queryKey: keys.queue,
    queryFn: ({ signal }) => get<QueueResponse>('/api/queue', signal),
    staleTime: ARCHIVE_STALE_MS,
  })
}

export function useQueueItem(id: string | undefined) {
  return useQuery({
    // The id is COLON-separated, not slash-separated:
    // "sgpmetE37:D160930.5:rh". It is still encoded whole, because a raw colon
    // in a path segment is legal but ambiguous, and because the router mounts
    // this as a splat -- so an id that ever gains a slash keeps working.
    queryKey: keys.queueItem(id ?? ''),
    queryFn: ({ signal }) =>
      get<QueueItemDetail>(
        '/api/queue/' + (id ?? '').split('/').map(encodeURIComponent).join('/'),
        signal,
      ),
    enabled: Boolean(id),
    staleTime: ARCHIVE_STALE_MS,
  })
}

export function useCatalog() {
  return useQuery({
    queryKey: keys.catalog,
    queryFn: ({ signal }) => get<CatalogResponse>('/api/ai/catalog', signal),
    staleTime: ARCHIVE_STALE_MS,
  })
}


/* The map datasets. These are build artefacts, not live readings -- an export
 * step produces them and nothing changes them in between -- so they are held
 * for the whole session rather than refetched. The console inlines the same
 * files; see api/mapdata.py for why the two frontends differ there.
 */
const BUILD_ARTEFACT = { staleTime: Infinity, gcTime: Infinity } as const

export function useSimMap() {
  return useQuery({
    queryKey: keys.map('sim'),
    queryFn: ({ signal }) => get<SimMap>('/api/map/sim', signal),
    ...BUILD_ARTEFACT,
  })
}

export function useWdqmsMap() {
  return useQuery({
    queryKey: keys.map('wdqms'),
    queryFn: ({ signal }) => get<WdqmsMap>('/api/map/wdqms', signal),
    ...BUILD_ARTEFACT,
  })
}

export function useArmMap() {
  return useQuery({
    queryKey: keys.map('arm'),
    queryFn: ({ signal }) => get<ArmMap>('/api/map/arm', signal),
    ...BUILD_ARTEFACT,
  })
}

/** The official NCMRWF boundary as geometry.
 *
 * Only needed on a static build, where there is no proxy to serve it as WMS
 * tiles. It is the same source either way -- vendored from NCMRWF -- so the
 * depiction of the border is still not something this application improvises. */
export function useBoundaryGeo() {
  return useQuery({
    queryKey: keys.map('boundary'),
    queryFn: ({ signal }) => get<unknown>('/api/map/boundary', signal),
    staleTime: Infinity,
  })
}

export function useStatesGeo() {
  return useQuery({
    queryKey: keys.map('states'),
    queryFn: ({ signal }) => get<unknown>('/api/map/states', signal),
    ...BUILD_ARTEFACT,
  })
}

/** The tile service's own status: it names the fingerprinted tile URL, which
 *  must never be built by hand -- that is how a browser ends up caching an
 *  obsolete basemap at a URL that did not change. */
export function useTileStatus() {
  return useQuery({
    queryKey: keys.tiles,
    queryFn: ({ signal }) => get<{
      available: boolean
      tile_template: string
      boundary_template: string | null
      attribution: string
      max_zoom: number
    }>('/api/tiles/status', signal),
    staleTime: ARCHIVE_STALE_MS,
  })
}
