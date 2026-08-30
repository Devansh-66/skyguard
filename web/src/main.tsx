/* Entry point.
 *
 * `basename` comes from Vite's own `base`, which is the only way the two can
 * be guaranteed to agree. They were set separately -- base from an env var,
 * basename hardcoded to "/app" -- and a static build served from the root
 * loaded its bundle correctly and then rendered nothing at all, because the
 * router was still waiting for a /app prefix that was never coming. One
 * source, or they drift the moment either moves.
 *
 * Historically /app in both dev and production: Vite's `base` option makes the
 * dev server serve under /app/ too, so the router never needs to know which
 * mode it is in. Retries are off because every endpoint here is a deterministic
 * read of an archive -- if it failed once it will fail three times, and the
 * only thing retrying adds is a slower error message.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import 'leaflet/dist/leaflet.css'
import App from './App'
import './styles/tokens.css'
import './styles/app.css'

const client = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter basename={import.meta.env.BASE_URL}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
