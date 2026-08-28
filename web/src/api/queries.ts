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

const ARCHIVE_STALE_MS = 5 * 60 * 1000

export const keys = {
  queue: ['queue'] as const,
  queueItem: (id: string) => ['queue', id] as const,
  catalog: ['ai', 'catalog'] as const,
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
