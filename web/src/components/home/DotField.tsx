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
 * EACH SHAPE HAS ITS OWN PLACE, AND THE PLACE IS FIXED
 *
 * Where a formation belongs is a property of the formation, not of whatever
 * happens to be on screen:
 *
 *   the map      beside the headline, on the right, where it has always read
 *                best -- a country is a picture and it wants a frame
 *   the wave     the full width, behind the copy. A chart of thirty days
 *                wants a long axis, and dots passing faintly behind a line of
 *                type is the effect working
 *   the curve    the same, for the same reason
 *   the circles  the full width, behind the three specialists
 *   the spiral   centred, because a spiral has no side to be on
 *
 * This replaced two failed attempts. Measuring the free space each frame and
 * snapping to it made the shape teleport whenever a card scrolled into view.
 * Centring everything cured the teleport by deleting the layout. A fixed place
 * per shape cannot jump -- there is nothing to recompute -- and the move from
 * one shape's place to the next is carried by the morph itself, which is
 * already eased.
 *
 * The cards are glass -- see `.sg-glass` -- so a wide formation behind a grid
 * of them is dimmed rather than deleted.
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
 * THESE ARE THE FALLBACK. The real ones are measured -- see `anchors()`.
 *
 * Spreading five shapes evenly over the page put the curve under the
 * three-agent section -- the field was moving, but never in step with the
 * sentence being read. These are measured against the sections. Between two
 * anchors the field is in transition, which is the point: the change happens
 * while you read the copy that explains it. */
const ANCHORS = [0.02, 0.14, 0.30, 0.46, 0.65, 0.79, 0.97]

/** How much of the viewport's height a formation is allowed. */
const FRAME_H = 0.86

/** A shape, stored in a unit box: 2N numbers in [0,1]. Unit coordinates are
 *  what let the regions change every frame without rebuilding anything. */
interface Shape {
  p: Float32Array
  /** width/height the shape wants, or 0 for "fill the frame". */
  aspect: number
  /** Where on the screen it lives. See the note at the top of this file. */
  place: 'right' | 'wide' | 'center' | 'full'
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
    /** Measured once per build; see `anchors()`. */
    let stops: number[] = ANCHORS
    /** Ink, then the five accents the page already uses for meaning. */
    let palette = ['#141413', '#1A5C7A', '#96650C', '#2F6F4E', '#A93226', '#8C877C']
    /** Light ink means a dark page, where the same alpha reads fainter. */
    let baseAlpha = 0.13
    let inkIsLight = false
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
      /* HOW DARK A DOT IS, AND WHY IT IS NOT 13% ANY MORE.
       *
       * The light theme ran the field at 13%. Measured over every lit pixel
       * that came to a mean alpha of 45 out of 255, which composites to about
       * RGB 209 on a paper of 250 -- a grey so pale that on a bright screen
       * the field was there and could not be seen. The dark theme was already
       * at 20% and read fine, which was the clue: the problem was never the
       * ink, it was the value.
       *
       * Both are 20% now. The field still sits well under the type it passes
       * behind -- body copy on this page is ink at full strength -- and the
       * marks in the margins, which have nothing over them at all, finally
       * read at a glance. */
      inkIsLight = light(palette[0])
      baseAlpha = inkIsLight ? 0.20 : 0.20

      shapes = [shapeIndia(data.current), shapeWave(), shapeCurve(),
                splitPanel(bands(w, h)), splitOrder(bands(w, h)),
                splitNetwork(bands(w, h)), shapeSpiral()]
      stops = anchors(h)
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
     *  measure and that is where the room usually is. Where a full-width grid
     *  leaves neither margin worth having, it returns the middle anyway: the
     *  cards are glass, so the shape is dimmed rather than deleted, and a
     *  dimmed shape beats a shape that jumps out of the way. */
    /** Where a shape's unit box lands. A pure function of the shape and the
     *  window: nothing here can change while you scroll, so nothing can jump. */
    function fit(sh: Shape) {
      // 'full' shapes are already written in viewport coordinates, because
      // they are two things at once -- a group in each margin -- and a single
      // box could not hold both.
      if (sh.place === 'full') return { x: 0, y: 0, sx: w, sy: h }
      const fh = h * FRAME_H
      const y = (h - fh) / 2
      if (sh.place === 'wide') {
        const x0 = w * 0.05, bw = w * 0.90
        if (!sh.aspect) return { x: x0, y, sx: bw, sy: fh }
        const sw = Math.min(bw, fh * sh.aspect), sy = sw / sh.aspect
        return { x: x0 + (bw - sw) / 2, y: (h - sy) / 2, sx: sw, sy }
      }
      const bw = sh.place === 'center' ? Math.min(w * 0.62, fh) : Math.min(w * 0.52, fh)
      const x0 = sh.place === 'center' ? (w - bw) / 2 : w - 12 - bw
      if (!sh.aspect) return { x: x0, y, sx: bw, sy: fh }
      const sw = Math.min(bw, fh * sh.aspect), sy = sw / sh.aspect
      return { x: x0 + (bw - sw) / 2, y: (h - sy) / 2, sx: sw, sy }
    }

