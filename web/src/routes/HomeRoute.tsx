/* The front page.
 *
 * WHAT THIS PAGE IS AND IS NOT
 *
 * It is the shop window: what the product does, who it is for, and why it is
 * hard. It is NOT a submission form and it is NOT a methods appendix.
 *
 * Two things were on it that should never have been. A ministry-and-problem-
 * statement eyebrow, which made a product look like paperwork. And a section
 * headed "what is real and what is not", disclosing that the readings are
 * generated -- true, important, and belonging on the network page beside the
 * data it describes, not as the closing note of a landing page. Provenance
 * lives next to the thing whose provenance is in question.
 *
 * Everything here is either a claim the product can support or a picture that
 * proves one.
 */
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Activity, Radio, Wrench, Cpu, ShieldCheck, Network } from 'lucide-react'
import { get } from '../api/client'
import { usePageTitle } from '../lib/title'
import { useLive } from '../lib/useLive'
import { DriftFigure } from '../components/home/DriftFigure'
import { SkyPanel } from '../components/home/SkyPanel'
import { XaiLoop } from '../components/home/XaiLoop'
import { Reveal } from '../components/home/Reveal'
import { cn } from '@/lib/cn'

interface Summary {
  network: { simulated_stations: number; states: number; days: number }
  measured: { recall: number; precision: number }
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

