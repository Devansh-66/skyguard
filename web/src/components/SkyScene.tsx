/* A living mountain sky, generated in code and driven by real state.
 *
 * WHY THIS IS NOT A STOCK VIDEO
 *
 * A looping mp4 of somebody else's mountain is a decoration: it weighs
 * megabytes, it says nothing about this network, and it shows the same
 * afternoon at three in the morning. This scene is drawn from numbers instead.
 * The sky is coloured by the real local time; the cloud cover and the darkness
 * of the ridges are driven by how much of the fleet currently needs a
 * technician. When the network is healthy it is a clear dawn. When a third of
 * it is failing, the weather closes in. The hero is a status display that
 * happens to be beautiful, which is the only kind worth putting on a product
 * about instruments.
 *
 * `mediaSrc` exists so a real video can take over later without a rewrite:
 * pass a file and it becomes the background layer, with this canvas behind it.
 *
 * HOW THE MOUNTAINS ARE MADE
 *
 * Each ridge is 1-D midpoint displacement (diamond-square in one dimension),
 * seeded so it is stable across renders -- a skyline that reshuffles on every
 * resize reads as noise, not terrain. Roughness falls with each subdivision,
 * which is what gives a ridgeline its self-similar jaggedness. Far ridges are
 * blended toward the horizon colour: aerial perspective is the single cue that
 * makes layered silhouettes read as distance rather than as stacked paper.
 */
import { useEffect, useRef } from 'react'

export interface SkySceneProps {
  /** 0 = the whole fleet is healthy, 1 = all of it needs a technician. Drives
   *  cloud cover, wind speed and how much light reaches the ridges. */
  unrest?: number
  /** Local hour 0-24. Defaults to the real clock. */
  hour?: number
  /** A video that should take over as the background layer. */
  mediaSrc?: string
}

/* ---------- colour ---------- */

type RGB = [number, number, number]

const mix = (a: RGB, b: RGB, t: number): RGB => [
  a[0] + (b[0] - a[0]) * t,
  a[1] + (b[1] - a[1]) * t,
  a[2] + (b[2] - a[2]) * t,
]

const css = (c: RGB, alpha = 1) =>
  'rgba(' + (c[0] | 0) + ',' + (c[1] | 0) + ',' + (c[2] | 0) + ',' + alpha + ')'

/** Three keyframes of sky -- top, middle, horizon -- keyed to sun altitude. */
// Night is moonlit, not black. Sampled from the rendered canvas, the first
// attempt put the sky at rgb(10,17,40) and the ridges at rgb(14,17,29) -- a
// four-point separation that is invisible on any screen not in a dark room, so
// at 3am the hero was a black rectangle. The floor is lifted until the ridge
// silhouettes read against it.
const NIGHT: [RGB, RGB, RGB] = [[16, 23, 50], [30, 42, 82], [56, 70, 112]]
const DAWN: [RGB, RGB, RGB] = [[22, 35, 68], [92, 62, 96], [232, 132, 88]]
const DAY: [RGB, RGB, RGB] = [[38, 96, 160], [126, 178, 218], [206, 226, 240]]

/** How far unrest is allowed to close the sky in. See the note in `draw`. */
const VISUAL_UNREST_CAP = 0.55

/** Sun altitude in [-1, 1]: peaks at local noon, zero at 06:00 and 18:00. */
const altitude = (hour: number) => Math.sin(((hour - 6) / 12) * Math.PI)

function palette(hour: number): { sky: [RGB, RGB, RGB]; night: number } {
  const a = altitude(hour)
  // Twilight is narrow and does most of the visual work, so it gets its own
  // band rather than being a midpoint between night and day.
  let sky: [RGB, RGB, RGB]
  if (a < -0.2) {
    sky = NIGHT
  } else if (a < 0.15) {
    const t = (a + 0.2) / 0.35
    sky = [
      mix(NIGHT[0], DAWN[0], t),
      mix(NIGHT[1], DAWN[1], t),
      mix(NIGHT[2], DAWN[2], t),
    ]
  } else {
    const t = Math.min((a - 0.15) / 0.45, 1)
    sky = [
      mix(DAWN[0], DAY[0], t),
      mix(DAWN[1], DAY[1], t),
      mix(DAWN[2], DAY[2], t),
    ]
  }
  return { sky, night: Math.max(0, Math.min(1, -a * 1.4 + 0.3)) }
}

/* ---------- terrain ---------- */

/** Deterministic PRNG. A skyline must not reshuffle when the window resizes. */
function rng(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 4294967296
  }
}

