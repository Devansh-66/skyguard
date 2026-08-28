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

/** A pen trace crossing a ruled sheet: the product in four strokes. */
function Glyph() {
  return (
    <svg width="24" height="18" viewBox="0 0 24 18" aria-hidden="true" className="glyph">
      <path d="M0 4.5H24M0 13.5H24" className="glyph-rule" />
      <path d="M1 11 L6 6 L10 12 L14 4 L18 9 L23 6" className="glyph-pen" />
    </svg>
  )
}
