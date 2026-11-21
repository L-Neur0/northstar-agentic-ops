/**
 * Keeps one broken report part from blanking the page (spec 23 §11.11.3; AC-23.97; F-16.2).
 * Why: the report is six independent parts (report v2, spec 27); if one cannot be drawn, the expert must still get
 * the other five, with a plain sentence where the broken one would be.
 * Rules: an error boundary per part; on a render error it shows the fallback (the part's heading
 * and "This part could not be shown.") and logs only the error class to the console, never text.
 * Must not: retry, hide the other parts, or show the error message.
 */
import { Component, type ReactNode } from 'react'

interface Props {
  fallback: ReactNode
  children: ReactNode
}

export class ReportPartBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true }
  }

  componentDidCatch(error: unknown): void {
    console.error('report part failed to render:', error instanceof Error ? error.name : typeof error)
  }

  render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}
