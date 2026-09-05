import { useState } from 'react'
import { Link2 } from 'lucide-react'
import { usePageTitle } from '../lib/title'
import { Reveal } from '../components/home/Reveal'
import { cn } from '@/lib/cn'

/* WHO BUILT IT, AND WHAT THEY WERE ASKED TO BUILD.
 *
 * This page exists so the front page does not have to carry it. The landing
 * page is the product argument; a ministry eyebrow and a row of student
 * photographs under a headline about atmospheric drift undoes that argument
 * in one glance. A judge who wants the submission context comes here
 * deliberately, and here it is complete rather than trimmed.
 *
 * The problem statement below is reproduced VERBATIM. Not paraphrased, not
 * "in our words", not shortened to the bits we do well. The single most
 * useful thing this page can do for a reader is let them hold the brief and
 * the build side by side and check them off against each other themselves --
 * and that only works if the brief is the brief.
 *
 * PHOTOGRAPHS ARE OPTIONAL BY CONSTRUCTION.
 *
 * Each card points at /team/<id>.jpg and falls back to an initial tile if the
 * file is not there. So the page is correct today with an empty folder, and
 * correct again the moment six files are dropped into web/public/team --
 * no code change, no build step, nothing to remember. The same is true of the
 * links: a placeholder renders as a dead grey chip rather than a live anchor
 * to nowhere, because a link that goes to "#" is worse than no link.
 */

interface Member {
  id: string
  name: string
  role: string
  /** What they own, in one sentence. */
  line: string
  github?: string
  linkedin?: string
}

/* Roles are a first split, not a final one -- swap them freely, the layout
 * does not care. Each maps to a part of this repository that actually
 * exists, so nobody is credited with a component nobody wrote. */
const TEAM: Member[] = [
  {
    id: 'devansh', name: 'Devansh',
    role: 'Detection engine & orchestrator',
    line: 'The neighbour differencing, the sigma bands, and the three-agent panel that turns a residual into a decision.',
  },
  {
    id: 'samarth', name: 'Samarth',
    role: 'Edge node & firmware',
    line: 'The ESP32 station: sensors, self-test, housekeeping channels, and the TLS uplink that carries them.',
  },
  {
    id: 'shaurya', name: 'Shaurya',
    role: 'Backend & data store',
    line: 'The API, the ingest path, the migrations, and the live replay clock the whole network runs on.',
  },
  {
    id: 'simran', name: 'Simran',
    role: 'Frontend & visualisation',
    line: 'The map, the charts and the interface, everything between a stored reading and a person understanding it.',
  },
  {
    id: 'ujjwal', name: 'Ujjwal',
    role: 'Data simulation & evaluation',
    line: 'The synthetic network, the injected faults, and the measurement that says how often we are actually right.',
  },
  {
    id: 'sneh', name: 'Sneh',
    role: 'Explainability & maintenance board',
    line: 'The worked arithmetic behind every verdict, and the queue a maintainer reads it from.',
  },
]

