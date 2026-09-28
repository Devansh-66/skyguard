/* ONE FIELD OF DOTS THAT CARRIES THE WHOLE PAGE.
 *
 * The home page used to explain itself with two line charts pinned beside the
 * text. They were accurate and they were inert: a reader scrolled past a
 * picture of an argument instead of watching the argument happen.
 *
 * So there are no charts. There is one field of points behind the entire page,
 * and scrolling moves it through the argument:
 *
 *   India          the network -- 344 stations inside the real boundary
 *   traces         thirty days of seven stations, all rising and falling as one
 *   the residual   the same seven after their neighbours are subtracted, six
 *                  collapsed onto zero and one walking out of the band
 *   the panel      three clusters of evidence converging on one verdict
 *   India          back to the network, which is what was being graded
 *
 * Every point keeps its identity across all five -- the 344 that are stations
 * in the first shape are the same 344 that end up back on the map, and the
 * coloured ones are the same dots that make the three agents' clusters in the
 * fourth -- so the page reads as one thing being re-arranged rather than five
 * pictures.
 *
 * THE FIELD GOES BESIDE THE CONTENT, NEVER UNDER IT
 *
 * The first version put the shapes in a fixed right-hand band. That works for
 * a page of narrow paragraphs and fails the moment a section is three cards
 * wide: the dots went behind the cards and the animation simply stopped
 * existing for a whole screen at a time.
 *
 * So the shapes are stored in a unit box and placed at draw time into whatever
 * space the page is not using at that scroll position. The occupied width is
 * measured from the real headings, paragraphs and cards, so the band follows
 * the layout instead of a guess about it: wide where the copy is a column, and
 * a ribbon down the margin where a grid of cards runs the full measure.
 * Nothing needs updating here when a section changes shape.
 *
 * WHY NONE OF THIS IS LOAD-BEARING
 *
 * The field is behind the content, aria-hidden, and carries no information the
 * text does not state. If the boundary never loads, the shape falls back to a
 * scattered cloud. If the canvas never paints, the page is a page. Under
 * `prefers-reduced-motion` it settles on the first shape and stops.
 *
 * WHY THE LOOP NEVER STOPS, AND WHY IT IS NOT THE ONLY DRIVER
 *
 * requestAnimationFrame does not fire in a hidden tab, an occluded pane or a
 * headless capture, so a field that only paints from the loop is blank in all
 * of them -- which is exactly what happened. It paints once synchronously on
 * mount and is then driven by both the scroll event and the frame loop: the
 * scroll moves it, the frames finish the move.
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
 * measured against the sections. Between two anchors the field is in
 * transition, which is the point: the change happens while you read the copy
 * that explains it. */
const ANCHORS = [0.06, 0.17, 0.32, 0.52, 0.90]

/** Gap between the content and the field, in CSS pixels. */
const GAP = 28
/** Narrower than this and a band is not worth preferring. Deliberately small:
 *  a ribbon down the margin beside a full-width grid of cards is still the
 *  field going past the section, which is what it is for. */
const MIN_BAND = 110

/** A shape, stored in a unit box: 2N numbers in [0,1]. Unit coordinates are
 *  what let the band change every frame without rebuilding anything. */