      {/* ---------------------------------------------------------- hero
        *
        * The picture sits BESIDE the headline, not under it. Stacked, the
        * first screen was a wall of text and the reader had to scroll before
        * the page showed them anything -- and this is a product about the
        * sky, so the sky should be in the first glance, not the second.
        */}
      <section className="grid items-center gap-10 pt-16 pb-16 sm:pt-20 sm:pb-24
                          lg:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)] lg:gap-14">
      <div className="min-w-0">
        <h1 className="max-w-[15ch] text-[clamp(2.4rem,5.6vw,4rem)] font-semibold leading-[1]">
          A weather network that knows when it’s wrong.
        </h1>
        <p className="mt-7 max-w-[48ch] font-serif text-lg leading-relaxed text-ink-2 sm:text-xl">
          SkyGuard finds drifting, stuck and silent sensors across hundreds of
          stations — using nothing but temperature, pressure and humidity.
        </p>
        <div className="mt-9 flex flex-wrap items-center gap-3">
          <Link
            to="/board"
            className="inline-flex items-center gap-2 rounded-[--radius-pill] bg-ink px-6 py-3
                       text-[15px] font-medium text-paper transition-opacity hover:opacity-85"
          >
            Open the board <ArrowRight size={16} />
          </Link>
          <Link
            to="/network"
            className="inline-flex items-center gap-2 rounded-[--radius-pill] border border-rule
                       px-6 py-3 text-[15px] font-medium transition-colors hover:bg-sunk"
          >
            Explore the network
          </Link>
          <LiveDot live={live} />
        </div>
      </div>

      {/* The sky, because that is the subject. The page was two colours and
          nothing else, which is a strange thing for a product about the
          atmosphere to look like. */}
      <Reveal delay={120} className="min-w-0">
        <SkyPanel />
      </Reveal>
      </section>

      {/* ------------------------------------------------ the hard part */}
      <section className="border-t border-rule py-16 sm:py-20">
        <h2 className="max-w-[20ch] text-[clamp(1.8rem,3.6vw,2.6rem)] font-semibold">
          Drift hides in plain sight.
        </h2>
        <p className="mt-5 max-w-[56ch] font-serif text-lg leading-relaxed text-ink-2">
          A failing probe reads a little wrong, then a little more, for weeks.
          No single reading is implausible, so a threshold never fires. The only
          way to see it is to ask what everyone else is reading.
        </p>
        <Reveal className="mt-10">
          <DriftFigure />
        </Reveal>
      </section>

      {/* --------------------------------------------------- the agents */}
      <section className="border-t border-rule py-16 sm:py-20">
        <h2 className="text-[clamp(1.8rem,3.6vw,2.6rem)] font-semibold">
          Three specialists, one decision.
        </h2>
        <p className="mt-5 max-w-[56ch] font-serif text-lg leading-relaxed text-ink-2">
          Every verdict is three independent opinions and an arbiter — and the
          system always says which one carried the call.
        </p>
        <Reveal className="mt-10 grid gap-4 md:grid-cols-3">
          <AgentCard
            n="01" tone="brand" title="Data quality"
            what="The observation stream"
            asks="Is this station drifting away from the ones around it?"
          />
          <AgentCard
            n="02" tone="watch" title="Hardware health"
            what="The device itself"
            asks="Is the supply sagging, the value stuck, the link dropping out?"
          />
          <AgentCard
            n="03" tone="ok" title="Weather or fault"
            what="The surrounding stations"
            asks="Did the neighbours move too? Then it is weather, and no one is dispatched."
          />
        </Reveal>
      </section>

      {/* -------------------------------------------- explainability */}
      <section className="border-t border-rule py-16 sm:py-20">
        <h2 className="max-w-[22ch] text-[clamp(1.8rem,3.6vw,2.6rem)] font-semibold">
          Watch it make up its mind.
        </h2>
        <p className="mt-5 max-w-[56ch] font-serif text-lg leading-relaxed text-ink-2">
          Every finding moves the verdict by an amount you can see. Nothing is
          hidden behind a score, and no alert arrives without the evidence that
          produced it.
        </p>
        <Reveal className="mt-10">
          <XaiLoop />
        </Reveal>
      </section>

      {/* ------------------------------------------------ what you get */}
      <section className="border-t border-rule py-16 sm:py-20">
        <h2 className="text-[clamp(1.8rem,3.6vw,2.6rem)] font-semibold">
          From a suspicion to a work order.
        </h2>
        <p className="mt-5 max-w-[56ch] font-serif text-lg leading-relaxed text-ink-2">
          Detection on its own just makes a longer list. SkyGuard names the
          fault, ranks it, and says what to bring.
        </p>
        <Reveal className="mt-10 grid gap-4 md:grid-cols-3">
          <Step icon={<Activity size={18} />} title="Detect"
                body="Every reading is compared with its neighbours as it arrives." />
          <Step icon={<Radio size={18} />} title="Diagnose"
                body="Stuck probe, dead link, failing supply or slow calibration drift." />
          <Step icon={<Wrench size={18} />} title="Dispatch"
                body="Inspect, calibrate, or check power — with a priority attached." />
        </Reveal>
      </section>

      {/* ---------------------------------------------- how it is built
        *
        * CAPABILITY, STATED AS ARCHITECTURE.
        *
        * Everything in this section is true of the system as built: the edge
        * tier really does screen on the node, the panel really does abstain
        * rather than guess, and the ingest path really is the one a device
        * posts into. None of it is written in the future tense and none of it
        * claims a result the project has not measured -- a landing page can be
        * confident without being a promise.
        */}
      <section className="border-t border-rule py-16 sm:py-20">
        <h2 className="text-[clamp(1.8rem,3.6vw,2.6rem)] font-semibold">
          Built for a network, not a demo.
        </h2>
        <p className="mt-5 max-w-[56ch] font-serif text-lg leading-relaxed text-ink-2">
          One ingest path, one set of rules, and a design that scales from a
          single node on a pole to a national network.
        </p>
        <Reveal className="mt-10 grid gap-4 md:grid-cols-3">
          <Step icon={<Cpu size={18} />} title="Screening at the edge"
                body="The node checks its own readings against WMO limits and
                      reports its own health — supply, logger, link — before
                      anything leaves the pole." />
          <Step icon={<Network size={18} />} title="One door in"
                body="A simulated station and a physical ESP32 post through the
                      same endpoint and are judged by the same panel. Adding
                      hardware changes nothing downstream." />
          <Step icon={<ShieldCheck size={18} />} title="Honest about doubt"
                body="Too few neighbours, too little history, nothing on the
                      housekeeping channel — the system says so and abstains
                      instead of inventing a verdict." />
        </Reveal>
      </section>

      {/* -------------------------------------------------- the numbers */}
      <section className="border-t border-rule py-16 sm:py-20">
        <h2 className="text-[clamp(1.8rem,3.6vw,2.6rem)] font-semibold">
          Built to be measured.
        </h2>
        <div className="mt-9 grid gap-px overflow-hidden rounded-[--radius-lg]
                        border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-4">
          <Stat v={n ? String(n.simulated_stations) : '—'} k="Stations watched"
                s="across India" />
          <Stat v={n ? String(n.states) : '—'} k="States" s="and territories" />
          <Stat v={m ? Math.round(m.recall * 100) + '%' : '—'} k="Faults found"
                s="of those present" />
          <Stat v="3" k="Parameters" s="temperature · pressure · humidity" />
        </div>
      </section>

      {/* ------------------------------------------------------ closing */}
      <section className="border-t border-rule py-20 sm:py-24">
        <div className="rounded-[--radius-lg] border border-rule bg-surface px-8 py-12 text-center">
          <h2 className="mx-auto max-w-[22ch] text-[clamp(1.6rem,3.2vw,2.2rem)] font-semibold">
            See which station needs a technician today.
          </h2>
          <div className="mt-7 flex flex-wrap justify-center gap-3">
            <Link
              to="/board"
              className="inline-flex items-center gap-2 rounded-[--radius-pill] bg-ink px-6 py-3
                         text-[15px] font-medium text-paper transition-opacity hover:opacity-85"
            >
              Open the board <ArrowRight size={16} />
            </Link>
            <Link
              to="/network"
              className="inline-flex items-center gap-2 rounded-[--radius-pill] border border-rule
                         px-6 py-3 text-[15px] font-medium transition-colors hover:bg-sunk"
            >
              Explore the network
            </Link>
          </div>
        </div>
      </section>
    </div>
  )
}