    type Box = ReturnType<typeof fit>
    const unit = (b: Box, sh: Shape, k: number) =>
      [b.x + sh.p[k * 2] * b.sx, b.y + sh.p[k * 2 + 1] * b.sy] as const

    function draw() {
      ctx!.clearRect(0, 0, w, h)
      const segs = shapes.length - 1
      let f = at <= stops[0] ? 0 : segs
      for (let k = 0; k < segs; k++) {
        if (at >= stops[k] && at <= stops[k + 1]) {
          f = k + (at - stops[k]) / (stops[k + 1] - stops[k])
          break
        }
      }
      f = Math.min(segs - 1e-6, Math.max(0, f))
      const i = Math.floor(f)
      const a = shapes[i], b = shapes[i + 1]
      // smoothstep, so each shape holds still for a moment before dissolving
      const u = f - i
      const t = u * u * (3 - 2 * u)

      const A = fit(a), B = fit(b)
      /* A dot's radius. The floor was 0.6, and a 0.6px circle is mostly
       * antialiasing: the browser spreads it over four pixels at a fraction of
       * the alpha it was given, so the value set above was never the value
       * drawn. 0.7 is the smallest that still lands as a dot. */
      const rf = 0.7 + 0.45 * Math.min(1, w / 1300)

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
        ctx!.globalAlpha = tone === 5 ? 0.42 : 0.68
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
      ctx!.globalAlpha = inkIsLight ? 0.55 : 0.52
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
  return { p: out, aspect: MASK_W / MASK_H, place: 'right' }
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
  return { p: out, aspect: 0, place: 'wide' }
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
  return { p: out, aspect: 0, place: 'wide' }
}

/** THE SPIRAL -- the atmosphere itself.
 *
 *  A plain Archimedean spiral: every turn the same distance from the last,
 *  which is the one spiral a person reads as a spiral rather than as a swirl.
 *  It replaced a drawn vortex with sweeping arms -- that had the right subject
 *  and the wrong picture, a busy mass where a clean line was wanted.
 *
 *  The page opens on a country full of instruments and closes on the
 *  circulation they are pointed at. The points are laid along the curve in
 *  index order, so the 344 stations -- the last of them, and the darkest --
 *  land on the outermost turn and the rim reads strongest.
 *
 *  `sqrt` on the parameter is what keeps the spacing even: sampled straight,
 *  the points crowd the centre and thin out to nothing at the rim, because a
 *  turn near the middle is short and a turn at the edge is long. */
function shapeSpiral(): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(41)
  const TURNS = 3.4
  for (let k = 0; k < N; k++) {
    const t = Math.sqrt((k + 0.5) / N)
    const th = t * TURNS * Math.PI * 2
    const r = 0.47 * t
    out[k * 2] = 0.5 + Math.cos(th) * r + (rand() - 0.5) * 0.012
    out[k * 2 + 1] = 0.5 + Math.sin(th) * r + (rand() - 0.5) * 0.012
  }
  return { p: out, aspect: 1, place: 'center' }
}

/* ------------------------------------------------------- the margin glyphs
 *
 * THE MIDDLE OF THE PAGE BELONGS TO THE CONTENT, SO THE FIELD TAKES THE EDGES.
 *
 * Between the three specialists and the results the page is all cards, and a
 * single formation there is either hidden behind them or shrunk to nothing. So
 * for those three sections the population divides into the two margins and
 * builds several small things instead of one big one: the instruments the
 * product actually reads -- a thermometer, a barometer dial, a hygrometer's
 * droplet -- with plain geometry between them.
 *
 * Instruments rather than abstract marks because this is a page about
 * instruments; geometry between them because at 157px a glyph that is almost a
 * picture is worse than one that is plainly a shape.
 *
 * The sides alternate their weight -- left, right, left -- so the stretch has a
 * rhythm and the dots visibly cross the page as you scroll, instead of three
 * identical screens with two busy margins.
 *
 * Every glyph is written in its own unit square and placed by slot. The bands
 * are fixed fractions of the viewport, so like every other placement in this
 * file they cannot change while you scroll, and nothing can jump.
 */

