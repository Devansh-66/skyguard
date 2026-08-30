/* Entry point.
 *
 * `basename` is /app in both dev and production: Vite's `base` option makes the
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
      <BrowserRouter basename="/app">
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