export function TeamRoute() {
  usePageTitle('Team')

  return (
    <div className="mx-auto max-w-[1100px] px-5">

      <section className="border-b border-rule pt-16 pb-14 sm:pt-20">
        <p className="font-mono text-[11px] uppercase tracking-widest text-ink-3">
          Smart India Hackathon 2026
        </p>
        <h1 className="mt-4 max-w-[18ch] text-[clamp(2.2rem,5vw,3.4rem)] font-semibold leading-[1.02]">
          Six people and one stubborn question.
        </h1>
        <p className="mt-6 max-w-[58ch] font-serif text-lg leading-relaxed text-ink-2">
          Can a weather station tell you that it is the one that is wrong? Everything
          on this site is our answer to problem statement 26073, reproduced in full
          below so you can check the build against the brief yourself.
        </p>
      </section>

      {/* ------------------------------------------------------------ people */}
      <section className="border-b border-rule py-16 sm:py-20">
        <h2 className="text-[clamp(1.6rem,3.2vw,2.2rem)] font-semibold">The team</h2>
        <p className="mt-4 max-w-[56ch] font-serif text-lg leading-relaxed text-ink-2">
          Split by the part of the system each of us is responsible for, which is also
          how the repository is split.
        </p>

        <Reveal className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {TEAM.map((m) => <Card key={m.id} m={m} />)}
        </Reveal>
      </section>

      {/* --------------------------------------------------- problem statement */}
      <section className="py-16 sm:py-20">
        <h2 className="text-[clamp(1.6rem,3.2vw,2.2rem)] font-semibold">
          The problem statement
        </h2>
        <p className="mt-4 max-w-[56ch] font-serif text-lg leading-relaxed text-ink-2">
          Reproduced exactly as issued. Nothing in the panel below is our wording.
        </p>

        <dl className="mt-8 grid gap-px overflow-hidden rounded-[--radius-lg]
                       border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-5">
          <Meta k="ID" v="26073" />
          <Meta k="Organisation" v="Ministry of Earth Sciences (MoES)" />
          <Meta k="Department" v="India Meteorological Department" />
          <Meta k="Category" v="Software" />
          <Meta k="Theme" v="Disaster Management" />
        </dl>

        <div className="mt-6 overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
          <div className="divide-y divide-rule">
            <Block h="Problem Statement Title">
              <P>AI/ML-Based Intelligent Anomaly Detection for Automatic Weather Stations (AWS)</P>
            </Block>

            <Block h="Title">
              <P>SkyGuard AI: Intelligent Real-Time Anomaly Detection System for Temperature,
                Pressure, and Humidity Sensors in Automatic Weather Stations</P>
            </Block>

            <Block h="Background">
              <P>Automatic Weather Stations (AWS) are critical components of modern
                meteorological observation networks. These stations continuously monitor
                atmospheric parameters and provide real-time data for weather forecasting,
                climate monitoring, disaster management, aviation, agriculture, and scientific
                research. However, AWS observations often contain anomalies caused by sensor
                malfunction, communication failures, calibration drift, power fluctuations,
                harsh environmental conditions, and data corruption. Erroneous observations can
                significantly impact weather forecasting accuracy and decision-making systems.
                Traditional threshold-based quality control methods are often insufficient for
                identifying complex or hidden anomalies in meteorological data streams.</P>
            </Block>

            <Block h="Problem Statement">
              <P>Develop an AI/ML-based intelligent anomaly detection system capable of
                automatically identifying abnormal, inconsistent, or faulty observations from
                Automatic Weather Stations in real time using only the following parameters:</P>
              <L items={['Temperature (°C)', 'Atmospheric Pressure (hPa)', 'Relative Humidity (%)']} />
              <P>The system should distinguish between genuine meteorological events and
                sensor/data anomalies while minimizing false alarms and enabling scalable
                deployment across large weather observation networks.</P>
            </Block>

            <Block h="Objectives">
              <L items={[
                'Detect anomalies in real-time AWS data streams.',
                'Identify sensor faults, spikes, frozen values, and communication errors.',
                'Learn normal temporal and seasonal patterns of temperature, pressure, and humidity.',
                'Perform multivariate consistency analysis among atmospheric parameters.',
                'Provide confidence scores and explainable AI-based reasoning for detected anomalies.',
                'Predict possible sensor degradation and maintenance requirements.',
                'Optionally suggest corrected/imputed values for anomalous observations.',
              ]} />
            </Block>

            <Block h="Expected Inputs">
              <P>Participants may use historical AWS datasets, simulated anomalies, or streaming
                sensor data containing the following meteorological parameters:</P>
              <L items={['Temperature — °C', 'Atmospheric Pressure — hPa', 'Relative Humidity — %']} />
            </Block>

            <Block h="Expected Outputs">
              <L items={[
                'Real-time anomaly alerts',
                'Severity and confidence scores',
                'Root-cause classification',
                'Visualization dashboard',
                'Sensor health status',
                'Corrected data estimation (optional)',
              ]} />
            </Block>

            <Block h="Suggested Technologies">
              <L items={[
                'Explainable AI (SHAP/LIME) (Preferable)',
                'Edge AI for low-power deployment on ESP32',
              ]} />
            </Block>

            <Block h="Evaluation Criteria" note="(To be evaluated in anomaly injected data)">
              <ul className="mt-3 grid gap-px overflow-hidden rounded-[--radius] border border-rule bg-rule sm:grid-cols-2">
                {CRITERIA.map(([k, v]) => (
                  <li key={k} className="flex items-baseline justify-between gap-3 bg-surface px-4 py-2.5">
                    <span className="text-sm text-ink-2">{k}</span>
                    <span className="tnum font-mono text-sm font-semibold text-ink">{v}</span>
                  </li>
                ))}
              </ul>
            </Block>

            <Block h="Example Use Case">
              <P>An AWS suddenly reports a temperature of 55°C with extremely high humidity and
                abnormal pressure variation while neighboring stations show normal conditions.
                The AI system should analyze temporal and spatial consistency, identify the
                reading as a probable sensor anomaly, generate an alert, and suggest corrective
                action.</P>
            </Block>

            <Block h="Grand Challenge">
              <P className="font-serif text-lg italic leading-relaxed text-ink">
                Can AI build a self-aware and self-healing weather observation network capable of
                delivering trustworthy atmospheric data under all environmental conditions?
              </P>
            </Block>

            <Block h="Output">
              <P className="font-medium text-ink">
                Fully executable code with example usage and a document explaining various use cases.
              </P>
            </Block>
          </div>
        </div>
      </section>
    </div>
  )
}