/** Points along a polyline, spaced evenly by length. The workhorse: most of
 *  these glyphs are outlines, and an outline is a polyline. */
function poly(pts: number[][], n: number, rand: () => number, close = true): Float32Array {
  const p = close ? [...pts, pts[0]] : pts
  const seg: number[] = []
  let total = 0
  for (let i = 1; i < p.length; i++) {
    const d = Math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1])
    seg.push(d); total += d
  }
  const out = new Float32Array(n * 2)
  for (let k = 0; k < n; k++) {
    let d = ((k + 0.5) / n) * total, i = 0
    while (i < seg.length - 1 && d > seg[i]) { d -= seg[i]; i++ }
    const t = seg[i] ? d / seg[i] : 0
    out[k * 2] = p[i][0] + (p[i + 1][0] - p[i][0]) * t + (rand() - 0.5) * 0.02
    out[k * 2 + 1] = p[i][1] + (p[i + 1][1] - p[i][1]) * t + (rand() - 0.5) * 0.02
  }
  return out
}

function ngon(sides: number, r: number, turn = 0): number[][] {
  const p: number[][] = []
  for (let i = 0; i < sides; i++) {
    const a = turn + (i / sides) * Math.PI * 2
    p.push([0.5 + Math.cos(a) * r, 0.5 + Math.sin(a) * r])
  }
  return p
}

type Glyph = (n: number, rand: () => number) => Float32Array

/** Points along an arc, appended to a path under construction. Canvas y grows
 *  downward, so a negative angle is up. */
function arc(pts: number[][], cx: number, cy: number, r: number,
             a0: number, a1: number, steps: number) {
  for (let i = 0; i <= steps; i++) {
    const a = a0 + ((a1 - a0) * i) / steps
    pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r])
  }
}

/** DATA QUALITY -- a reading, plotted.
 *
 *  A jagged line over a baseline: the observation stream this agent reads, and
 *  the only one of the three whose subject is a series rather than a thing. */
const gChart: Glyph = (n, rand) => {
  const base = poly([[0.06, 0.86], [0.94, 0.86]], Math.round(n * 0.22), rand, false)
  const line = poly([[0.07, 0.66], [0.21, 0.42], [0.33, 0.56], [0.46, 0.24],
                     [0.59, 0.48], [0.73, 0.18], [0.90, 0.40]],
                    n - Math.round(n * 0.22), rand, false)
  const o = new Float32Array(n * 2)
  o.set(base, 0); o.set(line, base.length)
  return o
}

/** HARDWARE HEALTH -- a pulse.
 *
 *  The trace a monitor draws, because that is exactly what this agent is: the
 *  device's own vital signs, read from the housekeeping channel rather than
 *  from the weather. Flat, flat, a spike, and flat again. */
const gPulse: Glyph = (n, rand) =>
  poly([[0.05, 0.50], [0.30, 0.50], [0.37, 0.50], [0.44, 0.16],
        [0.52, 0.84], [0.60, 0.42], [0.68, 0.50], [0.95, 0.50]], n, rand, false)

/** WEATHER OR FAULT -- a cloud.
 *
 *  The one mark nobody has to be taught. This agent's whole job is to ask
 *  whether the neighbours moved too, and the neighbours move because of this. */
const gCloudLine: Glyph = (n, rand) => {
  const pts: number[][] = [[0.16, 0.76], [0.82, 0.76]]
  arc(pts, 0.70, 0.64, 0.155, 0.40, -Math.PI * 0.95, 14)
  arc(pts, 0.47, 0.52, 0.225, -0.08, -Math.PI, 18)
  arc(pts, 0.25, 0.64, 0.155, -0.10, -Math.PI * 1.06, 14)
  return poly(pts, n, rand, false)
}

const gRing: Glyph = (n, rand) => poly(ngon(48, 0.40), n, rand)
const gTri: Glyph = (n, rand) => poly(ngon(3, 0.44, -Math.PI / 2), n, rand)