/** 1-D midpoint displacement over 2^power + 1 samples, normalised to [0,1]. */
function ridgeline(seed: number, power: number, roughness: number): Float32Array {
  const n = (1 << power) + 1
  const h = new Float32Array(n)
  const rand = rng(seed)
  h[0] = rand() * 0.4
  h[n - 1] = rand() * 0.4
  let step = n - 1
  let scale = 1
  while (step > 1) {
    const half = step >> 1
    for (let i = half; i < n; i += step) {
      h[i] = (h[i - half] + h[i + half]) / 2 + (rand() - 0.5) * scale
    }
    step = half
    scale *= roughness
  }
  let lo = Infinity
  let hi = -Infinity
  for (let i = 0; i < n; i++) {
    if (h[i] < lo) lo = h[i]
    if (h[i] > hi) hi = h[i]
  }
  const span = hi - lo || 1
  for (let i = 0; i < n; i++) h[i] = (h[i] - lo) / span
  return h
}

interface Layer {
  h: Float32Array
  /** 0 = furthest. Controls haze, drift rate and vertical placement. */
  depth: number
  base: number
  amp: number
}

const LAYERS = [
  { seed: 1337, power: 7, rough: 0.56, depth: 0.0, base: 0.62, amp: 0.16 },
  { seed: 9001, power: 7, rough: 0.54, depth: 0.28, base: 0.7, amp: 0.19 },
  { seed: 4242, power: 8, rough: 0.52, depth: 0.55, base: 0.79, amp: 0.22 },
  { seed: 7771, power: 8, rough: 0.5, depth: 0.78, base: 0.9, amp: 0.24 },
  { seed: 2024, power: 8, rough: 0.48, depth: 1.0, base: 1.04, amp: 0.26 },
]

