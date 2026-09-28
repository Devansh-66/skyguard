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
  /** Depth in [-1, 1] per point, for the shapes that are solids rather than
   *  drawings. Near points are drawn larger and at higher contrast, which is
   *  the whole of the three-dimensional effect. A shape without it is flat,
   *  and flat is the neutral value: a depth of 0 changes nothing. */
  z?: Float32Array
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
    /** Resolved positions and depths for the current frame. Allocated once:
     *  1,500 points redrawn sixty times a second is not the place to be
     *  handing the collector three arrays a frame. */
    const PX = new Float32Array(N), PY = new Float32Array(N), PZ = new Float32Array(N)

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
      // On a dark page the ink is a pale colour, and pale-on-dark at the same
      // alpha reads noticeably fainter than dark-on-pale. It gets more.
      inkIsLight = light(palette[0])
      baseAlpha = inkIsLight ? 0.20 : 0.13

      const ar = w / h
      shapes = [shapeIndia(data.current), shapeWave(), shapeCurve(),
                splitPanel(ar), splitOrder(ar), splitNetwork(ar), shapeSpiral()]
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

      const A = fit(a), B = fit(b)
      const rf = 0.6 + 0.4 * Math.min(1, w / 1300)

      /* Resolve the whole population once, rather than once per colour pass.
       * The passes below then only read, which is what makes a dozen of them
       * affordable. */
      for (let k = 0; k < N; k++) {
        const ax = A.x + a.p[k * 2] * A.sx, ay = A.y + a.p[k * 2 + 1] * A.sy
        const bx = B.x + b.p[k * 2] * B.sx, by = B.y + b.p[k * 2 + 1] * B.sy
        PX[k] = ax + (bx - ax) * t
        PY[k] = ay + (by - ay) * t
        const za = a.z ? a.z[k] : 0, zb = b.z ? b.z[k] : 0
        PZ[k] = za + (zb - za) * t
      }

      /* DEPTH IS DRAWN TWICE: IN SIZE, AND IN CONTRAST.
       *
       * Size alone gives a weak read and contrast alone gives a flat one; a
       * solid only looks solid when its near face is both bigger and darker
       * than its far one. Size can vary per point inside a single path, but
       * alpha cannot, so each group is drawn in two passes split at z = 0.
       * Two bands are enough -- the size gradient carries the rest. */
      const pass = (from: number, to: number, keep: (k: number) => boolean,
                    baseR: number, alpha: number) => {
        for (let near = 0; near < 2; near++) {
          ctx!.globalAlpha = alpha * (near ? 1.34 : 0.74)
          ctx!.beginPath()
          for (let k = from; k < to; k++) {
            if (!keep(k)) continue
            if ((PZ[k] > 0 ? 1 : 0) !== near) continue
            const r = rf * baseR * (1 + 0.45 * PZ[k])
            ctx!.moveTo(PX[k] + r, PY[k]); ctx!.arc(PX[k], PY[k], r, 0, Math.PI * 2)
          }
          ctx!.fill()
        }
      }

      // the field: plain ink, quiet
      ctx!.fillStyle = palette[0]
      pass(0, N - STATIONS, (k) => !TONE[k], 1, baseAlpha)

      /* THE COLOURED DOTS ARE THE PAGE'S OWN VOCABULARY.
       *
       * They are not sprinkles: a dot wearing the data-quality blue is a dot
       * that builds the data-quality drum in the margin, and the red ones are
       * the failing station -- the same points that sit out in the tail of the
       * distribution, wherever else the field goes. */
      for (let tone = 1; tone < palette.length; tone++) {
        ctx!.fillStyle = palette[tone]
        pass(0, N, (k) => TONE[k] === tone,
             1.3, tone === 5 ? 0.34 : 0.62)
      }

      // the stations: ink again, and bigger, because they are the subject
      ctx!.fillStyle = palette[0]
      pass(N - STATIONS, N, (k) => !TONE[k], 1.7, inkIsLight ? 0.55 : 0.42)
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
 * single formation there was either hidden behind them or shrunk to a smudge.
 * So for those three sections the population divides into the two margins and
 * builds several small things instead of one big one.
 *
 * THEY ARE SOLIDS, NOT OUTLINES
 *
 * The first version of these drew line art: a ring, a square, a triangle. A
 * ring of dots is a circle and nothing more -- there is no way to tell it from
 * a hole. So every glyph here is points sampled on the SURFACE OF A SOLID and
 * carries a depth with it, and the draw stage uses that depth twice: near
 * points are drawn larger and at higher contrast than far ones. That is what
 * makes a scatter of dots read as a ball rather than as a circle, and it costs
 * one extra number per point.
 *
 * The view is a fixed oblique one -- slightly above, slightly to the side --
 * because a solid seen straight on is a silhouette, which is an outline again.
 *
 * THE THREE SPECIALISTS ARE THREE DIFFERENT THINGS
 *
 * They used to be three identical discs in three colours, which said the
 * agents are interchangeable. They are not: one reads the observation stream,
 * one reads the device, one reads the weather around it. So each gets the
 * figure its own subject would be drawn as -- a drum for the data, a chip for
 * the hardware, a cloud for the weather -- in its own colour.
 *
 * The bands are fixed fractions of the viewport, so like every other placement
 * in this file they cannot change while you scroll, and nothing can jump.
 */

