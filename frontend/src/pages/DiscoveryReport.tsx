/**
 * Report page placeholder (spec 23 §3.1, part 1).
 * Why: *Finish* navigates to `/report/:sessionId`; part 1 only needs a page that says the map is
 * finished and leads back to My processes. Part 2 builds the real report screen here.
 * Rules: shows no report data and calls no API.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { AppHeader } from '../components/layout/AppHeader'

export function DiscoveryReport() {
  return (
    <div className="flex min-h-screen flex-col bg-page">
      <AppHeader />
      <main className="mx-auto w-full max-w-2xl px-4 py-10">
        <h2 className="mb-2 text-xl font-semibold text-fg">Your discovery report</h2>
        <p className="mb-6 text-fg">Your map is finished. Your discovery report will be shown here.</p>
        <Link to="/" className="inline-flex items-center gap-1.5 text-sm font-medium text-link underline underline-offset-2">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back to My processes
        </Link>
      </main>
    </div>
  )
}