/** A thermometer: a stem, and a bulb that is filled, because a thermometer
 *  with an empty bulb reads as a nail. */
const gThermo: Glyph = (n, rand) => {
  const stemN = Math.round(n * 0.55)
  const stem = poly([[0.40, 0.10], [0.60, 0.10], [0.60, 0.62], [0.40, 0.62]], stemN, rand)
  const o = new Float32Array(n * 2)
  o.set(stem, 0)
  for (let k = stemN; k < n; k++) {
    const a = rand() * Math.PI * 2, r = 0.19 * Math.sqrt(rand())
    o[k * 2] = 0.5 + Math.cos(a) * r; o[k * 2 + 1] = 0.76 + Math.sin(a) * r
  }
  return o
}

/** A barometer: a face, a needle, and the tick marks that make a circle read
 *  as an instrument rather than as a ring. */
const gDial: Glyph = (n, rand) => {
  const faceN = Math.round(n * 0.52)
  const needleN = Math.round(n * 0.22)
  const o = new Float32Array(n * 2)
  o.set(poly(ngon(48, 0.42), faceN, rand), 0)
  o.set(poly([[0.5, 0.5], [0.73, 0.29]], needleN, rand, false), faceN * 2)
  const rest = n - faceN - needleN
  for (let i = 0; i < rest; i++) {
    const k = faceN + needleN + i
    const a = (i / Math.max(1, rest)) * Math.PI * 2
    o[k * 2] = 0.5 + Math.cos(a) * 0.32; o[k * 2 + 1] = 0.5 + Math.sin(a) * 0.32
  }
  return o
}

/** Humidity, as the drop it is measured from. */
const gDrop: Glyph = (n, rand) => {
  const pts: number[][] = []
  for (let i = 0; i <= 44; i++) {
    const a = -Math.PI / 2 + (i / 44) * Math.PI * 2
    const r = 0.34 * (1 + 0.55 * Math.sin(a))
    pts.push([0.5 + Math.cos(a) * r * 0.85, 0.58 + Math.sin(a) * r])
  }
  return poly(pts, n, rand, false)
}

/** Three stops on one route: detect, diagnose, dispatch. */
const gRoute: Glyph = (n, rand) => {
  const lineN = Math.round(n * 0.24)
  const o = new Float32Array(n * 2)
  o.set(poly([[0.5, 0.08], [0.5, 0.92]], lineN, rand, false), 0)
  let k = lineN
  const per = Math.max(1, Math.floor((n - lineN) / 3))
  for (let s = 0; s < 3 && k < n; s++) {
    const cy = 0.20 + s * 0.30
    for (let i = 0; i < per && k < n; i++, k++) {
      const a = (i / per) * Math.PI * 2
      o[k * 2] = 0.5 + Math.cos(a) * 0.21; o[k * 2 + 1] = cy + Math.sin(a) * 0.21
    }
  }
  for (; k < n; k++) { o[k * 2] = 0.5; o[k * 2 + 1] = 0.82 }
  return o
}

/** The closed job: a box with a tick in it. */
const gTick: Glyph = (n, rand) => {
  const boxN = Math.round(n * 0.55)
  const o = new Float32Array(n * 2)
  o.set(poly([[0.12, 0.12], [0.88, 0.12], [0.88, 0.88], [0.12, 0.88]], boxN, rand), 0)
  o.set(poly([[0.26, 0.52], [0.44, 0.70], [0.76, 0.30]], n - boxN, rand, false), boxN * 2)
  return o
}


/** THE MARGINS ARE THE PAGE'S MARGINS, NOT A GUESS AT THEM.
 *
 *  The bands used to be flat fractions of the viewport -- 2.2% to 13.7% on the
 *  left, 86.3% to 97.8% on the right -- which at 1425px put their inner edges
 *  at 195 and 1230 while the content column runs 163 to 1263. Every glyph
 *  overlapped a card by about 32px, which reads as a mark that missed rather
 *  than a mark that was placed.
 *
 *  So they are derived from the same measure the layout uses: a column of at
 *  most 1100px, centred, with a 20px gutter. The band hugs that column's edge
 *  with a hairline of air, which is the one position that looks deliberate.
 *  It is still a pure function of the window -- no DOM is read, nothing can
 *  change while you scroll -- so it cannot bring back the jumping.
 *
 *  A glyph is capped at 190px so that a wide screen gets more air rather than
 *  enormous marks; on a narrow one, where there is no margin to have, the band
 *  sits over the glass instead and the glyph is dimmed rather than misplaced.
 */