export function SkyScene({ unrest = 0, hour, mediaSrc }: SkySceneProps) {
  const ref = useRef<HTMLCanvasElement | null>(null)

  // The animation loop reads live values through a ref so that a changing
  // unrest figure does not tear down and rebuild the whole scene.
  const state = useRef({ unrest, hour })
  state.current = { unrest, hour }

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const layers: Layer[] = LAYERS.map((l) => ({
      h: ridgeline(l.seed, l.power, l.rough),
      depth: l.depth,
      base: l.base,
      amp: l.amp,
    }))
    const stars = Array.from({ length: 220 }, () => ({
      x: Math.random(),
      y: Math.random() * 0.62,
      r: Math.random() * 1.1 + 0.25,
      p: Math.random() * Math.PI * 2,
    }))
    const clouds = Array.from({ length: 14 }, () => ({
      x: Math.random(),
      y: 0.1 + Math.random() * 0.34,
      w: 0.16 + Math.random() * 0.26,
      h: 0.03 + Math.random() * 0.05,
      v: 0.004 + Math.random() * 0.012,
    }))

    // A visitor who has asked for less motion gets one still frame, not a
    // frozen-looking animation loop burning a core.
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    let w = 0
    let h = 0
    let raf = 0

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const r = canvas.getBoundingClientRect()
      w = Math.max(r.width, 1)
      h = Math.max(r.height, 1)
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    const draw = (ms: number) => {
      const t = still ? 0 : ms / 1000
      // Unrest is capped for DRAWING only; the caption still reports the true
      // figure. Two reasons. A fault archive puts every station in the queue by
      // construction, so the honest input is pinned at 1.0 and an uncapped
      // scene would be permanently overcast -- a status display stuck on one
      // reading shows nothing. And the hero carries the headline: it has to
      // stay legible at the worst value the input can take.
      const u = Math.max(0, Math.min(1, state.current.unrest)) * VISUAL_UNREST_CAP
      const now = new Date()
      const hr = state.current.hour ?? now.getHours() + now.getMinutes() / 60
      const { sky, night } = palette(hr)

      // Unrest drains the colour and closes the sky in. Clamped so that a
      // wholly failing fleet is grim rather than black -- an unreadable page
      // helps nobody.
      const grey: RGB = [58, 60, 68]
      const top = mix(sky[0], grey, u * 0.45)
      const mid = mix(sky[1], grey, u * 0.4)
      const horizon = mix(sky[2], grey, u * 0.35)

      const g = ctx.createLinearGradient(0, 0, 0, h)
      g.addColorStop(0, css(top))
      g.addColorStop(0.55, css(mid))
      g.addColorStop(1, css(horizon))
      ctx.fillStyle = g
      ctx.fillRect(0, 0, w, h)

      // stars, fading as the sun rises and as cloud closes in
      const starA = night * (1 - u * 0.7)
      if (starA > 0.01) {
        ctx.fillStyle = '#EAF0FF'
        for (const s of stars) {
          const tw = 0.55 + 0.45 * Math.sin(t * 1.6 + s.p)
          ctx.globalAlpha = starA * tw
          ctx.beginPath()
          ctx.arc(s.x * w, s.y * h, s.r, 0, Math.PI * 2)
          ctx.fill()
        }
        ctx.globalAlpha = 1
      }

      // sun or moon, tracking an arc across the sky
      const alt = altitude(hr)
      if (alt > -0.35) {
        const cx = ((hr - 6) / 12) * w
        const cy = h * (0.72 - Math.max(alt, 0) * 0.52)
        const warm: RGB = alt < 0.2 ? [255, 190, 130] : [255, 246, 224]
        const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, h * 0.42)
        glow.addColorStop(0, css(warm, 0.55 * (1 - u * 0.6)))
        glow.addColorStop(1, css(warm, 0))
        ctx.fillStyle = glow
        ctx.fillRect(0, 0, w, h)
        ctx.fillStyle = css(warm, 0.9 * (1 - u * 0.5))
        ctx.beginPath()
        ctx.arc(cx, cy, h * 0.022, 0, Math.PI * 2)
        ctx.fill()
      }

      // cloud bank: both count and speed rise with unrest
      const nClouds = Math.round(3 + u * (clouds.length - 3))
      for (let i = 0; i < nClouds; i++) {
        const c = clouds[i]
        const x = (((c.x + t * c.v * (1 + u * 2)) % 1.3) - 0.15) * w
        const y = c.y * h
        const rw = c.w * w
        const rh = c.h * h
        const tint = mix(horizon, [255, 255, 255], 0.45 - u * 0.35)
        const cg = ctx.createRadialGradient(x, y, 0, x, y, rw)
        cg.addColorStop(0, css(tint, 0.3 + u * 0.25))
        cg.addColorStop(1, css(tint, 0))
        ctx.fillStyle = cg
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(1, rh / rw)
        ctx.beginPath()
        ctx.arc(0, 0, rw, 0, Math.PI * 2)
        ctx.fill()
        ctx.restore()
      }

      // ridges, far to near
      for (const L of layers) {
        const n = L.h.length
        // Aerial perspective: distant rock is mostly atmosphere.
        const rock: RGB = [16, 20, 34]
        const shade = mix(horizon, rock, 0.25 + L.depth * 0.72)
        const lit = mix(shade, [0, 0, 0], u * 0.25)
        const drift = still ? 0 : Math.sin(t * 0.05 + L.depth) * 6 * (1 - L.depth)

        ctx.fillStyle = css(lit)
        ctx.beginPath()
        ctx.moveTo(-20, h + 10)
        for (let i = 0; i < n; i++) {
          const x = (i / (n - 1)) * (w + 40) - 20 + drift
          const y = h * (L.base - L.amp) - L.h[i] * L.amp * h + L.amp * h * 0.5
          ctx.lineTo(x, y)
        }
        ctx.lineTo(w + 20, h + 10)
        ctx.closePath()
        ctx.fill()

        // A band of valley fog sits in front of every ridge but the nearest.
        if (L.depth < 0.95) {
          const fy = h * (L.base - L.amp * 0.35)
          const fogA = 0.1 + (1 - L.depth) * 0.16 + u * 0.1
          const fg = ctx.createLinearGradient(0, fy - h * 0.06, 0, fy + h * 0.1)
          fg.addColorStop(0, css(horizon, 0))
          fg.addColorStop(0.5, css(mix(horizon, [255, 255, 255], 0.3), fogA))
          fg.addColorStop(1, css(horizon, 0))
          ctx.fillStyle = fg
          ctx.fillRect(0, fy - h * 0.06, w, h * 0.16)
        }
      }

      // vignette, to seat the type
      const v = ctx.createRadialGradient(w / 2, h * 0.42, h * 0.2, w / 2, h * 0.5, h * 0.95)
      v.addColorStop(0, 'rgba(0,0,0,0)')
      v.addColorStop(1, 'rgba(0,0,0,0.42)')
      ctx.fillStyle = v
      ctx.fillRect(0, 0, w, h)

      if (!still) raf = requestAnimationFrame(draw)
    }

    resize()
    draw(0)
    const ro = new ResizeObserver(() => {
      resize()
      if (still) draw(0)
    })
    ro.observe(canvas)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [])

  return (
    <div className="sky">
      <canvas ref={ref} className="sky-canvas" aria-hidden="true" />
      {mediaSrc && (
        <video
          className="sky-video"
          src={mediaSrc}
          autoPlay
          muted
          loop
          playsInline
          aria-hidden="true"
        />
      )}
    </div>
  )
}
