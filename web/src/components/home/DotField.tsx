/* ONE FIELD OF DOTS THAT CARRIES THE WHOLE PAGE.
 *
 * The home page used to explain itself with two line charts pinned beside the
 * text. They were accurate and they were inert: a reader scrolled past a
 * picture of an argument instead of watching the argument happen.
 *
 * So there are no charts now. There is one field of points behind the entire
 * page, and scrolling moves it through the argument:
 *
 *   India          the network -- 344 stations inside the real boundary
 *   traces         thirty days of seven stations, all rising and falling as one
 *   the residual   the same seven after their neighbours are subtracted, six
 *                  collapsed onto zero and one walking out of the band
 *   the panel      three clusters of evidence converging on one verdict
 *   India          back to the network, which is what was being graded
 *
 * Every point keeps its identity across all five -- the 344 that are stations
 * in the first shape are the same 344 that end up back on the map -- so the
 * page reads as one thing being re-arranged rather than five pictures.
 *
 * WHY NONE OF THIS IS LOAD-BEARING
 *
 * The field is behind the content, aria-hidden, and carries no information the
 * text does not state. If the boundary never loads, the shape falls back to a
 * scattered cloud. If the canvas never paints, the page is a page. Under
 * `prefers-reduced-motion` it settles on the first shape and stops. The rule
 * this project keeps re-learning is that decoration must never be the only
 * place a fact appears, and nothing here is anywhere else.
 *
 * WHY THE LOOP NEVER STOPS
 *
 * An earlier version drew once per data change and scheduled a one-shot
 * animation. Any effect teardown that landed between the schedule and the
 * frame left an empty canvas with no way back, and that is exactly what
 * happened. This one starts a single permanent loop on mount and rebuilds from
 * a flag; there is no path in which the last thing to run is a clear.
 */
import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { get } from '../../api/client'
import type { SimMap } from '../../api/mapTypes'

/** Points in the field. Enough to read as a surface at 1440px, few enough that
 *  a full redraw every frame stays under a millisecond on a laptop. */
const N = 1500
/** How many of those are real stations. The rest are the country around them. */
const STATIONS = 344

/* The vendored boundary's own frame, hard-coded so the canvas can lay out
 * before the GeoJSON arrives. */
const LON = [67.5, 98.0] as const
const LAT = [6.2, 37.6] as const

/* WHERE EACH SHAPE IS FULLY ITSELF, as a fraction of the page's scroll.
 *
 * Spreading five shapes evenly over the page put the residual under the
 * three-agent section and the map under the closing call to action -- the
 * field was moving, but never in step with the sentence being read. These are
 * measured against the sections: the map through the hero, the traces and
 * their residual across the four steps of the drift argument, the panel under
 * the three specialists, and the map again under the measured numbers, which
 * are numbers about the network. Between two anchors the field is in
 * transition, which is the point: the change happens while you read the copy
 * that explains it. */
const ANCHORS = [0.06, 0.17, 0.32, 0.52, 0.90]

type Shape = Float32Array           // [x0, y0, x1, y1, ...], canvas CSS pixels

