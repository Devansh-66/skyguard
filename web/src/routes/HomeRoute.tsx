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
import { ScrollStory } from '@/components/home/ScrollStory'
import { DotField } from '@/components/home/DotField'
import { XaiLoop } from '../components/home/XaiLoop'
import { Reveal } from '../components/home/Reveal'
import { EdgeTiers } from '../components/home/EdgeTiers'
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
    <>
      {/* The page's one picture, behind everything and driven by the scroll.
          See DotField: it is the network, then thirty days of traces, then the
          residual, then the panel, then the network again -- and it is
          decoration, so nothing on the page depends on it arriving. */}
      <DotField />

    <div className="relative z-10 mx-auto max-w-[1100px] px-5">

      {/* ---------------------------------------------------------- hero
        *
        * THE HORIZON IS THE PAGE'S FIRST ARGUMENT.
        *
        * The sky used to be a card beside the headline, which made it an
        * illustration of the text. Run full width under the type it becomes
        * the ground the page stands on -- and this is a product about the
        * atmosphere, so the atmosphere should be the first thing seen rather
        * than a thumbnail of it.
        *
        * The live reading and the measured numbers sit in the first screen on
        * purpose. A landing page that makes you scroll six times before it
        * shows you a number is asking for trust it has not offered.
        */}
      <section className="pt-14 sm:pt-20">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-3">
          Automatic weather stations · SIH 2026 · PS26073
        </p>
        {/* SERIF, AT 400, TRACKED TIGHT.
          *
          * The headline was a semibold grotesque, which is what every
          * monitoring product uses and reads as software. Set in the serif the
          * page already loads, at regular weight and -0.035em, it reads as a
          * publication instead -- and the claim is a sentence about the
          * atmosphere, not a feature name. Weight is doing none of the work
          * here; size and tracking are. */}
        <h1 className="mt-5 max-w-[17ch] font-serif text-[clamp(2.8rem,7vw,5.2rem)]
                       font-normal leading-[0.96] tracking-[-0.035em]">
          A weather network that knows when it’s wrong.
        </h1>
        <p className="mt-7 max-w-[52ch] text-lg leading-relaxed text-ink-2 sm:text-xl">
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
      </section>

      {/* THE HERO'S PICTURE IS THE FIELD BEHIND IT, NOT A PANEL INSIDE IT.
        *
        * There was a painted sky here, full width, with the numbers resting on
        * it. It was the better answer while the page had no picture of its
        * own; now the dots draw the network across the whole first screen and
        * an opaque card in the middle of them covered half the country. What
        * is left is the part that was carrying information: four numbers, on a
        * rule, which the field passes behind. */}
      <Reveal className="mt-14">
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[--radius-lg]
                        border border-rule bg-rule sm:grid-cols-4">
          <Stat v={n ? String(n.simulated_stations) : '—'} k="Stations watched" s="across India" />
          <Stat v={n ? String(n.states) : '—'} k="States" s="and territories" />
          <Stat v={m ? Math.round(m.recall * 100) + '%' : '—'} k="Faults found" s="of those present" />
          <Stat v="3" k="Parameters" s="temperature · pressure · humidity" />
        </div>
      </Reveal>

      {/* ------------------------------------------------ the hard part
        *
        * The one idea the whole project rests on, told at the reader's pace
        * rather than in a caption. The figure pins; the reasoning scrolls
        * past it. See ScrollStory for why none of that needs JavaScript to
        * stay readable. */}
      <section className="border-t border-rule py-16 sm:py-20">
        <Eyebrow>The problem</Eyebrow>
        <h2 className="mt-4 max-w-[20ch] font-serif text-[clamp(2rem,4vw,3rem)] font-normal tracking-[-0.03em]">
          Drift hides in plain sight.
        </h2>
        <p className="mt-5 max-w-[56ch] text-lg leading-relaxed text-ink-2">
          A failing probe reads a little wrong, then a little more, for weeks.
          No single reading is implausible, so a threshold never fires.
        </p>

        <ScrollStory
          className="mt-4"
          steps={[
            { label: 'the record',
              text: <>Seven stations in one region, thirty days. One of them is
                     failing the entire time. Nothing in the left-hand panel
                     says which.</> },
            { label: 'why it hides',
              text: <>Every trace rises and falls together, because weather is
                     shared. A probe sliding a twentieth of a degree a day is
                     buried inside a daily swing forty times larger.</> },
            { label: 'the subtraction',
              text: <>So stop reading the station and start reading the
                     <em> difference</em>. Subtract the median of its
                     neighbours at the same moment: the weather cancels,
                     because it happened to all of them.</> },
            { label: 'what is left',
              text: <>Six traces collapse onto zero. The seventh walks out of
                     the band — and it had been walking the whole time, in
                     plain sight, in the panel on the left.</> },
          ]}
        />
      </section>

      {/* --------------------------------------------------- the agents
        *
        * A BENTO GRID, AND ONLY HERE.
        *
        * Three agents and a worked verdict are four things of unequal weight:
        * the verdict is the point and the agents are its inputs. Equal
        * columns said the opposite. Asymmetry is worth using exactly where
        * the content is asymmetric, and nowhere else on this page.
        */}
      <section className="border-t border-rule py-16 sm:py-20">
        <Eyebrow>The decision</Eyebrow>
        <h2 className="mt-4 font-serif text-[clamp(2rem,4vw,3rem)] font-normal tracking-[-0.03em]">
          Three specialists, one decision.
        </h2>
        <p className="mt-5 max-w-[56ch] text-lg leading-relaxed text-ink-2">
          Every verdict is three independent opinions and an arbiter — and the
          system always says which one carried the call.
        </p>

        {/* The three agents are three of a kind, so they get three equal
            columns. Stacking them down one third of a bento put the verdict
            beside them as a wall of numbers with no sentence next to it --
            and the verdict is the part that needs explaining, not the part
            that needs room. */}
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

        {/* The worked verdict, beside the sentence that says what to look at
            in it. A panel of moving numbers with its caption underneath is a
            widget; with the caption beside it, it is an example. */}
        <Reveal className="mt-4 grid items-center gap-8
                           lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.3fr)] lg:gap-12">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
              The arbiter, deciding
            </div>
            <p className="mt-4 max-w-[38ch] font-serif text-lg leading-relaxed text-ink-2">
              Every finding moves the verdict by an amount you can see. Nothing
              is hidden behind a score, and no alert arrives without the
              evidence that produced it.
            </p>
          </div>
          <div className="rounded-[--radius-lg] border border-rule bg-surface p-6">
            <XaiLoop />
          </div>
        </Reveal>
      </section>

      {/* ------------------------------------------------ what you get */}
      <section className="border-t border-rule py-16 sm:py-20">
        <Eyebrow>The outcome</Eyebrow>
        <h2 className="mt-4 font-serif text-[clamp(2rem,4vw,3rem)] font-normal tracking-[-0.03em]">
          From a suspicion to a work order.
        </h2>
        <p className="mt-5 max-w-[56ch] text-lg leading-relaxed text-ink-2">
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
        <Eyebrow>The architecture</Eyebrow>
        <h2 className="mt-4 font-serif text-[clamp(2rem,4vw,3rem)] font-normal tracking-[-0.03em]">
          Built for a network, not a demo.
        </h2>
        <p className="mt-5 max-w-[56ch] text-lg leading-relaxed text-ink-2">
          One ingest path, one set of rules, and a design that scales from a
          single node on a pole to a national network.
        </p>
        {/* The claim above is architectural, so it gets a picture of the
            architecture rather than a photograph of the board. */}
        <Reveal className="mt-10">
          <EdgeTiers />
        </Reveal>

        <Reveal className="mt-4 grid gap-4 md:grid-cols-3">
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

      {/* -------------------------------------------------- the numbers
        *
        * INVERTED, BECAUSE NINE SCREENS OF CREAM IS THE REAL MONOTONY.
        *
        * One dark band does more for the page's rhythm than any amount of
        * motion, and it belongs here: the measured results are the one place
        * the page stops describing and starts reporting. The weak numbers are
        * printed beside the strong ones deliberately -- a results panel that
        * shows only what flatters is not a results panel.
        */}
      <section className="py-10 sm:py-14">
        <Reveal className="rounded-[--radius-lg] bg-ink px-8 py-14 text-paper sm:px-12">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-paper/55">
            Measured, not claimed
          </p>
          <h2 className="mt-4 max-w-[24ch] font-serif text-[clamp(2rem,4vw,3rem)] font-normal tracking-[-0.03em]">
            Every figure here came from the running service.
          </h2>
          <div className="mt-10 grid gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
            <DarkStat v={m ? Math.round(m.recall * 100) + '%' : '—'}
                      k="Faults found"
                      s="of the faults injected into the network" />
            <DarkStat v={m ? Math.round(m.precision * 100) + '%' : '—'}
                      k="Alerts genuine"
                      s="honest, and the number we are working on" />
            <DarkStat v={n ? String(n.simulated_stations) : '—'}
                      k="Stations graded"
                      s="every reading, against its neighbours" />
            <DarkStat v="6σ / 8σ"
                      k="Alert bands"
                      s="three bad steps to open, six clean to close" />
          </div>
        </Reveal>
      </section>

      {/* ------------------------------------------------------ closing */}
      <section className="border-t border-rule py-20 sm:py-24">
        <div className="rounded-[--radius-lg] border border-rule bg-surface px-8 py-12 text-center">
          <h2 className="mx-auto max-w-[22ch] font-serif text-[clamp(1.9rem,3.6vw,2.6rem)] font-normal tracking-[-0.03em]">
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
    </>
  )
}

/** A section's name, set small and wide above its heading.
 *
 *  The page had eight headings and nothing between them but a hairline, so
 *  skimming it gave no sense of where you were. An eyebrow is the cheapest
 *  structure there is: it names the section in two words and gives the eye a
 *  fixed point at the top of each one. */
function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-brand">
      {children}
    </p>
  )
}

/** A statistic on the inverted band. Separate from Stat because the numbers
 *  there are the section rather than a strip under a figure, so they are set
 *  larger and without the cell borders that would fence them in. */
function DarkStat({ v, k, s }: { v: string; k: string; s: string }) {
  return (
    <div>
      <div className="text-[clamp(2.2rem,4.6vw,3.2rem)] font-semibold leading-none tracking-[-0.02em]">
        {v}
      </div>
      <div className="mt-4 font-mono text-[10px] uppercase tracking-widest text-paper/60">
        {k}
      </div>
      <p className="mt-2 max-w-[28ch] font-serif text-[14px] leading-relaxed text-paper/75">
        {s}
      </p>
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