interface Shape {
  p: Float32Array
  /** width/height the shape wants, or 0 for "stretch to the band". */
  aspect: number
}

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
    /** Ink first, then the three agent colours. */
    let palette = ['#141413', '#1A5C7A', '#96650C', '#2F6F4E']
    /** Light ink means a dark page, where the same alpha reads fainter. */
    let baseAlpha = 0.13
    let inkIsLight = false
    /** Content rectangles in DOCUMENT coordinates, so scrolling does not
     *  invalidate them. Rebuilt whenever the layout could have changed. */
    let blocks: { top: number; bottom: number; left: number; right: number }[] = []
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

    /** Every piece of the page the field must not sit on top of -- and only
     *  those.
     *
     *  The distinction that matters is whether a thing has a surface. A card,
     *  a stat strip, the inverted results band: these are opaque, and a dot
     *  behind one is a dot that does not exist. Headings and paragraphs are
     *  not; the field passing faintly behind a line of type is the effect
     *  working, and it is what the hero looked like when it read best.
     *
     *  So the keep-out is every element with a background of its own, read
     *  from the computed style rather than guessed from a class name, and
     *  measured in document coordinates so scrolling does not invalidate it. */
    function measure() {
      const host = document.querySelector('[data-field-content]') ?? document.body
      const y = window.scrollY
      blocks = [...host.querySelectorAll('[class*="rounded-"],[class*="bg-"]')]
        .filter((e) => {
          const bg = getComputedStyle(e).backgroundColor
          const m = bg.match(/[\d.]+/g)
          return !!m && m.length >= 3 && (m.length < 4 || +m[3] > 0.05)
        })
        .map((e) => {
          const r = e.getBoundingClientRect()
          return { top: r.top + y, bottom: r.bottom + y, left: r.left, right: r.right }
        })
        .filter((r) => r.bottom > r.top && r.right > r.left)
    }

    function build() {
      w = vw()
      h = vh()
      el!.width = Math.round(w * dpr)
      el!.height = Math.round(h * dpr)
      el!.style.width = w + 'px'
      el!.style.height = h + 'px'
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0)

      const cs = getComputedStyle(document.documentElement)
      const read = (name: string, fallback: string) => {
        const v = cs.getPropertyValue(name).trim()
        return /^(#|rgb|oklch|hsl)/.test(v) ? v : fallback
      }
      palette = [
        read('--color-ink', '#141413'),
        read('--color-brand', '#1A5C7A'),
        read('--color-watch', '#96650C'),
        read('--color-ok', '#2F6F4E'),
      ]
      // On a dark page the ink is a pale colour, and pale-on-dark at the same
      // alpha reads noticeably fainter than dark-on-pale. It gets more.
      inkIsLight = light(palette[0])
      baseAlpha = inkIsLight ? 0.20 : 0.13

      const india = shapeIndia(data.current)
      shapes = [india, shapeTraces(), shapeResidual(), shapePanel(), india]
      measure()
      dirty.current = false
    }

    /* THE CANVAS IS SIZED FROM THE VIEWPORT, AND THE VIEWPORT LIES AT MOUNT.
     *
     * A pane that is still opening reports a width of 0, and a field built at
     * that moment is a one-pixel canvas that no later event rebuilds. So the
     * size is re-checked before every paint rather than trusted once: a wrong
     * size can then last one frame instead of the session. */
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

    /** The widest strip of this screen the page is not using.
     *
     *  Prefers the right, because the copy is set against the left of the
     *  measure and that is where the room usually is; takes the left when it
     *  is clearly better; and where a full-width grid leaves neither, returns
     *  the wider margin so the field passes down the side of the section
     *  instead of disappearing behind it. */
    function freeBand(): [number, number] {
      const top = window.scrollY, bot = top + h
      let left = Infinity, right = -Infinity
      for (const b of blocks) {
        if (b.bottom < top || b.top > bot) continue
        if (b.left < left) left = b.left
        if (b.right > right) right = b.right
      }
      if (right < 0) return [w * 0.5, w * 0.985]        // nothing on this screen
      const r = w - (right + GAP), l = left - GAP
      if (r >= l && r >= MIN_BAND) return [right + GAP, w - 8]
      if (l >= MIN_BAND) return [8, left - GAP]
      // No honest gap: take the wider margin anyway rather than hide.
      return r >= l ? [w - Math.max(r, 44) - 8, w - 8] : [8, Math.max(l, 44)]
    }

    /** Place a unit-box shape into the band, preserving its aspect if it has
     *  one. Returns the offset and scale to map unit coordinates through. */
    function box(s: Shape, bx0: number, bx1: number) {
      const bw = bx1 - bx0, bh = h * 0.84
      if (!s.aspect) return { x: bx0, y: h * 0.08, sx: bw, sy: bh }
      const sw = Math.min(bw, bh * s.aspect), sh = sw / s.aspect
      return { x: bx0 + (bw - sw) / 2, y: (h - sh) / 2, sx: sw, sy: sh }
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

      const [bx0, bx1] = freeBand()
      const A = box(a, bx0, bx1), B = box(b, bx0, bx1)
      // A ribbon down a margin is a lot of dots in very little width, so the
      // dots shrink with the band rather than turning into a smear.
      const rf = 0.6 + 0.4 * Math.min(1, (bx1 - bx0) / 320)

      const xy = (k: number) => {
        const ax = A.x + a.p[k * 2] * A.sx, ay = A.y + a.p[k * 2 + 1] * A.sy
        const bx = B.x + b.p[k * 2] * B.sx, by = B.y + b.p[k * 2 + 1] * B.sy
        return [ax + (bx - ax) * t, ay + (by - ay) * t] as const
      }

      // the country: plain ink, quiet
      ctx!.fillStyle = palette[0]
      ctx!.globalAlpha = baseAlpha
      ctx!.beginPath()
      for (let k = 0; k < N - STATIONS; k++) {
        if (TONE[k]) continue
        const [x, y] = xy(k)
        ctx!.moveTo(x + rf, y); ctx!.arc(x, y, rf, 0, Math.PI * 2)
      }
      ctx!.fill()

      /* THE COLOURED FEW ARE THE THREE AGENTS, EVERYWHERE ON THE PAGE.
       *
       * They are not decoration sprinkled on: a dot carrying the data-quality
       * blue is a dot that lands in the data-quality cluster when the field
       * reaches the panel. So the scatter of colour in the map is the same
       * evidence, unsorted -- which is what the product actually claims. */
      for (let tone = 1; tone <= 3; tone++) {
        ctx!.fillStyle = palette[tone]
        ctx!.globalAlpha = 0.6
        ctx!.beginPath()
        for (let k = 0; k < N; k++) {
          if (TONE[k] !== tone) continue
          const [x, y] = xy(k)
          const r = rf * (k >= N - STATIONS ? 1.6 : 1.3)
          ctx!.moveTo(x + r, y); ctx!.arc(x, y, r, 0, Math.PI * 2)
        }
        ctx!.fill()
      }

      // the stations: ink again, and bigger, because they are the subject
      ctx!.fillStyle = palette[0]
      ctx!.globalAlpha = inkIsLight ? 0.55 : 0.42
      ctx!.beginPath()
      for (let k = N - STATIONS; k < N; k++) {
        if (TONE[k]) continue
        const [x, y] = xy(k)
        const r = rf * 1.7
        ctx!.moveTo(x + r, y); ctx!.arc(x, y, r, 0, Math.PI * 2)
      }
      ctx!.fill()
      ctx!.globalAlpha = 1
    }

    /** One easing step toward where the scroll says the field should be.
     *
     * This is driven from BOTH the scroll event and an animation frame, and it
     * has to be, because neither one is dependable on its own. A frame loop
     * alone freezes wherever requestAnimationFrame is throttled. The scroll
     * event alone stops the moment the wheel does, so the field arrives in
     * jerks and never settles. */
    const step = () => {
      if (!ensure()) return
      at += (want - at) * 0.18
      draw()
    }

    /* PAINT ONCE BEFORE ANY FRAME IS ASKED FOR, so the resting state is the
     * first shape rather than an empty canvas. */
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

    /* THE THEME WAS A COLOUR THE FIELD READ ONCE AND KEPT.
     *
     * The ink was resolved at build time, so switching to dark left the dots
     * painting the light theme's near-black onto a near-black page and the
     * whole field vanished. The toggle sets data-theme on <html>; watching it
     * is the difference between a field that follows the page and one that
     * only works in the mode it happened to load in. */
    const themes = new MutationObserver(() => { dirty.current = true })
    themes.observe(document.documentElement,
                   { attributes: true, attributeFilter: ['data-theme', 'class'] })

    /* The page's height and column widths change as data lands and fonts
     * settle; the measured blocks have to keep up or the band drifts out of
     * step with the layout it is avoiding. */
    const layout = new ResizeObserver(() => { dirty.current = true })
    layout.observe(document.body)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', onScroll)
      themes.disconnect()
      layout.disconnect()
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