/** A glyph's points, in its own unit square, with a depth in [-1, 1]. */
interface Cloud3D { p: Float32Array; z: Float32Array }

const TAU = Math.PI * 2

/** The one view everything is seen from: a little above, a little to the side.
 *
 *  Model space is centred on the origin with Y up and Z toward the viewer.
 *  The projection is oblique rather than perspective because these are 150px
 *  objects -- a vanishing point at that size is a distortion nobody reads as
 *  depth, while the shading does the work on its own. */
const SCALE = 1.34   // so a solid fills its cell instead of floating in it

function project(X: number, Y: number, Z: number) {
  const x = X * SCALE, y = Y * SCALE, z = Z * SCALE
  return {
    x: 0.5 + x + z * 0.20,
    y: 0.5 - y * 0.88 + z * 0.26,
    d: z * 0.90 + y * 0.30,
  }
}

/** A scratch builder: glyphs push points into it and it hands back a cloud. */
function builder(n: number) {
  const p = new Float32Array(n * 2)
  const z = new Float32Array(n)
  let i = 0
  return {
    get left() { return n - i },
    at(X: number, Y: number, Z: number) {
      if (i >= n) return
      const q = project(X, Y, Z)
      p[i * 2] = q.x; p[i * 2 + 1] = q.y; z[i] = Math.max(-1, Math.min(1, q.d * 2.2))
      i++
    },
    done(): Cloud3D {
      // Anything unclaimed sits at the centre rather than at (0,0), which
      // would be a stray dot in the corner of every glyph that rounds down.
      while (i < n) this.at(0, 0, 0)
      return { p, z }
    },
  }
}

type B = ReturnType<typeof builder>
type Rand = () => number

/** Points spread evenly over a sphere's surface. The `u` trick is what keeps
 *  them even: sampling the angle directly crowds both poles. */
function sphere(b: B, n: number, cx: number, cy: number, cz: number, r: number, rand: Rand) {
  for (let k = 0; k < n; k++) {
    const u = rand() * 2 - 1, th = rand() * TAU, s = Math.sqrt(1 - u * u)
    b.at(cx + s * Math.cos(th) * r, cy + u * r, cz + s * Math.sin(th) * r)
  }
}

/** A cylinder standing on its axis: the curved side, and a cap on top. */
function cylinder(b: B, n: number, cx: number, cy: number, r: number, h: number,
                  rand: Rand, caps = true) {
  const capN = caps ? Math.round(n * 0.26) : 0
  for (let k = 0; k < n - capN; k++) {
    const th = rand() * TAU
    b.at(cx + Math.cos(th) * r, cy + (rand() - 0.5) * h, Math.sin(th) * r)
  }
  for (let k = 0; k < capN; k++) {
    const th = rand() * TAU, rr = r * Math.sqrt(rand())
    b.at(cx + Math.cos(th) * rr, cy + h / 2, Math.sin(th) * rr)
  }
}

