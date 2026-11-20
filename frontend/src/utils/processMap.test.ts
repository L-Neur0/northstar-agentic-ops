/**
 * Tests for the diagram-to-Mermaid converter (spec 23 §11.12; AC-23.88, AC-23.89).
 * Why: the map on the report page is drawn from this text, so its shapes, links and the escaping
 * of untrusted labels are proven here without running Mermaid.
 * What: the recorded EU report's diagram (shapes, lanes, flows, data objects and stores,
 * determinism, empty input) and a hostile diagram (escaping, cutting, generated ids).
 * Must not: run Mermaid or a browser.
 */
import { euReport } from '../test/fixtures/report'
import type { ProcessDiagram } from '../types/report'
import { cleanLabel, mapAsText, toMermaid } from './processMap'

const eu = euReport.map.diagram as ProcessDiagram

describe('toMermaid on the EU diagram (AC-23.88)', () => {
  const text = toMermaid(eu)
  const lines = text.split('\n')

  it('starts with flowchart LR and has one subgraph per lane', () => {
    expect(lines[0]).toBe('flowchart LR')
    expect(text.match(/subgraph L\d+\["/g)).toHaveLength(eu.lanes.length)
    expect(text).toContain('subgraph L0["Cost controller"]')
  })

  it('gives each node type its shape', () => {
    expect(text).toContain('n0(("Month-end close completed"))')
    expect(text).toContain('n2("Step 1 · Collect site spreadsheets")')
    expect(text).toContain('n4{"Totals match SAP?"}')
    expect(text).toContain('n8((("Cost report sent")))')
  })

  it('labels flows and marks default flows', () => {
    expect(text).toContain('n4 -->|"yes"| n5')
    expect(text).toContain('n2 --> n3')
    const withDefault = toMermaid({ ...eu, flows: [{ source: 'g1', target: 't3', label: 'yes', isDefault: true }] })
    expect(withDefault).toContain('n4 -->|"yes (default)"| n5')
  })

  it('draws data objects as parallelograms on the right side and stores as cylinders', () => {
    expect(text).toContain('d0[/"site cost spreadsheets"/]')
    expect(text).toContain('d0 -.-> n2')
    expect(text).toContain('n2 -.-> d1')
    expect(text).toContain('s2[("SAP S/4HANA")]')
    expect(text).toContain('n3 -.- s2')
  })

  it('is deterministic, and an empty diagram gives ""', () => {
    expect(toMermaid(eu)).toBe(text)
    expect(toMermaid({ ...eu, nodes: [] })).toBe('')
    expect(toMermaid(null)).toBe('')
  })

  it('puts a node of an unknown lane in a last "Other" subgraph', () => {
    const odd: ProcessDiagram = { ...eu, nodes: [...eu.nodes, { id: 'x', type: 'task', label: 'Odd', lane: 'Nobody', stepIndex: 9, marker: '' }] }
    expect(toMermaid(odd)).toContain('subgraph L1["Other"]\n    n9("Step 9 · Odd")\n  end')
  })

  it('the text alternative lists steps in order with their lane, then decisions', () => {
    const alt = mapAsText(eu)
    expect(alt.steps[0]).toBe('Step 1 · Collect site spreadsheets (Cost controller)')
    expect(alt.steps).toHaveLength(5)
    expect(alt.decisions).toEqual(['Totals match SAP?: yes, no'])
  })
})

describe('labels are cleaned and ids generated (AC-23.89)', () => {
  const hostile: ProcessDiagram = {
    lanes: ['Lane "A"'],
    nodes: [
      { id: 'raw-id-<script>', type: 'task', label: 'Say "hi" <script>alert(1)</script> ] } \nnext', lane: 'Lane "A"', stepIndex: 1, marker: '' },
      { id: 'end"]; click', type: 'end', label: 'x'.repeat(200), lane: 'Lane "A"', stepIndex: null, marker: '' },
    ],
    flows: [
      { source: 'raw-id-<script>', target: 'end"]; click', label: '', isDefault: false },
      { source: 'raw-id-<script>', target: 'nowhere', label: 'lost', isDefault: false },
    ],
    dataObjects: [],
    dataStores: [],
    simplified: false,
    stepsHash: '',
  }
  const text = toMermaid(hostile)

  it('escapes quotes and angle brackets and keeps one line', () => {
    expect(text).toContain('n0("Step 1 · Say #quot;hi#quot; #lt;script#gt;alert(1)#lt;/script#gt; ] } next")')
    expect(text).not.toContain('<script>')
    expect(text).toContain('subgraph L0["Lane #quot;A#quot;"]')
  })

  it('cuts a label to 80 characters', () => {
    expect(cleanLabel('x'.repeat(200))).toBe(`${'x'.repeat(79)}…`)
  })

  it('never passes a raw id and skips flows to unknown nodes', () => {
    expect(text).not.toContain('raw-id')
    expect(text).not.toContain('click')
    expect(text).toContain('n0 --> n1')
    expect(text).not.toContain('lost')
  })
})