/* ------------------------------------------------------------------ colour */

/** Which dots carry an agent's colour, and which agent.
 *
 *  0 is plain ink. 1, 2 and 3 are data quality, hardware health and weather-
 *  or-fault -- and they are chosen by the same `k % 4` that decides which
 *  cluster a dot joins in the panel shape, so a coloured dot is always the
 *  agent whose cluster it will land in. About one dot in fourteen, which is
 *  enough to see and few enough to stay a field rather than a chart. */
const TONE = (() => {
  const t = new Uint8Array(N)
  for (let k = 0; k < N; k++) if (k % 14 === 0 && k % 4 < 3) t[k] = (k % 4) + 1
  return t
})()

/** Is this colour light? Used to tell a dark page from a pale one without
 *  asking the document twice about a theme it has already published. */
function light(css: string) {
  if (css.startsWith('#')) {
    const hex = css.slice(1)
    const n = hex.length === 3
      ? hex.split('').map((c) => parseInt(c + c, 16))
      : [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16))
    return (n[0] * 0.299 + n[1] * 0.587 + n[2] * 0.114) > 140
  }
  const m = css.match(/\d+(\.\d+)?/g)
  if (m && m.length >= 3 && css.startsWith('rgb')) {
    return (+m[0] * 0.299 + +m[1] * 0.587 + +m[2] * 0.114) > 140
  }
  return false
}

/* ------------------------------------------------------------------ shapes */

/* The mask is a fixed size because the result is unit coordinates: the shape
 * does not need to know how big it will eventually be drawn. */
const MASK_H = 512
const MASK_W = Math.round(MASK_H * 0.88)

/** India, rejection-sampled against the real boundary.
 *
 *  Testing thousands of candidate points against an 8,778-vertex multipolygon
 *  in JavaScript would cost hundreds of frames. Filling the polygon once into
 *  an offscreen canvas and reading its alpha channel costs one, and the shape
 *  is exactly the outline the network map draws. */