const CRITERIA: [string, string][] = [
  ['Innovation & Novelty', '25%'], ['Detection Accuracy', '20%'],
  ['Real-Time Capability', '15%'], ['Explainability', '10%'],
  ['Scalability', '10%'], ['Practical Deployability', '10%'],
  ['Visualization/UI', '5%'], ['Energy Efficiency', '5%'],
]

/* ------------------------------------------------------------------ pieces */

function Card({ m }: { m: Member }) {
  /* The photograph is attempted, not assumed. onError is the only reliable
     signal that a static file is missing -- there is no way to ask first
     without a second request -- so the initial tile is what the card starts
     as, and the photograph replaces it only once it has actually loaded. */
  const [loaded, setLoaded] = useState(false)
  const [failed, setFailed] = useState(false)

  return (
    <article className="flex flex-col overflow-hidden rounded-[--radius-lg] border border-rule bg-surface">
      <div className="relative aspect-[4/3] bg-sunk">
        {!failed && (
          <img
            /* BASE_URL, not a leading slash: the app is served under /app/,
               so an absolute "/team/x.jpg" would 404 in every deployment and
               only work on a dev server rooted at "/". */
            src={`${import.meta.env.BASE_URL}team/${m.id}.jpg`}
            alt={m.name}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
            className={cn('absolute inset-0 size-full object-cover transition-opacity duration-300',
              loaded ? 'opacity-100' : 'opacity-0')}
          />
        )}
        {!loaded && (
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="font-mono text-4xl font-semibold text-ink-3/60">
              {m.name[0]}
            </span>
            <span className="absolute bottom-2 font-mono text-[9.5px] uppercase tracking-widest text-ink-3/70">
              photo to come
            </span>
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col p-5">
        <h3 className="text-[17px] font-semibold leading-tight">{m.name}</h3>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-brand">
          {m.role}
        </p>
        <p className="mt-3 flex-1 text-sm leading-relaxed text-ink-2">{m.line}</p>

        <div className="mt-4 flex items-center gap-2">
          <Chip icon={<Link2 className="size-3.5" />} href={m.github} label="GitHub" />
          <Chip icon={<Link2 className="size-3.5" />} href={m.linkedin} label="LinkedIn" />
        </div>
      </div>
    </article>
  )
}

/** A live anchor if there is somewhere to go, a dead grey chip if not. */
function Chip({ icon, href, label }: {
  icon: React.ReactNode; href?: string; label: string
}) {
  const base = 'inline-flex items-center gap-1.5 rounded-[--radius] border px-2.5 py-1 '
             + 'font-mono text-[10px] uppercase tracking-widest'
  if (!href) {
    return (
      <span className={cn(base, 'cursor-default border-rule bg-sunk text-ink-3/70')}
            title={`${label} link not added yet`}>
        {icon}{label}
      </span>
    )
  }
  return (
    <a href={href} target="_blank" rel="noreferrer noopener"
       className={cn(base, 'border-rule text-ink-2 transition-colors hover:border-ink hover:text-ink')}>
      {icon}{label}
    </a>
  )
}

function Meta({ k, v }: { k: string; v: string }) {
  return (
    <div className="bg-surface px-4 py-3">
      <dt className="font-mono text-[10px] uppercase tracking-widest text-ink-3">{k}</dt>
      <dd className="mt-1 text-sm text-ink">{v}</dd>
    </div>
  )
}

function Block({ h, note, children }: {
  h: string; note?: string; children: React.ReactNode
}) {
  return (
    <div className="px-5 py-5 sm:px-6">
      <h3 className="font-mono text-[10px] uppercase tracking-widest text-ink-3">
        {h}{note && <em className="ml-2 normal-case tracking-normal opacity-80">{note}</em>}
      </h3>
      {children}
    </div>
  )
}

function P({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <p className={cn('mt-2 max-w-[72ch] text-sm leading-relaxed text-ink-2', className)}>
      {children}
    </p>
  )
}

function L({ items }: { items: string[] }) {
  return (
    <ul className="mt-2 max-w-[72ch] space-y-1.5">
      {items.map((s) => (
        <li key={s} className="flex gap-2.5 text-sm leading-relaxed text-ink-2">
          <span className="mt-[0.55em] size-1 shrink-0 rounded-full bg-ink-3" />
          {s}
        </li>
      ))}
    </ul>
  )
}