export function DotField({ className }: { className?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const data = useRef<{ geom?: GeoJSON.Geometry; stations?: SimMap['stations'] }>({})
  const dirty = useRef(true)

  const boundary = useQuery({
    queryKey: ['map', 'boundary'] as const,
    queryFn: ({ signal }) => get<GeoJSON.Feature>('/api/map/boundary', signal),
    staleTime: Infinity, retry: false,
  })
  const sim = useQuery({
    queryKey: ['map', 'sim'] as const,
    queryFn: ({ signal }) => get<SimMap>('/api/map/sim', signal),
    staleTime: Infinity, retry: false,
  })

  // The queries feed a ref, not the effect's dependency list. The drawing loop
  // is started once and owns the canvas for the component's whole life; data
  // arriving later only raises a flag it reads on its next frame.
  useEffect(() => {
    data.current = {
      geom: (boundary.data as GeoJSON.Feature | undefined)?.geometry,
      stations: sim.data?.stations,
    }
    dirty.current = true
  }, [boundary.data, sim.data])

  useEffect(() => {
    const el = canvas.current
    if (!el) return
    const ctx = el.getContext('2d')
    if (!ctx) return

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    let w = 0, h = 0
    let shapes: Shape[] = []
    let ink = '#141413'
    /** Where the field actually is, which lags where the scroll says it should
     *  be. Without this the dots snap with the scroll wheel; with it they
     *  stream, which is the difference between a slideshow and a field. */
    let at = 0
    /** Where the scroll says it should be. */
    let want = 0

    /* Layout's idea of the viewport, not the window's.
     *
     * `window.innerWidth` is 0 in an occluded or not-yet-composited tab even
     * while the document lays out perfectly well around it, so a canvas sized
     * from it comes out 1x1 or blank. The documentElement's client box is the
     * same number whenever the window is honest and a real number when it is
     * not. */
    const vw = () => document.documentElement.clientWidth || window.innerWidth
    const vh = () => document.documentElement.clientHeight || window.innerHeight

    function build() {
      w = vw()
      h = vh()
      el!.width = Math.round(w * dpr)
      el!.height = Math.round(h * dpr)
      el!.style.width = w + 'px'
      el!.style.height = h + 'px'
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0)

      const c = getComputedStyle(document.documentElement)
        .getPropertyValue('--color-ink').trim()
      ink = /^(#|rgb|oklch|hsl)/.test(c) ? c : '#141413'

      const india = shapeIndia(w, h, data.current)
      shapes = [india, shapeTraces(w, h), shapeResidual(w, h), shapePanel(w, h), india]
      dirty.current = false
    }

    /* THE CANVAS IS SIZED FROM THE VIEWPORT, AND THE VIEWPORT LIES AT MOUNT.
     *
     * A pane that is still opening reports an innerWidth of 0, and a field
     * built at that moment is a one-pixel canvas that no later event rebuilds
     * -- which is exactly what happened. So the size is re-checked before
     * every paint rather than trusted once and patched by a resize listener:
     * a wrong size can then last one frame instead of the session. */
    const ensure = () => {
      const cw = vw(), ch = vh()
      if (!cw || !ch) return false
      if (dirty.current || cw !== w || ch !== h) build()
      return true
    }

    /** 0 at the top of the document, 1 at the bottom. */
    function progress() {
      const d = document.documentElement
      const span = d.scrollHeight - vh()
      return span > 0 ? Math.min(1, Math.max(0, window.scrollY / span)) : 0
    }

    function draw() {
      ctx!.clearRect(0, 0, w, h)
      const segs = shapes.length - 1
      let f = at <= ANCHORS[0] ? 0 : segs
      for (let k = 0; k < segs; k++) {
        if (at >= ANCHORS[k] && at <= ANCHORS[k + 1]) {
          f = k + (at - ANCHORS[k]) / (ANCHORS[k + 1] - ANCHORS[k])
          break
        }
      }
      f = Math.min(segs - 1e-6, Math.max(0, f))
      const i = Math.floor(f)
      const a = shapes[i], b = shapes[i + 1]
      // smoothstep, so each shape holds still for a moment before dissolving
      const u = f - i
      const t = u * u * (3 - 2 * u)

      ctx!.fillStyle = ink
      /* Where the field has no free half to live in it has to cross the
       * words, so it gets quieter rather than getting out of the way -- a
       * texture behind the text instead of dots between the letters. */
      const faint = w < 900 ? 0.5 : 1
      for (let pass = 0; pass < 2; pass++) {
        const isStation = pass === 1
        ctx!.globalAlpha = (isStation ? 0.42 : 0.13) * faint
        ctx!.beginPath()
        const from = isStation ? N - STATIONS : 0
        const to = isStation ? N : N - STATIONS
        const r = isStation ? 1.7 : 1.0
        for (let k = from; k < to; k++) {
          const x = a[k * 2] + (b[k * 2] - a[k * 2]) * t
          const y = a[k * 2 + 1] + (b[k * 2 + 1] - a[k * 2 + 1]) * t
          ctx!.moveTo(x + r, y)
          ctx!.arc(x, y, r, 0, Math.PI * 2)
        }
        ctx!.fill()
      }
      ctx!.globalAlpha = 1
    }


    /** One easing step toward where the scroll says the field should be.
     *
     * This is driven from BOTH the scroll event and an animation frame, and it
     * has to be, because neither one is dependable on its own. A frame loop
     * alone freezes wherever requestAnimationFrame is throttled -- a
     * background window, an occluded pane, a capture -- and the field sits on
     * one shape while the reader scrolls past four. The scroll event alone
     * stops the moment the wheel does, so the field arrives in jerks and never
     * settles. Together: the scroll moves it, the frames finish the move. */
    const step = () => {
      if (!ensure()) return
      at += (want - at) * 0.18
      draw()
    }

    /* PAINT ONCE BEFORE ANY FRAME IS ASKED FOR.
     *
     * requestAnimationFrame does not fire in a hidden tab, a background
     * window, or a headless capture -- so a field that only ever paints from
     * the loop is blank in every one of those, including print. One
     * synchronous build and draw on mount makes the resting state the first
     * shape; the loop then takes over wherever frames are actually served. */
    at = reduce ? 0 : progress()
    want = at
    step()

    let raf = 0
    const frame = () => {
      raf = requestAnimationFrame(frame)
      if (dirty.current || w !== vw() || h !== vh()) { step(); return }
      if (Math.abs(want - at) > 0.0004) step()
    }

    const onScroll = () => {
      if (reduce) return
      want = progress()
      step()
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    raf = requestAnimationFrame(frame)

    const onResize = () => { dirty.current = true }
    window.addEventListener('resize', onResize)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', onScroll)
    }
  }, [])

  return (
    <canvas
      ref={canvas}
      aria-hidden="true"
      className={className ?? 'pointer-events-none fixed inset-0 z-0'}
    />
  )
}

/* ------------------------------------------------------------------ shapes */

/* THE FIELD KEEPS TO THE SIDE THE TEXT IS NOT ON.
 *
 * Centred, the map ran straight through the headline and the dots landed
 * between the words -- a background that makes the foreground harder to read
 * is not a background. The page sets its copy in a column against the left of
 * a 1100px measure, so on anything wide enough the field lives in the right
 * half and the reading stays clean. Below that there is no free half, so it
 * spans the width and relies on being faint; a phone shows one shape at a time
 * with a lot of air around it anyway. */
function band(w: number) {
  return w < 900 ? [w * 0.06, w * 0.94] : [w * 0.50, w * 0.985]
}

/** The map's frame: the tallest box that fits the band it is given. */
function frame(w: number, h: number) {
  const [bx0, bx1] = band(w)
  const sh = h * 0.80
  const sw = Math.min(bx1 - bx0, sh * 0.88)
  return { x0: bx0 + (bx1 - bx0 - sw) / 2, y0: (h - sh) / 2, sw, sh }
}

/** India, rejection-sampled against the real boundary.
 *
 *  Testing thousands of candidate points against an 8,778-vertex multipolygon
 *  in JavaScript would cost hundreds of frames. Filling the polygon once into
 *  an offscreen canvas and reading its alpha channel costs one, and the shape
 *  is exactly the outline the network map draws. */
function shapeIndia(w: number, h: number,
                    d: { geom?: GeoJSON.Geometry; stations?: SimMap['stations'] }): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(7)
  const { x0, y0, sw, sh } = frame(w, h)
  const px = (lon: number) => x0 + ((lon - LON[0]) / (LON[1] - LON[0])) * sw
  const py = (lat: number) => y0 + (1 - (lat - LAT[0]) / (LAT[1] - LAT[0])) * sh

  let mask: Uint8ClampedArray | null = null
  const geom = d.geom
  if (geom && (geom.type === 'MultiPolygon' || geom.type === 'Polygon')) {
    const m = document.createElement('canvas')
    m.width = Math.max(1, Math.round(w)); m.height = Math.max(1, Math.round(h))
    const mc = m.getContext('2d', { willReadFrequently: true })
    if (mc) {
      mc.fillStyle = '#000'
      mc.beginPath()
      const polys = geom.type === 'MultiPolygon'
        ? (geom.coordinates as number[][][][])
        : [geom.coordinates as number[][][]]
      for (const poly of polys) for (const ring of poly) {
        ring.forEach(([lon, lat], i) => {
          const x = px(lon), y = py(lat)
          if (i === 0) mc.moveTo(x, y); else mc.lineTo(x, y)
        })
        mc.closePath()
      }
      mc.fill('evenodd')
      mask = mc.getImageData(0, 0, m.width, m.height).data
    }
  }

  const fill = N - STATIONS
  let k = 0, tries = 0
  while (k < fill && tries < fill * 60) {
    tries++
    const x = x0 + rand() * sw, y = y0 + rand() * sh
    if (mask && mask[(((y | 0) * Math.round(w)) + (x | 0)) * 4 + 3] < 128) continue
    out[k * 2] = x; out[k * 2 + 1] = y; k++
  }
  // If the boundary never arrived the loop above still fills the box, and if it
  // somehow ran out of tries the remainder is scattered rather than left at 0,0.
  while (k < fill) { out[k * 2] = x0 + rand() * sw; out[k * 2 + 1] = y0 + rand() * sh; k++ }

  const st = d.stations ?? []
  for (let s = 0; s < STATIONS; s++) {
    const j = (fill + s) * 2
    const p = st[s]
    if (p) { out[j] = px(p.lon); out[j + 1] = py(p.lat) }
    else { out[j] = x0 + rand() * sw; out[j + 1] = y0 + rand() * sh }
  }
  return out
}

