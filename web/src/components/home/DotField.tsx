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
 * ONE FORMATION, AND ONE PLACE TO PUT IT
 *
 * The shape is centred in the viewport and it stays there. That sounds too
 * simple to be worth a comment, so here is what it replaced and why.
 *
 * A solid card makes a dot behind it not exist, so the field used to find the
 * free space and draw itself there -- whole in a wide margin, torn across two
 * narrow ones. The placement therefore depended on which cards happened to be
 * on screen, and cards scroll. Crossing the boundary where a card entered the
 * viewport, the field changed its mind about where it lived and the shape
 * jumped: the map broke near the top of the page, and the wave broke coming
 * out of it. No amount of better dodging fixes that, because the jump IS the
 * dodging.
 *
 * So the cards became glass instead -- see `.sg-glass` -- and the field stopped
 * dodging. It is placed once, at build, and only a resize moves it. A morph
 * between two shapes is then continuous by construction, which is the only way
 * it can be.
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

/** How much of the viewport a formation is allowed, as a fraction. Short of
 *  the edges so nothing is ever clipped mid-morph. */
const FRAME_W = 0.90
const FRAME_H = 0.86

/** A shape, stored in a unit box: 2N numbers in [0,1]. Unit coordinates are
 *  what let the regions change every frame without rebuilding anything. */
interface Shape {
  p: Float32Array
  /** width/height the shape wants, or 0 for "fill the frame". */
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
      // On a dark page the ink is a pale colour, and pale-on-dark at the same
      // alpha reads noticeably fainter than dark-on-pale. It gets more.
      inkIsLight = light(palette[0])
      baseAlpha = inkIsLight ? 0.20 : 0.13

      shapes = [shapeIndia(data.current), shapeWave(), shapeCurve(),
                shapeCircles(), shapeVortex()]
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

    /** Where a shape's unit box lands on screen. Centred, aspect respected,
     *  and the same every frame until the window changes size. */
    function fit(sh: Shape) {
      const fw = w * FRAME_W, fh = h * FRAME_H
      if (!sh.aspect) return { x: (w - fw) / 2, y: (h - fh) / 2, sx: fw, sy: fh }
      const sw = Math.min(fw, fh * sh.aspect), sy = sw / sh.aspect
      return { x: (w - sw) / 2, y: (h - sy) / 2, sx: sw, sy }
    }

    type Box = ReturnType<typeof fit>
    const unit = (b: Box, sh: Shape, k: number) =>
      [b.x + sh.p[k * 2] * b.sx, b.y + sh.p[k * 2 + 1] * b.sy] as const

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
      const rf = 0.6 + 0.4 * Math.min(1, (w * FRAME_W) / 900)

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
  return { p: out, aspect: 0 }
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
  return { p: out, aspect: 0 }
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
  return { p: out, aspect: 1 }
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
  /* Nine streamlines, not fourteen. With more than that the loops overlap
   * into a solid blob and the shape stops being a spiral -- it has to be
   * possible to follow one turn round with your eye. */
  const LINES = 9, TURNS = 4.2
  const core = Math.round(N * 0.72)
  const per = Math.floor(core / LINES)
  for (let k = 0; k < N; k++) {
    const j = k * 2
    if (k < core) {
      const line = k % LINES
      const q = Math.floor(k / LINES) / per
      const th = (line / LINES) * Math.PI * 2 + q * TURNS * Math.PI * 2
      // tightening as it rises, which is the whole reason a vortex spins up
      const r = 0.33 * (1 - 0.66 * q) * (1 + (rand() - 0.5) * 0.10)
      out[j] = 0.5 + Math.cos(th) * r
      // the loops are ellipses seen obliquely, and the stack rises as it winds
      out[j + 1] = 0.90 - q * 0.78 + Math.sin(th) * r * 0.34
    } else {
      /* The arms: long filaments sweeping in from outside, kept clear of the
       * core so they read as feeding it rather than as part of it. */
      const arm = (k - core) % 7
      const n = Math.floor((N - core) / 7)
      const t = (Math.floor((k - core) / 7) % n) / n
      const R = 1.0 - 0.52 * t
      const ph = (arm / 7) * Math.PI * 2 + t * 1.7
      out[j] = 0.5 + Math.cos(ph) * R * 0.5
      out[j + 1] = 0.52 + Math.sin(ph) * R * 0.30 + (rand() - 0.5) * 0.015
    }
  }
  return { p: out, aspect: 0.62 }
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