function shapeIndia(d: { geom?: GeoJSON.Geometry; stations?: SimMap['stations'] }): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(7)
  const ux = (lon: number) => (lon - LON[0]) / (LON[1] - LON[0])
  const uy = (lat: number) => 1 - (lat - LAT[0]) / (LAT[1] - LAT[0])

  let mask: Uint8ClampedArray | null = null
  const geom = d.geom
  if (geom && (geom.type === 'MultiPolygon' || geom.type === 'Polygon')) {
    const m = document.createElement('canvas')
    m.width = MASK_W; m.height = MASK_H
    const mc = m.getContext('2d', { willReadFrequently: true })
    if (mc) {
      mc.fillStyle = '#000'
      mc.beginPath()
      const polys = geom.type === 'MultiPolygon'
        ? (geom.coordinates as number[][][][])
        : [geom.coordinates as number[][][]]
      for (const poly of polys) for (const ring of poly) {
        ring.forEach(([lon, lat], i) => {
          const x = ux(lon) * MASK_W, y = uy(lat) * MASK_H
          if (i === 0) mc.moveTo(x, y); else mc.lineTo(x, y)
        })
        mc.closePath()
      }
      mc.fill('evenodd')
      mask = mc.getImageData(0, 0, MASK_W, MASK_H).data
    }
  }

  const fill = N - STATIONS
  let k = 0, tries = 0
  while (k < fill && tries < fill * 60) {
    tries++
    const x = rand(), y = rand()
    if (mask && mask[(((y * MASK_H) | 0) * MASK_W + ((x * MASK_W) | 0)) * 4 + 3] < 128) continue
    out[k * 2] = x; out[k * 2 + 1] = y; k++
  }
  // Without the boundary this is a scattered cloud rather than an empty hero.
  while (k < fill) { out[k * 2] = rand(); out[k * 2 + 1] = rand(); k++ }

  const st = d.stations ?? []
  for (let s = 0; s < STATIONS; s++) {
    const j = (fill + s) * 2
    const p = st[s]
    if (p) { out[j] = ux(p.lon); out[j + 1] = uy(p.lat) }
    else { out[j] = rand(); out[j + 1] = rand() }
  }
  return { p: out, aspect: MASK_W / MASK_H }
}

const ROWS = 7

/** Seven stations over thirty days. Every trace carries the same weather, and
 *  one of them is also drifting -- by a twentieth of the daily swing, which is
 *  the whole point: at this scale you cannot see which. */
function shapeTraces(): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(19)
  const per = Math.ceil(N / ROWS)
  for (let k = 0; k < N; k++) {
    const row = k % ROWS, u = Math.floor(k / ROWS) / (per - 1)
    const weather = Math.sin(u * Math.PI * 6.2) * 0.19 + Math.sin(u * Math.PI * 12.4 + 1.1) * 0.06
    const base = 0.5 + (row - (ROWS - 1) / 2) * 0.045
    const drift = row === 2 ? u * 0.095 : 0
    out[k * 2] = u
    out[k * 2 + 1] = base + weather + drift + (rand() - 0.5) * 0.01
  }
  return { p: out, aspect: 0 }
}

/** The same seven after the median of their neighbours is subtracted. The
 *  weather cancels because it happened to all of them; six traces collapse
 *  onto zero and the seventh walks out of the band it had been hiding in. */
function shapeResidual(): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(23)
  const per = Math.ceil(N / ROWS)
  for (let k = 0; k < N; k++) {
    const row = k % ROWS, u = Math.floor(k / ROWS) / (per - 1)
    out[k * 2] = u
    out[k * 2 + 1] = row === 2 ? 0.5 - u * 0.38 : 0.5 + (rand() - 0.5) * 0.028
  }
  return { p: out, aspect: 0 }
}

/** Three clusters of evidence and the verdict they converge on: the data
 *  quality, hardware health and weather-or-fault agents, then the arbiter's
 *  single decision. The cluster a dot joins is `k % 4`, which is also what
 *  gives it its colour, so the three columns come out in the three agents'
 *  own colours. */
function shapePanel(): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(31)
  for (let k = 0; k < N; k++) {
    const j = k * 2
    if (k % 4 < 3) {
      const c = k % 4
      out[j] = 0.10 + c * 0.22 + (rand() - 0.5) * 0.13
      out[j + 1] = 0.5 + (rand() - 0.5) * 0.62
    } else {
      const a = rand() * Math.PI * 2
      const r = 0.15 * Math.sqrt(0.55 + rand() * 0.45)
      out[j] = 0.84 + Math.cos(a) * r
      out[j + 1] = 0.5 + Math.sin(a) * r * 1.6
    }
  }
  return { p: out, aspect: 0 }
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
