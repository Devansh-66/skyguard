/* ONE FIELD OF DOTS THAT CARRIES THE WHOLE PAGE.
 *
 * The home page used to explain itself with two line charts pinned beside the
 * text. They were accurate and they were inert: a reader scrolled past a
 * picture of an argument instead of watching the argument happen.
 *
 * So there are no charts. There is one field of points behind the entire page,
 * and scrolling moves it through five shapes a person already knows how to
 * read -- a country, a wave, a distribution, a Venn, a vortex:
 *
 *   India          the network: hundreds of instruments across a country
 *   the wave       weather, shared by all of them, which is what hides a fault
 *   the curve      the spread readings fall into once their neighbours are
 *                  subtracted -- and the broken one, red, out in the tail
 *   three circles  three specialists, and the verdict living where they agree
 *   the vortex     the atmosphere itself, which is what all of it is for
 *
 * The shapes are the point. An abstract knot or lattice of dots is a texture;
 * a map, a wave and a bell curve are things the reader has already understood
 * before they finish the sentence beside them. Every point keeps its identity
 * throughout -- the 344 that are stations in the first shape are the same 344
 * that are darker in the last, and the handful that sit in the tail of the
 * distribution are red everywhere, because they are the failing station in
 * every one of these pictures.
 *
 * ONE FORMATION AT A TIME, AND IT NEVER DUPLICATES
 *
 * An earlier version split the dots across the free regions and had each
 * region draw the shape, which put two half-density Indias on the screen at
 * once. One population, one shape.
 *
 * Where the page leaves a wide free area the shape is drawn whole in it. Where
 * a full-width grid of cards runs down the middle there is no wide area, so
 * the single shape is TORN around them: the points left of its middle go into
 * the left margin, the points right of it into the right, in proportion to
 * how much room each margin has. That reads as the content pushing the field
 * apart, which is what it is, rather than as a copy on either side. The map is
 * the one shape never torn -- half an India each side is not an India -- so
 * where there is no room it is drawn small in the wider margin.
 *
 * The keep-out is only what has a surface of its own, read from the computed
 * background rather than guessed from a class name, because a card hides a dot
 * and a paragraph does not. Where a screen holds no cards at all the field
 * takes the whole width, which is where the wave and the curve get to be full
 * size.
 *
 * WHY NONE OF THIS IS LOAD-BEARING
 *
 * The field is behind the content, aria-hidden, and carries no information the
 * text does not state. If the boundary never loads, the first shape falls back
 * to a scattered cloud. If the canvas never paints, the page is a page. Under
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
 * Spreading five shapes evenly over the page put the curve under the
 * three-agent section -- the field was moving, but never in step with the
 * sentence being read. These are measured against the sections. Between two
 * anchors the field is in transition, which is the point: the change happens
 * while you read the copy that explains it. */
const ANCHORS = [0.06, 0.17, 0.32, 0.52, 0.90]

/** Gap between a surface and the field, in CSS pixels. */
const GAP = 26
/** A region narrower than this is not worth drawing into at all. */
const MIN_REGION = 96
/** Below this width a region cannot hold a whole shape, so the shape is torn
 *  across both margins instead. */
const WHOLE_REGION = 300
/** Taller than this many times its width and a region transposes the shape it
 *  is given, so time runs down the column instead of across a sliver. */
const UPRIGHT = 1.3

/** A shape, stored in a unit box: 2N numbers in [0,1]. Unit coordinates are
 *  what let the regions change every frame without rebuilding anything. */
interface Shape {
  p: Float32Array
  /** width/height the shape wants, or 0 for "fill the region". */
  aspect: number
  /** Does its x axis mean something (time, value)? Only these transpose. */
  axial?: boolean
  /** May it be torn across two margins? The map may not. */
  tearable?: boolean
}

