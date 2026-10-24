import { StrictMode, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'

// /dev/board: overlay engine playground (#11). Lazy, so it stays out of the main bundle.
const DevBoard = lazy(() => import('./dev/DevBoard.tsx'))
const page = location.pathname.startsWith('/dev/board') ? <DevBoard /> : <App />

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense>{page}</Suspense>
  </StrictMode>,
)