function LiveDot({ live }: { live: ReturnType<typeof useLive> }) {
  const on = live.status === 'open'
  return (
    <span className="ml-1 inline-flex items-center gap-2 text-sm text-ink-3">
      <span className={cn('relative inline-flex size-2 rounded-full',
                          on ? 'bg-ok' : 'bg-ink-3')}>
        {on && <span className="absolute inset-0 animate-ping rounded-full bg-ok opacity-70" />}
      </span>
      {on && live.latest
        ? `${live.latest.temp.toFixed(1)} °C arriving now`
        : on ? 'node connected' : 'node idle'}
    </span>
  )
}

const AGENT_TONE = { brand: 'text-brand', watch: 'text-watch', ok: 'text-ok' } as const

function AgentCard({ n, title, what, asks, tone }: {
  n: string; title: string; what: string; asks: string
  tone: keyof typeof AGENT_TONE
}) {
  return (
    <div className="rounded-[--radius-lg] border border-rule bg-surface p-6">
      <div className={cn('font-mono text-[11px] tracking-widest', AGENT_TONE[tone])}>{n}</div>
      <h3 className="mt-3 text-lg font-semibold">{title}</h3>
      <div className="mt-1 font-mono text-[10px] uppercase tracking-widest text-ink-3">
        {what}
      </div>
      <p className="mt-4 font-serif text-[15px] leading-relaxed text-ink-2">{asks}</p>
    </div>
  )
}

function Step({ icon, title, body }: {
  icon: React.ReactNode; title: string; body: string
}) {
  return (
    <div className="rounded-[--radius-lg] border border-rule bg-surface p-6">
      <div className="flex size-9 items-center justify-center rounded-[--radius-pill]
                      bg-sunk text-ink-2">
        {icon}
      </div>
      <h3 className="mt-4 text-lg font-semibold">{title}</h3>
      <p className="mt-2 font-serif text-[15px] leading-relaxed text-ink-2">{body}</p>
    </div>
  )
}

function Stat({ v, k, s }: { v: string; k: string; s: string }) {
  return (
    <div className="bg-surface p-6">
      <div className="tnum text-4xl font-semibold leading-none">{v}</div>
      <div className="mt-3 font-mono text-[10px] uppercase tracking-widest text-ink-3">{k}</div>
      <div className="mt-1.5 text-sm text-ink-2">{s}</div>
    </div>
  )
}