/* WHERE THE SHAPES ARE FULLY THEMSELVES, MEASURED RATHER THAN WRITTEN DOWN.
 *
 * These used to be seven constants tuned by hand against the page as it stood.
 * Then the copy was rewritten, the page lost nine hundred pixels, and every
 * section slid out from under its formation: the web arrived a screen early,
 * the curve sat against the wrong step. A number tuned against a layout is a
 * number that breaks the next time anyone edits a sentence.
 *
 * So they are read off the layout instead. Each formation is pinned to the
 * thing it illustrates -- the map to the hero, the wave and the curve to the
 * steps of the detection sequence, the rest to their own sections -- and a
 * small offset puts the shape fully formed a moment after the heading lands,
 * while the body beneath it is being read.
 *
 * This runs ONCE, inside build, not per frame. The offsets are document
 * positions, which do not change as you scroll, so this cannot bring back the
 * jumping that measuring per frame used to cause. If the page is not the shape
 * this expects -- fewer sections, no steps -- it returns the constants above
 * rather than guessing.
 */
function anchors(h: number): number[] {
  const d = document.documentElement
  const span = d.scrollHeight - h
  const host = document.querySelector('[data-field-content]')
  if (span <= 0 || !host) return ANCHORS
  const secs = [...host.querySelectorAll(':scope > section')]
  const steps = [...host.querySelectorAll('.sg-story-step')]
  if (secs.length < 6 || steps.length < 4) return ANCHORS

  const at = (el: Element, bias: number) =>
    (el.getBoundingClientRect().top + window.scrollY - h * 0.30) / span + bias
  const out = [
    at(secs[0], 0.03),     // the map, over the hero
    at(steps[1], 0),       // the wave, while the first two steps are read
    at(steps[3], 0),       // the curve, while the last two are
    at(secs[2], 0.04),     // the three specialists
    at(secs[3], 0.04),     // suspicion to work order
    at(secs[4], 0.06),     // built for a network
    1,                     // the spiral, at the foot of the page
  ].map((v) => Math.min(1, Math.max(0, v)))

  // Strictly increasing, or the segment search below divides by zero.
  for (let i = 1; i < out.length; i++) {
    if (out[i] <= out[i - 1]) out[i] = Math.min(1, out[i - 1] + 0.01)
  }
  return out
}

interface Bands { lx0: number; rx0: number; bw: number; ar: number }

function bands(w: number, h: number): Bands {
  const AIR = 14
  const col = Math.min(1100, w - 40)
  const left = (w - col) / 2
  let px = Math.min(190, left - AIR - 8)
  const ar = w / h
  if (px < 96) {
    px = Math.min(120, w * 0.17)
    return { lx0: 8 / w, rx0: (w - 8 - px) / w, bw: px / w, ar }
  }
  return {
    lx0: (left - AIR - px) / w,
    rx0: Math.min(w - 8 - px, left + col + AIR) / w,
    bw: px / w,
    ar,
  }
}

interface Slot { g: Glyph; side: 'L' | 'R'; tone?: number }

/** Lay a stack of glyphs down each margin.
 *
 *  `ar` is the viewport's width over its height, and it is here so that a
 *  glyph drawn in a unit square comes out square in pixels: unit space is
 *  stretched by the window, and a circle that forgets that is an egg. */
