/**
 * The router of the interview side (spec 23 §3.1; AC-23.6).
 * Why: replaces the spec 10 scaffold page. `/` is My processes, `/process-discovery[/:id]` the
 * interview, `/report/:id` the report (a placeholder in part 1); anything else goes to `/`.
 * Rules: providers live in `main.tsx` (and in tests); this file only maps paths to pages.
 */
import { Navigate, Route, Routes } from 'react-router-dom'
import { Home } from './pages/Home'
import { ProcessDiscovery } from './pages/ProcessDiscovery'
import { DiscoveryReport } from './pages/DiscoveryReport'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/process-discovery" element={<ProcessDiscovery />} />
      <Route path="/process-discovery/:sessionId" element={<ProcessDiscovery />} />
      <Route path="/report/:sessionId" element={<DiscoveryReport />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