interface Region { x0: number; x1: number }

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
    /** Ink, then the five accents the page already uses for meaning. */
    let palette = ['#141413', '#1A5C7A', '#96650C', '#2F6F4E', '#A93226', '#8C877C']
    /** Light ink means a dark page, where the same alpha reads fainter. */
    let baseAlpha = 0.13
    let inkIsLight = false
    /** Surface rectangles in DOCUMENT coordinates, so scrolling does not
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
     *  a stat block, the inverted results band: these are opaque, and a dot
     *  behind one is a dot that does not exist. Headings and paragraphs are
     *  not; the field passing faintly behind a line of type is the effect
     *  working, and it is what the hero looked like when it read best. */
    function measure() {
      const host = document.querySelector('[data-field-content]') ?? document.body
      const y = window.scrollY
      blocks = [...host.querySelectorAll('[class*="rounded-"],[class*="bg-"]')]
        .filter((e) => {
          const m = getComputedStyle(e).backgroundColor.match(/[\d.]+/g)
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
        read('--color-fault', '#A93226'),
        read('--color-ink-3', '#8C877C'),
      ]
      // On a dark page the ink is a pale colour, and pale-on-dark at the same
      // alpha reads noticeably fainter than dark-on-pale. It gets more.
      inkIsLight = light(palette[0])
      baseAlpha = inkIsLight ? 0.20 : 0.13

      shapes = [shapeIndia(data.current), shapeWave(), shapeCurve(),
                shapeCircles(), shapeVortex()]
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

    /** The strips of this screen the page is not using, in page order.
     *
     *  With no surfaces in view that is the whole width, which is where the
     *  wave and the curve get to be full size. With a grid of cards down the
     *  middle it is the two margins. */
    function regions(): Region[] {
      const top = window.scrollY, bot = top + h
      let left = Infinity, right = -Infinity
      for (const b of blocks) {
        if (b.bottom < top || b.top > bot) continue
        if (b.left < left) left = b.left
        if (b.right > right) right = b.right
      }
      if (right < 0) return [{ x0: 8, x1: w - 8 }]
      const out: Region[] = []
      if (left - GAP >= MIN_REGION) out.push({ x0: 8, x1: left - GAP })
      if (w - (right + GAP) >= MIN_REGION) out.push({ x0: right + GAP, x1: w - 8 })
      if (!out.length) {
        // No honest gap on either side: take the wider margin anyway, at
        // whatever width it has, rather than hide behind the section.
        const r = w - right, l = left
        out.push(r >= l ? { x0: w - Math.max(r, 46), x1: w - 6 }
                        : { x0: 6, x1: Math.max(l, 46) })
      }
      return out
    }

    /** Where a shape's unit coordinates land on this screen.
     *
     *  Either a single box -- the whole shape in the one free area -- or a
     *  tear: the same shape, its left part in the left margin and its right
     *  part in the right, split where the two margins' widths say. */
    interface Layout {
      tear: null | { s: number; l: Region; r: Region }
      x: number; y: number; sx: number; sy: number; rot: boolean
    }

    function layout(s: Shape, regs: Region[]): Layout {
      const y0 = h * 0.06, sy = h * 0.88
      const widest = regs.reduce((a, b) => (b.x1 - b.x0 > a.x1 - a.x0 ? b : a))
      const wide = widest.x1 - widest.x0

      if (wide < WHOLE_REGION && regs.length > 1 && s.tearable) {
        const l = regs[0], r = regs[1]
        const wl = l.x1 - l.x0, wr = r.x1 - r.x0
        return { tear: { s: wl / (wl + wr), l, r }, x: 0, y: y0, sx: 0, sy, rot: false }
      }

      const rot = !s.aspect && !!s.axial && sy > wide * UPRIGHT
      if (!s.aspect) return { tear: null, x: widest.x0, y: y0, sx: wide, sy, rot }
      const sw = Math.min(wide, sy * s.aspect), sh = sw / s.aspect
      return { tear: null, x: widest.x0 + (wide - sw) / 2, y: y0 + (sy - sh) / 2,
               sx: sw, sy: sh, rot: false }
    }

    const unit = (b: Layout, s: Shape, k: number) => {
      let u = s.p[k * 2], v = s.p[k * 2 + 1]
      if (b.rot) { const t = u; u = 1 - v; v = t }
      if (b.tear) {
        const { s: cut, l, r } = b.tear
        const x = u < cut
          ? l.x0 + (u / cut) * (l.x1 - l.x0)
          : r.x0 + ((u - cut) / (1 - cut)) * (r.x1 - r.x0)
        return [x, b.y + v * b.sy] as const
      }
      return [b.x + u * b.sx, b.y + v * b.sy] as const
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

      const regs = regions()
      const A = layout(a, regs), B = layout(b, regs)
      const room = regs.reduce((m, r) => Math.max(m, r.x1 - r.x0), 0)
      // A ribbon down a margin is a lot of dots in very little width, so the
      // dots shrink with the room rather than turning into a smear.
      const rf = 0.6 + 0.4 * Math.min(1, room / 320)

      const xy = (k: number) => {
        const [ax, ay] = unit(A, a, k)
        const [bx, by] = unit(B, b, k)
        return [ax + (bx - ax) * t, ay + (by - ay) * t] as const
      }

      // the field: plain ink, quiet
      ctx!.fillStyle = palette[0]
      ctx!.globalAlpha = baseAlpha
      ctx!.beginPath()
      for (let k = 0; k < N - STATIONS; k++) {
        if (TONE[k]) continue
        const [x, y] = xy(k)
        ctx!.moveTo(x + rf, y); ctx!.arc(x, y, rf, 0, Math.PI * 2)
      }
      ctx!.fill()

      /* THE COLOURED DOTS ARE THE PAGE'S OWN VOCABULARY.
       *
       * They are not sprinkles: the tone is chosen by the same `k % 4` that
       * decides which circle a dot joins in the Venn, so a dot wearing the
       * data-quality blue is the dot that ends up in the data-quality circle.
       * The red ones are the failing station -- the same points that sit out
       * in the tail of the distribution, wherever else the field goes. */
      for (let tone = 1; tone < palette.length; tone++) {
        ctx!.fillStyle = palette[tone]
        ctx!.globalAlpha = tone === 5 ? 0.34 : 0.62
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
     * settle; the measured surfaces have to keep up or the regions drift out
     * of step with the layout they are avoiding. */
    const layoutWatch = new ResizeObserver(() => { dirty.current = true })
    layoutWatch.observe(document.body)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', onScroll)
      themes.disconnect()
      layoutWatch.disconnect()
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

/** The points that are the failing station.
 *
 *  They are the ones out in the tail of the distribution, and they carry the
 *  fault red in every other shape too -- the same instrument, wherever the
 *  field happens to be. Fixed indices rather than random ones so the page
 *  looks identical on every visit and can be pointed at in a slide. */
const OUTLIERS = [41, 197, 353, 509, 665, 821, 977, 1133]

/** Which dots carry a colour, and which one.
 *
 *  0 is plain ink. 1 to 3 are the three agents, chosen by the same `k % 4`
 *  that decides which circle a dot joins in the Venn, so the colour is never
 *  arbitrary. 4 is the fault red, worn only by the failing station. 5 is a
 *  soft grey that thins the field out rather than adding a sixth meaning.
 *
 *  `k % 7` rather than a multiple of four, because a stride that shares a
 *  factor with four picks the same circle every time and the field comes out
 *  in one colour. */
const TONE = (() => {
  const t = new Uint8Array(N)
  for (let k = 0; k < N; k++) {
    if (k % 7 === 0 && k % 4 < 3) t[k] = (k % 4) + 1
    else if (k % 23 === 5) t[k] = 5
  }
  for (const k of OUTLIERS) t[k] = 4
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

/** INDIA -- the network.
 *
 *  Rejection-sampled against the real boundary. Testing thousands of candidate
 *  points against an 8,778-vertex multipolygon in JavaScript would cost
 *  hundreds of frames; filling the polygon once into an offscreen canvas and
 *  reading its alpha channel costs one, and the shape is exactly the outline
 *  the network map draws. */
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

/** THE WAVE -- weather, shared.
 *
 *  Seven stations over thirty days, drawn as seven strands of one wave because
 *  that is the fact: weather happens to all of them at once, and a probe
 *  sliding a twentieth of a degree a day is buried inside a swing forty times
 *  larger. One strand is drifting, and at this scale you cannot tell which,
 *  which is the whole problem the page is about to solve. */
function shapeWave(): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(19)
  const per = Math.ceil(N / ROWS)
  for (let k = 0; k < N; k++) {
    const row = k % ROWS, u = Math.floor(k / ROWS) / (per - 1)
    const swell = Math.sin(u * Math.PI * 3.2) * 0.26 + Math.sin(u * Math.PI * 7.1 + 0.8) * 0.05
    const strand = (row - (ROWS - 1) / 2) * 0.035
    const drift = row === 2 ? u * 0.09 : 0
    out[k * 2] = u
    out[k * 2 + 1] = 0.5 + swell + strand + drift + (rand() - 0.5) * 0.008
  }
  return { p: out, aspect: 0, axial: true, tearable: true }
}

/** THE CURVE -- the spread, once the weather is gone.
 *
 *  Subtract the median of a station's neighbours and the shared weather
 *  cancels, because it happened to all of them. What is left is a plain
 *  distribution: nearly every reading near zero, fewer further out. It is
 *  drawn as a cloud of points under the bell rather than the bell's outline,
 *  because a drawn curve looks like a chart and a cloud looks like readings.
 *
 *  The failing station is the handful of red points out in the tail, which is
 *  exactly how the detector finds it: not by the reading being impossible, but
 *  by it being far out in the spread its own neighbours define. */
function shapeCurve(): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(23)
  const SIGMA = 0.125
  const outliers = new Set(OUTLIERS)
  for (let k = 0; k < N; k++) {
    if (outliers.has(k)) {
      out[k * 2] = 0.86 + rand() * 0.10
      out[k * 2 + 1] = 0.90 - rand() * 0.06
      continue
    }
    const x = rand()
    const bell = Math.exp(-((x - 0.5) * (x - 0.5)) / (2 * SIGMA * SIGMA))
    out[k * 2] = x
    out[k * 2 + 1] = 0.93 - rand() * bell * 0.78
  }
  return { p: out, aspect: 0, axial: true, tearable: true }
}

/** THREE CIRCLES -- three specialists, one verdict.
 *
 *  A Venn, in the three agents' own colours, with the points that belong to
 *  none of them gathered in the overlap at the centre: the verdict lives where
 *  the three agree. This replaced three parallel bars and a ring, which at any
 *  width narrower than a full screen read as three tally marks and a nought. */
function shapeCircles(): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(31)
  const R = 0.255, D = 0.145
  for (let k = 0; k < N; k++) {
    const j = k * 2, g = k % 4
    if (g < 3) {
      const th = (g * 2 * Math.PI) / 3 - Math.PI / 2
      const cx = 0.5 + Math.cos(th) * D, cy = 0.5 + Math.sin(th) * D
      const a = rand() * Math.PI * 2, r = R * Math.sqrt(rand())
      out[j] = cx + Math.cos(a) * r
      out[j + 1] = cy + Math.sin(a) * r
    } else {
      const a = rand() * Math.PI * 2, r = 0.085 * Math.sqrt(rand())
      out[j] = 0.5 + Math.cos(a) * r
      out[j + 1] = 0.5 + Math.sin(a) * r
    }
  }
  return { p: out, aspect: 1, tearable: true }
}

/** THE VORTEX -- the atmosphere itself.
 *
 *  An inward spiral tightening as it rises, with long arms sweeping in from
 *  the sides to feed it: the shape of a cyclone, and the shape of every
 *  circulation this project exists to measure honestly. The page opens on a
 *  country full of instruments and closes on the thing they are pointed at.
 *
 *  Two thirds of the points are the core, wound on fourteen streamlines so the
 *  loops read as loops rather than as a smear; the rest are the arms. */
function shapeVortex(): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(41)
  const LINES = 14, TURNS = 3.1
  const core = Math.round(N * 0.64)
  for (let k = 0; k < N; k++) {
    const j = k * 2
    if (k < core) {
      const line = k % LINES
      const q = Math.floor(k / LINES) / Math.floor(core / LINES)
      const th = (line / LINES) * Math.PI * 2 + q * TURNS * Math.PI * 2
      const r = 0.30 * (1 - 0.72 * q)
      out[j] = 0.5 + Math.cos(th) * r
      // the loops are ellipses seen obliquely, and the stack rises as it winds
      out[j + 1] = 0.86 - q * 0.70 + Math.sin(th) * r * 0.30
    } else {
      const arm = (k - core) % 9
      const s = ((k - core) / 9 % Math.floor((N - core) / 9)) / Math.floor((N - core) / 9)
      const R = 0.95 - 0.58 * s
      const ph = (arm / 9) * Math.PI * 2 + s * 1.5
      out[j] = 0.5 + Math.cos(ph) * R * 0.52
      out[j + 1] = 0.5 + Math.sin(ph) * R * 0.34 + (rand() - 0.5) * 0.02
    }
  }
  return { p: out, aspect: 0.8, tearable: true }
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
