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
import type { SimMap, WdqmsMap } from './mapTypes'

const ARCHIVE_STALE_MS = 5 * 60 * 1000

export const keys = {
  queue: ['queue'] as const,
  queueItem: (id: string) => ['queue', id] as const,
  catalog: ['ai', 'catalog'] as const,
  map: (name: string) => ['map', name] as const,
  tiles: ['tiles', 'status'] as const,
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

/** Where the live node stands, and what is currently wrong with it. */
export function useLiveStation() {
  return useQuery({
    queryKey: ['live', 'station'] as const,
    queryFn: ({ signal }) => get<{
      id: string; name: string; state: string
      lat: number; lon: number; elev: number
      neighbours: string[]
    }>('/api/live/station', signal),
    staleTime: Infinity,
    // A station that is not configured is not an error worth a red box; the
    // map simply has one fewer dot.
    retry: false,
  })
}

/** The live node's current verdict, polled so the board can list it as work.
 *
 *  Polled rather than pushed: the board is not the live page and does not hold
 *  a socket open, and a maintenance queue that refreshes every few seconds is
 *  refreshing far faster than anyone works down it. */
export function useLiveStanding() {
  return useQuery({
    queryKey: ['live', 'standing'] as const,
    queryFn: ({ signal }) => get<{
      station: { id: string; name: string; state: string; elev: number }
      band: 'learning' | 'ok' | 'watch' | 'fault'
      z: number
      readings: number
      /** What the neighbours say this place should be reading, and what the
       *  node actually reported. The two numbers the residual is made of, so
       *  the arithmetic behind a verdict can be shown rather than asserted. */
      expected: number | null
      last: number | null
      open_seconds: number | null
      reporting: boolean
      injected_fault: string
    }>('/api/live/standing', signal),
    refetchInterval: 5000,
    retry: false,
  })
}

/** Hardware nodes posting through /api/ingest, and where each one stands.
 *
 *  Separate from useLiveStanding on purpose. That one is the Python feeder --
 *  a stand-in that generates its readings. These are devices that MEASURE
 *  them, are registered with coordinates, and are differenced against their
 *  neighbours exactly like the 344. Merging the two into one call would make
 *  the demo unable to answer the first question anyone asks about it: which of
 *  these am I looking at.
 *
 *  Polled, like the board's other sources: a maintenance queue that refreshes
 *  every few seconds refreshes far faster than anyone works down it. */
export interface EdgeStation {
  id: string; name: string; label: string
  state: string; lat: number; lon: number; elev: number
}
export interface EdgeStanding {
  station: string
  /** What THIS reading says. Flickers, by design. */
  band: 'learning' | 'ok' | 'watch' | 'fault'
  /** What the technician is told, after three-up / six-down hysteresis. This
   *  is the one every screen shows; `band` is only for the live tooltip. */
  case: 'learning' | 'ok' | 'watch' | 'fault'
  case_open: boolean
  /** How many record frames the case has been open. Thirty simulated minutes
   *  each -- the unit the rest of the ledger counts in. */
  open_frames: number | null
  open_from_frame: number | null
  z: number
  residual: number
  expected: { temp: number; rh: number; pres: number }
  reported: { temp: number; rh: number; pres: number }
  frame: number
  readings: number
  neighbours: number
  open_seconds: number | null
}
export function useEdgeStanding() {
  return useQuery({
    queryKey: ['edge', 'standing'] as const,
    queryFn: ({ signal }) => get<{
      stations: Record<string, EdgeStation>
      standing: Record<string, EdgeStanding>
      /** Why a station that IS reporting still has no verdict. Empty is the
       *  normal case; an entry is the difference between "this dashboard is
       *  broken" and "this node cannot say when its readings are from". */
      blocked: Record<string, { reason: string; detail: string; t: number }>
    }>('/api/edge/standing', signal),
    refetchInterval: 5000,
    // A build with no hardware node configured is not an error worth a red
    // box; the map simply has one fewer dot.
    retry: false,
  })
}

/** One hardware node's trace: what it reported, and what its neighbours say
 *  it should have reported, on the shared record axis.
 *
 *  Fetched rather than accumulated from the socket, because the node's history
 *  outlives the page -- a board reporting for an hour should draw an hour on
 *  first paint. Only fetched for the node actually being looked at. */
export function useEdgeSeries(station: string | null) {
  return useQuery({
    queryKey: ['edge', 'series', station] as const,
    queryFn: ({ signal }) => get<{
      station: string
      n: number
      frames: number[]
      reported: { temp: (number | null)[]; rh: (number | null)[]; pres: (number | null)[] }
      expected: { temp: (number | null)[]; rh: (number | null)[]; pres: (number | null)[] }
      minutes_per_frame: number
    }>(`/api/edge/series?station=${encodeURIComponent(station!)}`, signal),
    enabled: Boolean(station),
    refetchInterval: 5000,
    retry: false,
  })
}

/** Whether the node's scenario replay is running, and how far it has got.
 *
 *  The panel needs this to tell a live trace from a stopped one. A pen that
 *  has stopped moving and a pen that is between readings look identical, and
 *  the first is a fault while the second is a Tuesday. */
export function useReplayStatus() {
  return useQuery({
    queryKey: ['edge', 'replay', 'status'] as const,
    queryFn: ({ signal }) => get<{
      running: boolean; sent: number; total: number
      station: string | null; pass_no: number
      stopped_by: string | null; scenario_present: boolean
    }>('/api/edge/replay/status', signal),
    refetchInterval: 2000,
    retry: false,
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
