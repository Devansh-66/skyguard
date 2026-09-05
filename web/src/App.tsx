/* Layout and routing.
 *
 * A single top bar, no sidebar. The scroll-dependent transparency the bar used
 * to carry is gone with the dark hero it existed for: the page is chart paper
 * from edge to edge now, so the bar is simply a ruled header that sits on it.
 * A state that no longer changes anything is a state worth deleting.
 *
 * The map used to be a separate static console linked out to from here. It is
 * ported now and /network is a route like any other, so the top bar is on it
 * and there is one frontend rather than two drifting apart.
 */
import { Link, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { ThemeToggle } from './components/ThemeToggle'
import { Suspense, lazy } from 'react'
import { BoardRoute } from './routes/BoardRoute'
import { HomeRoute } from './routes/HomeRoute'

/* Leaflet is ~160 kB and only this route needs it. Code-split so opening the
 * maintenance board does not wait for a mapping library it will not use. */
const NetworkRoute = lazy(() =>
  import('./routes/NetworkRoute').then((m) => ({ default: m.NetworkRoute })))


export default function App() {
  return (
    <div className="min-h-screen bg-paper text-ink">
      <header className="sticky top-0 z-50 border-b border-rule bg-paper/85 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-8 px-5">
          <Link to="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
            <Glyph />
            <span className="text-[15px]">SkyGuard</span>
            <span className="hidden font-mono text-[10px] font-medium uppercase
                             tracking-widest text-ink-3 sm:inline">PS26073</span>
          </Link>
          <nav className="flex items-center gap-1">
            <Tab to="/board">Maintenance</Tab>
            <Tab to="/network">Network</Tab>
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<HomeRoute />} />
          <Route path="/board" element={<BoardRoute />} />
          <Route path="/board/*" element={<BoardRoute />} />
          <Route path="/network" element={
            <Suspense fallback={<p className="p-10 text-ink-3">Loading the map…</p>}>
              <NetworkRoute />
            </Suspense>} />
          {/* The board used to live at /queue. Anyone holding an old link is
              sent on rather than shown a dead end. */}
          <Route path="/queue" element={<Navigate to="/board" replace />} />
          <Route path="/queue/*" element={<Navigate to="/board" replace />} />
          <Route path="*" element={<p className="p-10 text-ink-2">No such page.</p>} />
        </Routes>
      </main>
    </div>
  )
}


/* The active tab is marked with a rule under it AND a weight change. Colour
 * alone fails for the ~8% of men with a colour vision deficiency, and it also
 * fails on a washed-out projector, which is the same problem twice. */
function Tab({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        'relative px-3 py-2 text-sm transition-colors ' +
        (isActive
          ? 'font-semibold text-ink after:absolute after:inset-x-3 after:-bottom-px '
            + 'after:h-0.5 after:bg-brand'
          : 'text-ink-2 hover:text-ink')
      }
    >
      {children}
    </NavLink>
  )
}

/** Three readings, one adrift.
 *
 * The previous mark was the WMO station plot -- a circle with a long shaft and
 * two perpendicular feathers -- and it read as a KEY: circular bow, straight
 * stem, teeth. Correct meteorologically, wrong as a logo, and unfixable without
 * losing the thing that made it a station plot.
 *
 * This says what the product does instead of what the domain looks like. Three
 * bars are the three channels: temperature, pressure, humidity. Two hold their
 * line and one has slipped out of it, and that one is red. Drift is only
 * visible against something that has not drifted, which is the whole argument
 * of the project, stated in three rectangles.
 *
 * Two colours, both from the agreed set. No curves, so nothing to resemble a
 * bow or a barb, and it stays square at 16px where circles turn to mush.
 */
function Glyph() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
      <rect fill="currentColor" x="2" y="4.6" width="15" height="3.2" rx="1" />
      <rect fill="var(--color-fault)" x="6.8" y="10.4" width="15" height="3.2" rx="1" />
      <rect fill="currentColor" x="2" y="16.2" width="15" height="3.2" rx="1" />
    </svg>
  )
}