/** A box, sampled over its faces in proportion to their area, so a flat slab
 *  does not end up with as many points on its edge as on its face. */
function box(b: B, n: number, cx: number, cy: number, cz: number,
             sx: number, sy: number, sz: number, rand: Rand) {
  const areas = [sx * sy, sx * sy, sy * sz, sy * sz, sx * sz, sx * sz]
  const total = areas.reduce((a, v) => a + v, 0)
  for (let k = 0; k < n; k++) {
    let pick = rand() * total, f = 0
    while (f < 5 && pick > areas[f]) { pick -= areas[f]; f++ }
    const a = rand() - 0.5, c = rand() - 0.5
    if (f < 2) b.at(cx + a * sx, cy + c * sy, cz + (f ? -0.5 : 0.5) * sz)
    else if (f < 4) b.at(cx + (f === 2 ? 0.5 : -0.5) * sx, cy + a * sy, cz + c * sz)
    else b.at(cx + a * sx, cy + (f === 4 ? 0.5 : -0.5) * sy, cz + c * sz)
  }
}

/* --------------------------------------------------------------- the glyphs */

type Glyph = (n: number, rand: Rand) => Cloud3D

/** DATA QUALITY -- a drum.
 *  The shape every stored stream has been drawn as for forty years: a cylinder
 *  with a rim where each layer meets the next. What this agent reads is the
 *  observation stream, so it gets the stream's own figure. */
const gDrum: Glyph = (n, rand) => {
  const b = builder(n)
  const r = 0.30, h = 0.46
  cylinder(b, Math.round(n * 0.62), 0, 0, r, h, rand, false)
  // the rims: three discs up the drum, which is what makes it a drum and not
  // a tin can
  const ring = Math.round(n * 0.38 / 3)
  for (let i = 0; i < 3; i++) {
    const y = h / 2 - i * (h / 2.2)
    for (let k = 0; k < ring; k++) {
      const th = rand() * TAU
      const rr = i === 0 ? r * Math.sqrt(rand()) : r * (0.96 + rand() * 0.08)
      b.at(Math.cos(th) * rr, y, Math.sin(th) * rr)
    }
  }
  return b.done()
}

/** HARDWARE HEALTH -- a chip.
 *  A flat package with two rows of legs. Nobody has to be told what it is, and
 *  it is literally what this agent is asking about: the board on the pole. */
const gChip: Glyph = (n, rand) => {
  const b = builder(n)
  box(b, Math.round(n * 0.66), 0, 0.03, 0, 0.40, 0.20, 0.34, rand)
  const legs = 4, per = Math.max(1, Math.round(n * 0.34 / (legs * 2)))
  for (let i = 0; i < legs; i++) {
    const z = -0.13 + (i / (legs - 1)) * 0.26
    for (const side of [-1, 1]) {
      box(b, per, side * 0.28, -0.09, z, 0.16, 0.055, 0.04, rand)
    }
  }
  return b.done()
}

/** WEATHER OR FAULT -- a cloud.
 *  Three overlapping balls, which is how a cloud has been drawn since anyone
 *  drew one. This agent's whole job is to ask whether the neighbours moved
 *  too, and the neighbours move because of this. */
const gCloud: Glyph = (n, rand) => {
  const b = builder(n)
  const lobes: [number, number, number, number][] = [
    [-0.17, -0.03, 0.02, 0.17],
    [0.02, 0.06, -0.02, 0.22],
    [0.20, -0.02, 0.03, 0.16],
    [0.02, -0.08, 0.10, 0.15],
  ]
  const per = Math.floor(n / lobes.length)
  for (const [x, y, z, r] of lobes) sphere(b, per, x, y, z, r, rand)
  return b.done()
}

/** A sphere on its own: the arbiter's single decision. */
const gBall: Glyph = (n, rand) => {
  const b = builder(n)
  sphere(b, n, 0, 0, 0, 0.34, rand)
  return b.done()
}

/** A cube. Plain, solid, and the only thing on the page with a right angle. */
const gCube: Glyph = (n, rand) => {
  const b = builder(n)
  box(b, n, 0, 0, 0, 0.42, 0.42, 0.42, rand)
  return b.done()
}

