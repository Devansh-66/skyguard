/* The front page.
 *
 * WHAT WAS WRONG WITH THE ONE BEFORE
 *
 * It read like a document someone had written, because it was: paragraphs of
 * reasoning, a table of caveats, three sections of prose before anything was
 * shown. That is the right shape for a report and the wrong shape for a site.
 * A visitor gives this page a few seconds and decides whether the project is
 * serious; prose cannot win that, a picture can.
 *
 * So: one claim, one figure that proves it, the three agents drawn rather than
 * described, and the measured numbers. Everything that used to be a paragraph
 * is now either a caption or deleted. The detail still exists -- it lives on
 * the board and the network map, where someone who wants it has asked for it.
 */
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { get } from '../api/client'
import { usePageTitle } from '../lib/title'
import { useLive } from '../lib/useLive'
import { DriftFigure } from '../components/home/DriftFigure'
import { cn } from '@/lib/cn'

interface Summary {
  network: {
    simulated_stations: number; states: number; injected_faults: number
    days: number; step_minutes: number
  }
  measured: {
    recall: number; precision: number
    recall_excluding_dropouts: number
    alert_episodes: number; stations_alerting: number
  }
}

function useSummary() {
  return useQuery({
    queryKey: ['summary'] as const,
    queryFn: ({ signal }) => get<Summary>('/api/summary', signal),
    staleTime: Infinity,
  })
}

export function HomeRoute() {
  usePageTitle(undefined)
  const sum = useSummary()
  const live = useLive(import.meta.env.VITE_API_BASE ?? '')
  const n = sum.data?.network
  const m = sum.data?.measured

  return (
    <div className="mx-auto max-w-[1100px] px-5">

      {/* ---------------------------------------------------------- hero */}
      <section className="pt-20 pb-16 sm:pt-28 sm:pb-20">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-3">
          Ministry of Earth Sciences · IMD · PS26073
        </p>
        <h1 className="mt-6 max-w-[18ch] text-[clamp(2.6rem,7vw,4.6rem)] font-semibold leading-[1.02]">
          A broken weather station doesn’t stop.
          <span className="block text-ink-3">It keeps reporting.</span>
        </h1>
        <p className="mt-7 max-w-[54ch] font-serif text-xl leading-relaxed text-ink-2">
          SkyGuard finds the failure anyway — from temperature, pressure and
          humidity alone — by asking every station whether it still agrees with
          its neighbours.
        </p>
        <div className="mt-9 flex flex-wrap items-center gap-3">
          <Link
            to="/board"
            className="inline-flex items-center gap-2 rounded-[--radius-pill] bg-ink px-6 py-3
                       text-[15px] font-medium text-paper transition-opacity hover:opacity-88"
          >
            Open the board <ArrowRight size={16} />
          </Link>
          <Link
            to="/network"
            className="inline-flex items-center gap-2 rounded-[--radius-pill] border border-rule
                       px-6 py-3 text-[15px] font-medium transition-colors hover:bg-sunk"
          >
            See the network
          </Link>
          <LiveDot live={live} />
        </div>
      </section>

      {/* -------------------------------------------------- the argument */}
      <section className="border-t border-rule py-16">
        <h2 className="max-w-[22ch] text-[clamp(1.7rem,3.4vw,2.4rem)] font-semibold">
          Drift is invisible until you have something to compare it to.
        </h2>
        <p className="mt-4 max-w-[58ch] font-serif text-lg leading-relaxed text-ink-2">
          A probe that fails slowly reads a little wrong, then a little more,
          for weeks. No single reading is implausible, so no threshold fires.
        </p>
        <div className="mt-10">
          <DriftFigure />
        </div>
      </section>

      {/* ----------------------------------------------------- the agents */}
      <section className="border-t border-rule py-16">
        <h2 className="text-[clamp(1.7rem,3.4vw,2.4rem)] font-semibold">
          Three specialists, one decision.
        </h2>
        <p className="mt-4 max-w-[58ch] font-serif text-lg leading-relaxed text-ink-2">
          Each agent looks at one kind of evidence and reports on its own. An
          arbiter combines them, and says which one carried the call.
        </p>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          <AgentCard
            n="01" title="Data quality" tone="brand"
            what="The observation stream"
            asks="Is the reading drifting away from its neighbours?"
          />
          <AgentCard
            n="02" title="Hardware health" tone="watch"
            what="The device itself"
            asks="Is the supply sagging, the value stuck, the link dropping?"
          />
          <AgentCard
            n="03" title="Weather or fault" tone="ok"
            what="The surrounding stations"
            asks="Did the neighbours move too? Then it is weather, not a fault."
          />
        </div>
        <p className="mt-6 max-w-[62ch] text-sm text-ink-3">
          Hardware outranks calibration — a dead link is a fault in any weather.
          A confirmed regional front can veto everything else.
        </p>
      </section>

      {/* ---------------------------------------------------- the numbers */}
      <section className="border-t border-rule py-16">
        <h2 className="text-[clamp(1.7rem,3.4vw,2.4rem)] font-semibold">
          Measured, not claimed.
        </h2>
        <div className="mt-9 grid gap-px overflow-hidden rounded-[--radius-lg]
                        border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-4">
          <Stat v={m ? pct(m.recall) : '—'} k="Recall"
                s="of injected faults found" />
          <Stat v={m ? pct(m.precision) : '—'} k="Precision"
                s="of alerting stations that had one" />
          <Stat v={n ? String(n.simulated_stations) : '—'} k="Stations"
                s="real IMD sites across India" />
          <Stat v="3" k="Parameters"
                s="temperature · pressure · humidity" />
        </div>
        <p className="mt-6 max-w-[62ch] font-serif text-[15px] leading-relaxed text-ink-2">
          Both numbers belong together. The same detector reaches 86% recall at
          15% precision if the bands are loosened — and a queue nobody trusts is
          worse than a shorter one.
        </p>
      </section>

      {/* ----------------------------------------------------- the honesty */}
      <section className="border-t border-rule py-16 pb-24">
        <h2 className="text-[clamp(1.7rem,3.4vw,2.4rem)] font-semibold">
          What is real, and what is not.
        </h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-3">
          <Honest k="Station locations" v="Real IMD sites" tone="ok" />
          <Honest k="Readings" v="Generated, and will stay generated" tone="watch" />
          <Honest k="Faults" v="Injected, so the truth is known exactly" tone="ok" />
        </div>
        <p className="mt-6 max-w-[62ch] font-serif text-[15px] leading-relaxed text-ink-2">
          What is being demonstrated is the pipeline that judges the readings —
          the same pipeline an ESP32 posts into today.
        </p>
      </section>
    </div>
  )
}