function compose(seed: number, b: Bands, slots: Slot[], weightL: number): Shape {
  const rand = mulberry(seed)
  const BW = b.bw                        // band width, as a fraction of the page
  const gh = BW * b.ar                   // the same span, measured down the page
  const stack = (side: 'L' | 'R') => slots.filter((s) => s.side === side).length

  const box = (s: Slot, i: number) => {
    const count = stack(s.side)
    const gap = gh * 0.34
    const total = count * gh + (count - 1) * gap
    const k = total > 0.94 ? 0.94 / total : 1
    const H = gh * k, G = gap * k
    return {
      x0: s.side === 'L' ? b.lx0 : b.rx0,
      y0: (1 - (count * H + (count - 1) * G)) / 2 + i * (H + G),
      w: BW * k, h: H,
    }
  }

  // Which dots go to which glyph. A glyph that names an agent takes the dots
  // wearing that agent's colour, so the mark is made of the right points.
  const taken = new Uint8Array(N)
  const buckets: number[][] = slots.map(() => [])
  slots.forEach((s, i) => {
    if (!s.tone) return
    for (let k = 0; k < N; k++) {
      if (!taken[k] && TONE[k] === s.tone) { buckets[i].push(k); taken[k] = 1 }
    }
  })
  const nL = stack('L'), nR = slots.length - nL
  const share = slots.map((s) => (s.side === 'L' ? weightL / nL : (1 - weightL) / nR))
  const target = share.map((f) => Math.round(N * f))
  let gi = 0
  for (let k = 0; k < N; k++) {
    if (taken[k]) continue
    let tries = 0
    while (buckets[gi].length >= target[gi] && tries < slots.length) {
      gi = (gi + 1) % slots.length; tries++
    }
    buckets[gi].push(k)
    gi = (gi + 1) % slots.length
  }

  const out = new Float32Array(N * 2)
  const seen: Record<string, number> = { L: 0, R: 0 }
  slots.forEach((s, i) => {
    const b = box(s, seen[s.side]++)
    const pts = s.g(Math.max(1, buckets[i].length), rand)
    buckets[i].forEach((k, j) => {
      out[k * 2] = b.x0 + pts[j * 2] * b.w
      out[k * 2 + 1] = b.y0 + pts[j * 2 + 1] * b.h
    })
  })
  return { p: out, aspect: 0, place: 'full' }
}

/** THREE SPECIALISTS -- weighted left.
 *
 *  Three different marks, because the agents are not three of a kind: one
 *  reads a series, one reads a device, one reads the sky. A plotted reading, a
 *  monitor's pulse and a cloud -- each in its own colour and built from the
 *  dots that wear that colour everywhere else on the page. Three identical
 *  discs said they were interchangeable, which is the one thing this section
 *  argues against. The arbiter's single ring faces them from the other margin.
 */
function splitPanel(b: Bands): Shape {
  return compose(61, b, [
    { g: gChart, side: 'L', tone: 1 },
    { g: gPulse, side: 'L', tone: 2 },
    { g: gCloudLine, side: 'L', tone: 3 },
    { g: gRing, side: 'R' },
    { g: gTri, side: 'R' },
  ], 0.72)
}

/** SUSPICION TO WORK ORDER -- weighted right.
 *
 *  The route with its three stops and the closed job it ends in, against a
 *  barometer and a square on the quiet side. */
function splitOrder(b: Bands): Shape {
  return compose(67, b, [
    { g: gDrop, side: 'L' },
    { g: gThermo, side: 'L' },
    { g: gDial, side: 'R' },
    { g: gRoute, side: 'R' },
    { g: gTick, side: 'R' },
  ], 0.30)
}

/** BUILT FOR A NETWORK -- one web, spanning both margins.
 *
 *  This section is the one that already owns a real figure: EdgeTiers is a
 *  960px animated diagram of the ingest path. So whatever goes in the margins
 *  must not be a second diagram, and it must not be TWO things either.
 *
 *  It was two things: a mast down the left and a node-link graph down the
 *  right, joined by one long arc. Three faults with that. The sides said
 *  different kinds of thing, so the eye read them as two separate pictures
 *  rather than one. The arc, bowed upward from the top of the mast, sailed
 *  straight over the headline -- the one place on the screen the field should
 *  never be. And a mast is a picture of a pole, which is what the section is
 *  arguing AGAINST: not a demo on a pole, a network.
 *
 *  So it is one web. The same kind of node down both margins, each tied to its
 *  nearest neighbours on its own side, and a few long strands crossing the
 *  page to make the two sides one mesh rather than two columns. Nearest-
 *  neighbour is not a decorative choice: it is the relation the detector runs
 *  on, a station judged against the ones around it.
 *
 *  The crossing strands are nearly level and sit away from the top of the
 *  screen, so they pass behind the cards -- which is what the glass is for --
 *  rather than over the heading.
 *
 *  Written straight in viewport coordinates rather than through the glyph
 *  composer, because a web is one drawing, not a stack of marks in a band.
 */
