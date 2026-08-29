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
    <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true" className="glyph">
      <rect className="glyph-hold" x="2" y="4.6" width="15" height="3.2" />
      <rect className="glyph-drift" x="6.8" y="10.4" width="15" height="3.2" />
      <rect className="glyph-hold" x="2" y="16.2" width="15" height="3.2" />
    </svg>
  )
}