const pct = (x: number) => Math.round(x * 100) + '%'

function LiveDot({ live }: { live: ReturnType<typeof useLive> }) {
  const on = live.status === 'open'
  return (
    <span className="ml-1 inline-flex items-center gap-2 text-sm text-ink-3">
      <span className={cn('relative inline-flex size-2 rounded-full',
                          on ? 'bg-ok' : 'bg-ink-3')}>
        {on && (
          <span className="absolute inset-0 animate-ping rounded-full bg-ok opacity-70" />
        )}
      </span>
      {on && live.latest
        ? `${live.latest.temp.toFixed(1)} °C reporting now`
        : on ? 'node connected' : 'node idle'}
    </span>
  )
}

const AGENT_TONE = {
  brand: 'text-brand',
  watch: 'text-watch',
  ok: 'text-ok',
} as const

function AgentCard({ n, title, what, asks, tone }: {
  n: string; title: string; what: string; asks: string
  tone: keyof typeof AGENT_TONE
}) {
  return (
    <div className="rounded-[--radius-lg] border border-rule bg-surface p-5">
      <div className={cn('font-mono text-[11px] tracking-widest', AGENT_TONE[tone])}>{n}</div>
      <h3 className="mt-3 text-lg font-semibold">{title}</h3>
      <div className="mt-1 font-mono text-[10px] uppercase tracking-widest text-ink-3">
        {what}
      </div>
      <p className="mt-3 font-serif text-[15px] leading-relaxed text-ink-2">{asks}</p>
    </div>
  )
}

function Stat({ v, k, s }: { v: string; k: string; s: string }) {
  return (
    <div className="bg-surface p-5">
      <div className="tnum text-4xl font-semibold leading-none">{v}</div>
      <div className="mt-3 font-mono text-[10px] uppercase tracking-widest text-ink-3">{k}</div>
      <div className="mt-1.5 text-sm text-ink-2">{s}</div>
    </div>
  )
}

function Honest({ k, v, tone }: { k: string; v: string; tone: 'ok' | 'watch' }) {
  return (
    <div className="rounded-[--radius-lg] border border-rule bg-surface p-5">
      <div className="font-mono text-[10px] uppercase tracking-widest text-ink-3">{k}</div>
      <div className={cn('mt-2 text-[15px] font-medium',
                         tone === 'ok' ? 'text-ok' : 'text-watch')}>
        {v}
      </div>
    </div>
  )
}