/** A thermometer: a stem with a ball of mercury at the bottom. */
const gThermo: Glyph = (n, rand) => {
  const b = builder(n)
  cylinder(b, Math.round(n * 0.55), 0, 0.10, 0.075, 0.52, rand)
  sphere(b, n - Math.round(n * 0.55), 0, -0.24, 0, 0.16, rand)
  return b.done()
}

/** A barometer: a coin-thin drum seen from above and the side at once, with a
 *  needle standing proud of its face. */
const gDial: Glyph = (n, rand) => {
  const b = builder(n)
  const faceN = Math.round(n * 0.46), rimN = Math.round(n * 0.26)
  for (let k = 0; k < faceN; k++) {
    const th = rand() * TAU, rr = 0.32 * Math.sqrt(rand())
    b.at(Math.cos(th) * rr, 0.07, Math.sin(th) * rr)
  }
  for (let k = 0; k < rimN; k++) {
    const th = rand() * TAU
    b.at(Math.cos(th) * 0.32, 0.07 - rand() * 0.10, Math.sin(th) * 0.32)
  }
  const rest = n - faceN - rimN
  for (let k = 0; k < rest; k++) {
    const t = k / Math.max(1, rest)
    b.at(t * 0.22, 0.10, -t * 0.16)
  }
  return b.done()
}

/** Humidity, as the drop it is measured from: a ball drawn up to a point. */
const gDrop: Glyph = (n, rand) => {
  const b = builder(n)
  for (let k = 0; k < n; k++) {
    // a teardrop is a sphere whose radius falls away toward the top
    const u = rand() * 2 - 1, th = rand() * TAU
    const taper = Math.pow((1 - u) / 2, 1.5)
    const r = 0.30 * Math.sqrt(1 - u * u) * (0.35 + 0.65 * taper)
    b.at(Math.cos(th) * r, -u * 0.34 - 0.02, Math.sin(th) * r)
  }
  return b.done()
}

/** Three stops on one route: detect, diagnose, dispatch. */
const gRoute: Glyph = (n, rand) => {
  const b = builder(n)
  const stopN = Math.round(n * 0.24)
  for (let i = 0; i < 3; i++) sphere(b, stopN, 0, 0.30 - i * 0.30, 0, 0.115, rand)
  const rest = b.left
  for (let k = 0; k < rest; k++) {
    b.at((rand() - 0.5) * 0.03, 0.30 - (k / rest) * 0.60, (rand() - 0.5) * 0.03)
  }
  return b.done()
}

/** The closed job: a solid block with a tick standing on its face. */
const gDone: Glyph = (n, rand) => {
  const b = builder(n)
  box(b, Math.round(n * 0.64), 0, 0, 0, 0.40, 0.40, 0.30, rand)
  const rest = b.left
  const path: [number, number][] = [[-0.15, 0.00], [-0.04, -0.11], [0.17, 0.15]]
  for (let k = 0; k < rest; k++) {
    const t = (k / rest) * 2
    const i = t < 1 ? 0 : 1, f = t < 1 ? t : t - 1
    const x = path[i][0] + (path[i + 1][0] - path[i][0]) * f
    const y = path[i][1] + (path[i + 1][1] - path[i][1]) * f
    b.at(x, y, 0.17 + (rand() - 0.5) * 0.02)
  }
  return b.done()
}

/** One node on a pole: a hexagonal prism, which is the shape a screen's
 *  louvres make and the shape a cell of a network is drawn as. */
const gPrism: Glyph = (n, rand) => {
  const b = builder(n)
  const r = 0.32, h = 0.34
  const sideN = Math.round(n * 0.7), per = Math.max(1, Math.round(sideN / 6))
  for (let f = 0; f < 6; f++) {
    const a0 = (f / 6) * TAU, a1 = ((f + 1) / 6) * TAU
    for (let k = 0; k < per; k++) {
      const t = rand()
      const x = Math.cos(a0) * r + (Math.cos(a1) - Math.cos(a0)) * r * t
      const z = Math.sin(a0) * r + (Math.sin(a1) - Math.sin(a0)) * r * t
      b.at(x, (rand() - 0.5) * h, z)
    }
  }
  const rest = b.left
  for (let k = 0; k < rest; k++) {
    const th = rand() * TAU, rr = r * Math.sqrt(rand())
    b.at(Math.cos(th) * rr, h / 2, Math.sin(th) * rr)
  }
  return b.done()
}

