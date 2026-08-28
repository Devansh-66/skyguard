/* Layout and routing.
 *
 * The sidebar is gone. Navigation is a single top bar, which is what lets the
 * landing page run the sky full-bleed to all four edges -- a fixed left rail
 * would have cut a slab out of the horizon on every page to hold three links.
 *
 * The bar is transparent over the hero and turns solid once the page scrolls,
 * so the type stays readable against a sky that changes colour through the day.
 *
 * Only routes that actually exist appear here. The map console is a link OUT to
 * the older static page rather than a stub route, because a nav item leading to
 * "coming soon" is worse than one leading somewhere real -- and the map is real,
 * it just has not been ported yet.
 */
import { useEffect, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { BoardRoute } from './routes/BoardRoute'
import { HomeRoute } from './routes/HomeRoute'

export default function App() {
  const { pathname } = useLocation()
  const onHome = pathname === '/'
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // The board manages its own scrolling in two independent panes, so the page
  // itself must not also scroll or the two fight each other.
  const solid = !onHome || scrolled

  return (
    <div className={'app' + (onHome ? ' on-home' : '')}>
      <header className={'topbar' + (solid ? ' solid' : '')}>
        <Link to="/" className="mark">
          <Glyph />
          <span>SkyGuard</span>
        </Link>
        <nav className="links">
          <NavLink to="/board">Maintenance</NavLink>
          <a href="/console/console.html">Network map</a>
          <a href="/docs" onClick={(e) => e.preventDefault()} className="disabled" aria-disabled="true">
            Method
          </a>
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

/** A ridgeline under a horizon: the product in eleven strokes. */
function Glyph() {
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
      <circle cx="11" cy="11" r="10" className="glyph-ring" />
      <path d="M3 15 L8 8 L11 12 L14 6 L19 15 Z" className="glyph-peak" />
    </svg>
  )
}
