/**
 * Turns the stored process diagram (spec 18) into Mermaid flowchart text and a text alternative
 * (spec 23 §11.12; AC-23.88, AC-23.89, AC-23.90).
 * Why: the server sends the diagram model, not Mermaid text, so the client draws one picture per
 * report from the same data the PDF uses; a pure, deterministic converter is testable without a
 * browser and keeps untrusted labels away from Mermaid's syntax.
 * Rules: generated ids only (`n0`, `d0`, `s0`): a raw id never reaches Mermaid; every label is one
 * line, escaped (`"` `<` `>`) and cut to 80 characters; flows to unknown nodes are skipped; an
 * empty diagram gives "". Must not: render, read the clock or decide anything about the process.
 */
import type { ProcessDiagram } from '../types/report'

const LABEL_MAX = 80

/** One line, cut to 80 characters with "…", then escaped for a quoted Mermaid label. */
export function cleanLabel(text: string): string {
  const line = text.replace(/\s*[\r\n]+\s*/g, ' ').trim()
  const cut = line.length > LABEL_MAX ? `${line.slice(0, LABEL_MAX - 1)}…` : line
  return cut.replace(/"/g, '#quot;').replace(/</g, '#lt;').replace(/>/g, '#gt;')
}

const OTHER_LANE = 'Other'

export function toMermaid(diagram: ProcessDiagram | null): string {
  if (!diagram || diagram.nodes.length === 0) return ''
  const ids = new Map<string, string>()
  diagram.nodes.forEach((node, i) => ids.set(node.id, `n${i}`))

  const shape = (i: number): string => {
    const node = diagram.nodes[i]
    const label = cleanLabel(node.label)
    const id = `n${i}`
    switch (node.type) {
      case 'start':
        return `${id}(("${label || ' '}"))`
      case 'end':
        return `${id}((("${label || ' '}")))`
      case 'gateway':
        return `${id}{"${label || ' '}"}`
      default: {
        const text = node.stepIndex === null ? label : `Step ${node.stepIndex} · ${label}`
        return `${id}("${text || ' '}")`
      }
    }
  }

  const lines = ['flowchart LR']
  const lanes = [...diagram.lanes]
  const unknown = diagram.nodes.some((n) => !lanes.includes(n.lane))
  if (unknown) lanes.push(OTHER_LANE)
  lanes.forEach((lane, li) => {
    const members = diagram.nodes
      .map((n, i) => ({ n, i }))
      .filter(({ n }) => (lane === OTHER_LANE && li === lanes.length - 1 && unknown ? !diagram.lanes.includes(n.lane) : n.lane === lane))
    if (members.length === 0) return
    lines.push(`  subgraph L${li}["${cleanLabel(lane) || ' '}"]`)
    for (const { i } of members) lines.push(`    ${shape(i)}`)
    lines.push('  end')
  })

  for (const flow of diagram.flows) {
    const a = ids.get(flow.source)
    const b = ids.get(flow.target)
    if (!a || !b) continue
    const label = cleanLabel([flow.label, flow.isDefault ? '(default)' : ''].filter(Boolean).join(' '))
    lines.push(label ? `  ${a} -->|"${label}"| ${b}` : `  ${a} --> ${b}`)
  }

  const taskOf = (step: number) => {
    const i = diagram.nodes.findIndex((n) => n.type === 'task' && n.stepIndex === step)
    return i >= 0 ? `n${i}` : null
  }
  diagram.dataObjects.forEach((obj, i) => {
    const task = taskOf(obj.stepIndex)
    if (!task) return
    lines.push(`  d${i}[/"${cleanLabel(obj.label) || ' '}"/]`)
    lines.push(obj.direction === 'input' ? `  d${i} -.-> ${task}` : `  ${task} -.-> d${i}`)
  })
  diagram.dataStores.forEach((store, i) => {
    lines.push(`  s${i}[("${cleanLabel(store.label) || ' '}")]`)
    for (const step of store.steps) {
      const task = taskOf(step)
      if (task) lines.push(`  ${task} -.- s${i}`)
    }
  })
  return lines.join('\n')
}

/** The "Map as text" lines: tasks in step order with their lane, then the decisions. */
export function mapAsText(diagram: ProcessDiagram): { steps: string[]; decisions: string[] } {
  const steps = diagram.nodes
    .filter((n) => n.type === 'task')
    .sort((a, b) => (a.stepIndex ?? Number.MAX_SAFE_INTEGER) - (b.stepIndex ?? Number.MAX_SAFE_INTEGER))
    .map((n) => `${n.stepIndex === null ? '' : `Step ${n.stepIndex} · `}${n.label}${n.lane ? ` (${n.lane})` : ''}`)
  const decisions = diagram.nodes
    .filter((n) => n.type === 'gateway' && n.label.trim())
    .map((g) => {
      const branches = diagram.flows.filter((f) => f.source === g.id && f.label.trim()).map((f) => f.label)
      return branches.length ? `${g.label}: ${branches.join(', ')}` : g.label
    })
  return { steps, decisions }
}

/** Counts for the map's accessible name. */
export function mapCounts(diagram: ProcessDiagram): { steps: number; roles: number } {
  return { steps: diagram.nodes.filter((n) => n.type === 'task').length, roles: diagram.lanes.length }
}
