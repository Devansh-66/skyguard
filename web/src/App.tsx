/* Layout and routing.
 *
 * A single top bar, no sidebar. The scroll-dependent transparency the bar used
 * to carry is gone with the dark hero it existed for: the page is chart paper
 * from edge to edge now, so the bar is simply a ruled header that sits on it.
 * A state that no longer changes anything is a state worth deleting.
 *
 * The map is the older static console at /console/console.html, linked out to
 * rather than ported. Note the consequence: that page is outside this shell, so
 * the top bar is not on it and the way back is the browser's back button.
 */
import { Link, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { BoardRoute } from './routes/BoardRoute'
import { HomeRoute } from './routes/HomeRoute'


export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="mark">
          <Glyph />
          <span>SkyGuard</span>
        </Link>
        <nav className="links">
          <NavLink to="/board">Maintenance</NavLink>
          <a href="/console/console.html">Network map</a>
        </nav>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<HomeRoute />} />
          <Route path="/board" element={<BoardRoute />} />
          <Route path="/board/*" element={<BoardRoute />} />
          {/* The board used to live at /queue. Anyone holding an old link is
              sent on rather than shown a dead end. */}
          <Route path="/queue" element={<Navigate to="/board" replace />} />
          <Route path="/queue/*" element={<Navigate to="/board" replace />} />
          <Route path="*" element={<p className="notfound">No such page.</p>} />
        </Routes>
      </main>
    </div>
  )
}

/** The station plot.
 *
 * This is the symbol a meteorologist already reads: the WMO station model that
 * has been drawn on synoptic charts since the 1930s. The circle is the station
 * and its fill is sky cover; the shaft is wind direction and each feather is a
 * speed increment. It is the one mark in this field that means something before
 * anyone is told what it means, and no software uses it.
 *
 * Monochrome on purpose. Oxide red is reserved for "this instrument has left
 * tolerance", and spending it on a logo would blunt the one place it has to
 * carry weight. Everything here inherits currentColor, so the mark works on the
 * bar, inverted on a dark button, or at 16px in a tab.
 */
function Glyph() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true" className="glyph">
      {/* sky cover: the half fill that gives the mark weight at small sizes */}
      <path d="M13 10.2a6.8 6.8 0 0 0 0 13.6z" className="glyph-cover" />
      <circle cx="13" cy="17" r="6.8" className="glyph-ring" />
      <path d="M17.9 12.2 L27 3.2" className="glyph-shaft" />
      <path d="M27 3.2 L23.6 1.9 M24.2 6 L20.8 4.7" className="glyph-barb" />
    </svg>
  )
}