const ROWS = 7

/** Seven stations over thirty days. Every trace carries the same weather, and
 *  one of them is also drifting -- by a twentieth of the daily swing, which is
 *  the whole point: at this scale you cannot see which. */
function shapeTraces(w: number, h: number): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(19)
  const [pad, right] = band(w); const span = right - pad
  const per = Math.ceil(N / ROWS)
  for (let k = 0; k < N; k++) {
    const row = k % ROWS, u = Math.floor(k / ROWS) / (per - 1)
    const weather = Math.sin(u * Math.PI * 6.2) * h * 0.15
                  + Math.sin(u * Math.PI * 12.4 + 1.1) * h * 0.045
    const base = h * 0.5 + (row - (ROWS - 1) / 2) * h * 0.035
    const drift = row === 2 ? u * h * 0.075 : 0
    out[k * 2] = pad + u * span
    out[k * 2 + 1] = base + weather + drift + (rand() - 0.5) * h * 0.008
  }
  return out
}

/** The same seven after the median of their neighbours is subtracted. The
 *  weather cancels because it happened to all of them; six traces collapse
 *  onto zero and the seventh walks out of the band it had been hiding in. */
function shapeResidual(w: number, h: number): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(23)
  const [pad, right] = band(w); const span = right - pad
  const per = Math.ceil(N / ROWS)
  for (let k = 0; k < N; k++) {
    const row = k % ROWS, u = Math.floor(k / ROWS) / (per - 1)
    out[k * 2] = pad + u * span
    out[k * 2 + 1] = row === 2
      ? h * 0.5 - u * h * 0.30
      : h * 0.5 + (rand() - 0.5) * h * 0.022
  }
  return out
}

/** Three clusters of evidence and the verdict they converge on: the data
 *  quality, hardware health and weather-or-fault agents on the left, the
 *  arbiter's single decision on the right. */
function shapePanel(w: number, h: number): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(31)
  const [bx0, bx1] = band(w); const bw = bx1 - bx0
  for (let k = 0; k < N; k++) {
    const j = k * 2
    if (k % 4 < 3) {
      const c = k % 4
      out[j] = bx0 + bw * (0.10 + c * 0.20) + (rand() - 0.5) * bw * 0.11
      out[j + 1] = h * 0.5 + (rand() - 0.5) * h * 0.42
    } else {
      const a = rand() * Math.PI * 2
      const r = h * 0.17 * Math.sqrt(0.55 + rand() * 0.45)
      out[j] = bx0 + bw * 0.82 + Math.cos(a) * r
      out[j + 1] = h * 0.5 + Math.sin(a) * r
    }
  }
  return out
}

/** Deterministic noise: the field must scatter the same way on every visit, so
 *  it can be pointed at in a slide. */
function mulberry(seed: number) {
  return () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