function splitNetwork(b: Bands): Shape {
  const out = new Float32Array(N * 2)
  const rand = mulberry(71)
  let i = 0
  const put = (x: number, y: number) => {
    if (i >= N) return
    out[i * 2] = x + (rand() - 0.5) * 0.002
    out[i * 2 + 1] = y + (rand() - 0.5) * 0.003
    i++
  }
  /** A run of dots along a gently bowed line. `bow` of 0 is straight. */
  const strand = (x0: number, y0: number, x1: number, y1: number,
                  n: number, bow = 0) => {
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2 + bow
    for (let k = 0; k < n; k++) {
      const t = (k + 0.5) / n, u = 1 - t
      put(u * u * x0 + 2 * u * t * cx + t * t * x1,
          u * u * y0 + 2 * u * t * cy + t * t * y1)
    }
  }

  const gw = b.bw
  const mid = [b.lx0 + gw / 2, b.rx0 + gw / 2]

  // The stations: the same kind of node down both margins, spread over the
  // height so the web is a web and not a column.
  const PER = 9
  const nx: number[] = [], ny: number[] = []
  for (const side of [0, 1]) {
    for (let k = 0; k < PER; k++) {
      const t = (k + 0.5) / PER
      nx.push(mid[side] + (rand() - 0.5) * gw * 0.80)
      ny.push(0.10 + t * 0.80 + (rand() - 0.5) * 0.045)
    }
  }
  const dist = (p: number, q: number) =>
    Math.hypot((nx[p] - nx[q]) * b.ar, ny[p] - ny[q])

  // Each node to its two nearest, and each edge drawn once.
  const drawn = new Set<string>()
  for (let k = 0; k < nx.length; k++) {
    const order = nx.map((_, j) => j)
      .filter((j) => j !== k)
      .sort((p, q) => dist(k, p) - dist(k, q))
    for (let m = 0; m < 2; m++) {
      const j = order[m]
      const key = k < j ? `${k}-${j}` : `${j}-${k}`
      if (drawn.has(key)) continue
      drawn.add(key)
      strand(nx[k], ny[k], nx[j], ny[j], 17)
    }
  }

  /* A NODE IS A RING, NOT A BLOB.
   *
   * Each one used to be thirty-four points scattered inside a 14px disc, which
   * at this dot size is a smudge rather than a station -- and it sat in a page
   * where every other mark is a line drawing. A ring of evenly spaced points
   * with a few in the middle reads as a node at a glance, holds its shape at
   * any size, and costs a third of the dots, which go to the strands instead.
   *
   * Every third one is drawn larger, because a mesh where every node is
   * identical reads as a pattern; a real network has hubs. */
  const RING = 18
  for (let k = 0; k < nx.length; k++) {
    const r = gw * (k % 3 === 0 ? 0.105 : 0.072)
    for (let m = 0; m < RING; m++) {
      const a = (m / RING) * Math.PI * 2
      put(nx[k] + Math.cos(a) * r, ny[k] + Math.sin(a) * r * b.ar)
    }
    for (let m = 0; m < 4; m++) {
      const a = rand() * Math.PI * 2, rr = r * 0.20 * Math.sqrt(rand())
      put(nx[k] + Math.cos(a) * rr, ny[k] + Math.sin(a) * rr * b.ar)
    }
  }

  /* THE STRANDS THAT MAKE IT ONE MESH.
   *
   * Without these the page shows two columns of dots and calls it a network.
   * Three is the right number: one is a rope, five is a grille. They are
   * matched by height so they run nearly level, and bowed by a few percent so
   * they read as slack line rather than as rules across the page. */
  const pairs: [number, number][] = []
  // 2, 4 and 7 rather than 1, 4, 7: the first pair sat at a fifth of the
  // screen, which is where a section's lead paragraph is. A strand behind a
  // line of type is fine; a strand behind the sentence you are reading is not.
  for (const k of [2, 4, 7]) {
    let best = PER, bd = 9
    for (let j = PER; j < nx.length; j++) {
      const d = Math.abs(ny[j] - ny[k])
      if (d < bd && !pairs.some((p) => p[1] === j)) { bd = d; best = j }
    }
    pairs.push([k, best])
  }
  const rest = N - i
  const per = Math.floor(rest / pairs.length)
  pairs.forEach(([k, j], n) => {
    strand(nx[k], ny[k], nx[j], ny[j], n === pairs.length - 1 ? N - i : per,
           (n % 2 ? 0.055 : -0.045))
  })

  return { p: out, aspect: 0, place: 'full' }
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
