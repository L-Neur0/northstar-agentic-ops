/**
 * The process map of the report: the stored diagram drawn with Mermaid, with a text alternative
 * (spec 23 §11.12, §11.14.4; AC-23.90, AC-23.91, AC-23.100).
 * Why: the map is the picture experts recognise their process in; it must follow the app theme,
 * print in the light theme, and never break the rest of Part 4 when it cannot be drawn.
 * Rules: Mermaid is loaded with a dynamic `import('mermaid')` only here (not in the interview
 * bundle), with `securityLevel: "strict"`, and gets only `toMermaid` text (generated ids, cleaned
 * labels); the theme follows the `dark` class on `<html>` and switches to light between
 * `beforeprint` and `afterprint`; the renderer is a prop so tests inject a stub.
 * Must not: pass raw ids or unescaped labels to Mermaid, or squeeze the drawing below 600 px.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57, AC-23.102).
 */
import { useEffect, useState } from 'react'
import { mapAsText, mapCounts, toMermaid } from '../../utils/processMap'
import type { ProcessDiagram } from '../../types/report'
import { ReportNoteBox } from './ReportNote'

export type MapTheme = 'default' | 'dark'
export type MapRenderer = (id: string, text: string, theme: MapTheme) => Promise<string>

let renderCount = 0

/** The lazy Mermaid call: the library is fetched the first time a map is drawn. */
const mermaidRenderer: MapRenderer = async (id, text, theme) => {
  const { default: mermaid } = await import('mermaid')
  mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme, flowchart: { htmlLabels: false } })
  const { svg } = await mermaid.render(id, text)
  return svg
}

const isDarkNow = () => typeof document !== 'undefined' && document.documentElement.classList.contains('dark')

/** True while `<html>` carries the `dark` class and no print is running. */
function useMapTheme(): MapTheme {
  const [dark, setDark] = useState(isDarkNow)
  const [printing, setPrinting] = useState(false)
  useEffect(() => {
    const observer = new MutationObserver(() => setDark(isDarkNow()))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    const before = () => setPrinting(true)
    const after = () => setPrinting(false)
    window.addEventListener('beforeprint', before)
    window.addEventListener('afterprint', after)
    return () => {
      observer.disconnect()
      window.removeEventListener('beforeprint', before)
      window.removeEventListener('afterprint', after)
    }
  }, [])
  return dark && !printing ? 'dark' : 'default'
}

export function ProcessMap({
  diagram,
  caption,
  render = mermaidRenderer,
}: {
  diagram: ProcessDiagram | null
  caption: string | null
  render?: MapRenderer
}) {
  const theme = useMapTheme()
  const text = toMermaid(diagram)
  const [drawn, setDrawn] = useState<{ key: string; svg: string | null } | null>(null)
  const key = `${theme}\n${text}`

  useEffect(() => {
    if (!text) return
    let live = true
    renderCount += 1
    render(`process-map-${renderCount}`, text, theme)
      .then((svg) => live && setDrawn({ key, svg }))
      .catch(() => live && setDrawn({ key, svg: null }))
    return () => {
      live = false
    }
  }, [key, text, theme, render])

  const current = drawn?.key === key ? drawn : null
  const failed = !diagram || !text || (current !== null && current.svg === null)
  const counts = diagram ? mapCounts(diagram) : { steps: 0, roles: 0 }
  const alt = diagram ? mapAsText(diagram) : null

  return (
    <div className="my-3">
      {failed ? (
        <ReportNoteBox kind="error" text="The process map could not be drawn." />
      ) : (
        <div role="region" aria-label="Process map" tabIndex={0} className="overflow-x-auto rounded-md border border-line bg-surface p-2 print:overflow-visible">
          {current?.svg ? (
            <div
              role="img"
              aria-label={`Process map: ${counts.steps} steps across ${counts.roles} ${counts.roles === 1 ? 'role' : 'roles'}`}
              className="min-w-[600px] [&_svg]:h-auto [&_svg]:max-w-full"
              dangerouslySetInnerHTML={{ __html: current.svg }}
            />
          ) : (
            <p role="status" className="p-4 text-sm text-muted">
              Drawing the map…
            </p>
          )}
        </div>
      )}
      {caption && <p className="mt-1 text-sm text-muted">{caption}</p>}
      {alt && alt.steps.length > 0 && (
        <details className="mt-2 text-sm print:hidden">
          <summary className="cursor-pointer text-link">Map as text</summary>
          <ol className="ml-5 mt-1 list-decimal text-fg">
            {alt.steps.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ol>
          {alt.decisions.length > 0 && (
            <ul className="ml-5 mt-1 list-disc text-muted">
              {alt.decisions.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </details>
      )}
    </div>
  )
}