/** The network: a field of small balls on a plane, receding. The same node,
 *  four hundred times. */
const gField: Glyph = (n, rand) => {
  const b = builder(n)
  const cols = 6, rows = 6, per = Math.max(1, Math.floor(n / (cols * rows)))
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const x = -0.34 + (c + (r % 2 ? 0.5 : 0)) * (0.68 / (cols - 1))
      const z = -0.30 + r * (0.60 / (rows - 1))
      sphere(b, per, x, -0.06 + z * 0.10, z, 0.042, rand)
    }
  }
  return b.done()
}

interface Slot { g: Glyph; side: 'L' | 'R'; tone?: number }

/** Lay a stack of glyphs down each margin.
 *
 *  `ar` is the viewport's width over its height, and it is here so a glyph
 *  drawn in a unit square comes out square in pixels: unit space is stretched
 *  by the window, and a ball that forgets that is an egg. */
function compose(seed: number, ar: number, slots: Slot[], weightL: number): Shape {
  const rand = mulberry(seed)
  const BW = 0.115                       // band width, as a fraction of the page
  const gh = BW * ar                     // the same span, measured down the page
  const stack = (side: 'L' | 'R') => slots.filter((s) => s.side === side).length

  const cell = (s: Slot, i: number) => {
    const count = stack(s.side)
    const gap = gh * 0.30
    const total = count * gh + (count - 1) * gap
    const k = total > 0.94 ? 0.94 / total : 1
    const H = gh * k, G = gap * k
    return {
      x0: s.side === 'L' ? 0.022 : 0.863,
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
  const depth = new Float32Array(N)
  const seen: Record<string, number> = { L: 0, R: 0 }
  slots.forEach((s, i) => {
    const b = cell(s, seen[s.side]++)
    const c = s.g(Math.max(1, buckets[i].length), rand)
    buckets[i].forEach((k, j) => {
      out[k * 2] = b.x0 + c.p[j * 2] * b.w
      out[k * 2 + 1] = b.y0 + c.p[j * 2 + 1] * b.h
      depth[k] = c.z[j]
    })
  })
  return { p: out, z: depth, aspect: 0, place: 'full' }
}

/** THREE SPECIALISTS -- weighted left.
 *
 *  A drum, a chip and a cloud, in the three agents' own colours and made of
 *  the dots that wear those colours everywhere else on the page: the stream,
 *  the device, and the weather around it. Three identical discs said the
 *  agents were interchangeable, which is the one thing this section is
 *  arguing against. The arbiter's single decision faces them from the other
 *  margin, above the cube that closes every case. */
function splitPanel(ar: number): Shape {
  return compose(61, ar, [
    { g: gDrum, side: 'L', tone: 1 },
    { g: gChip, side: 'L', tone: 2 },
    { g: gCloud, side: 'L', tone: 3 },
    { g: gBall, side: 'R' },
    { g: gCube, side: 'R' },
  ], 0.72)
}

/** SUSPICION TO WORK ORDER -- weighted right.
 *
 *  The route with its three stops and the job it closes, against the
 *  instruments that raised it on the quiet side. */
function splitOrder(ar: number): Shape {
  return compose(67, ar, [
    { g: gDrop, side: 'L' },
    { g: gThermo, side: 'L' },
    { g: gDial, side: 'R' },
    { g: gRoute, side: 'R' },
    { g: gDone, side: 'R' },
  ], 0.30)
}

/** BUILT FOR A NETWORK -- weighted left.
 *
 *  One node on a pole, with the two other things it measures, and the same
 *  node four hundred times over on the far side. */
function splitNetwork(ar: number): Shape {
  return compose(71, ar, [
    { g: gPrism, side: 'L' },
    { g: gThermo, side: 'L' },
    { g: gDrop, side: 'L' },
    { g: gField, side: 'R' },
  ], 0.70)
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
