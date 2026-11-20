/**
 * Wire types of the discovery report, a mirror of `DiscoveryReport` and its part models in the
 * backend's `models/process_discovery_wire.py` (spec 20 v3 §3.3, §4; spec 23 part 2 §12, Q7/Q8).
 * Why: the report page renders exactly what `GET /api/sessions/{id}/report` sends, and a drift
 * between the server's names and this file must break the build or the contract test
 * (`services/contract.test.ts` parses a recorded report), not a screen in front of the expert.
 * Rules: every number is a display-ready string ("96 h", "About 342 hours a year.") because the
 * server formats everything (Q8 resolved: strings); hours only, no euro field (R5, the parked line
 * is the server's own sentence). Must not: hold logic, add fields the server does not send, or
 * format any value.
 */
import type { FieldStatus } from './process-discovery'

export type ReportNoteKind = 'missing' | 'failed' | 'empty' | 'simplified' | 'incomplete' | 'task' | 'one_off' | 'error'

export interface ReportNote {
  kind: ReportNoteKind
  text: string
}

export interface PartBase {
  number: number
  title: string
  note: ReportNote | null
}

export interface ReportField {
  key: string
  label: string
  value: string
  status: FieldStatus | null
  source: string | null
  quote: string | null
}

export interface ReportCover {
  productName: string
  companyName: string
  processName: string
  department: string
  /** "<code> · <name>", as sent. */
  cluster: string
  region: string
  owner: string
  date: string
  /** The status text ("Mapped", "Validated by IT"). */
  status: string
}

export interface TopOpportunity {
  id: string
  title: string
  stepsLabel: string
  hours: string
}

export interface AtAGlancePart extends PartBase {
  hours: string
  routeHeadline: string | null
  top: TopOpportunity[]
  prepare: string[]
}

export interface FieldsPart extends PartBase {
  fields: ReportField[]
  /** Task or one-off notes shown above the list. */
  notes: ReportNote[]
}

export interface DiagramNode {
  id: string
  type: string
  label: string
  lane: string
  stepIndex: number | null
  marker: string
}

export interface DiagramFlow {
  source: string
  target: string
  label: string
  isDefault: boolean
}

export interface DiagramDataObject {
  id: string
  stepIndex: number
  direction: 'input' | 'output'
  label: string
}

export interface DiagramDataStore {
  id: string
  label: string
  steps: number[]
}

export interface ProcessDiagram {
  lanes: string[]
  nodes: DiagramNode[]
  flows: DiagramFlow[]
  dataObjects: DiagramDataObject[]
  dataStores: DiagramDataStore[]
  simplified: boolean
  stepsHash: string
}

export interface StepColumn {
  number: number
  name: string
  cells: ReportField[]
}

export interface MapPart extends PartBase {
  diagram: ProcessDiagram | null
  processName: string
  caption: string | null
  systems: string[]
  columns: StepColumn[]
  rowLabels: string[]
}

export interface StepRow {
  number: number
  name: string
  hours: string
  /** 'automate' | 'assist' | 'human', or null when not assessed. */
  fit: string | null
  fitLabel: string
  routeId: string | null
  routeName: string
  routeReason: string
  reason: string
  evidence: string
  evidenceLabel: string
}

export interface StepsPart extends PartBase {
  rows: StepRow[]
  catalogueNote: string | null
}

export interface RouteItem {
  number: number
  name: string
  hours: string
  routeName: string
  reason: string
}

export interface RouteGroup {
  key: string
  title: string
  items: RouteItem[]
}

export interface RoutePart extends PartBase {
  headline: string
  groups: RouteGroup[]
  prepare: string[]
  catalogueNote: string | null
}

export interface ReportOpportunity {
  id: string
  title: string
  stepsLabel: string
  typeLabel: string
  whatChanges: string
  how: string
  prepareFirst: string
  /** The impact word ("High"). */
  impact: string
  impactReason: string
  /** The feasibility word ("Medium"). */
  feasibility: string
  feasibilityReason: string
  evidence: string
  evidenceLabel: string
  /** The review status text ("Accepted by IT"), or null. */
  review: string | null
}

export interface ReportStayHuman {
  stepsLabel: string
  reason: string
  evidence: string
}

export interface AssessmentPart extends PartBase {
  summary: string
  opportunities: ReportOpportunity[]
  stayHuman: ReportStayHuman[]
}

export interface StepValueRow {
  number: number
  name: string
  hoursPerRun: string
  runsPerYear: string
  hoursPerYear: string
}

export interface OpportunityValueRow {
  id: string
  title: string
  stepsLabel: string
  stepHours: string
}

export interface PotentialPart extends PartBase {
  complete: boolean
  steps: StepValueRow[]
  opportunities: OpportunityValueRow[]
  totals: { hours: string }
  formulas: string[]
  assumptions: string[]
  problems: string[]
  /** The server's sentence that euro values are not shown yet (R5). */
  parkedLine: string
}

export interface ReadinessRow {
  key: string
  label: string
  question: string
  level: string
  levelLabel: string
  reason: string
  toPrepare: string
  note: string
}

export interface ReadinessPart extends PartBase {
  dimensions: ReadinessRow[]
  footer: string
}

export interface PathItem {
  opportunityId: string
  title: string
  stepsLabel: string
  stepHours: string
}

export interface PathGroup {
  key: string
  title: string
  prepareLines: string[]
  items: PathItem[]
  emptyText: string | null
}

export interface PathPart extends PartBase {
  groups: PathGroup[]
}

export interface GapsPart extends PartBase {
  fields: ReportField[]
  documents: { name: string; outcome: string }[]
  closingNote: string
}

export interface DiscoveryReport {
  cover: ReportCover
  atAGlance: AtAGlancePart
  process: FieldsPart
  measures: FieldsPart
  map: MapPart
  steps: StepsPart
  route: RoutePart
  assessment: AssessmentPart
  potential: PotentialPart
  readiness: ReadinessPart
  path: PathPart
  gaps: GapsPart
  generatedAt: string
}

/** The eleven part keys in report order (spec 20 §3.3); the client fixes the order, not the titles. */
export const PART_KEYS = [
  'atAGlance',
  'process',
  'measures',
  'map',
  'steps',
  'route',
  'assessment',
  'potential',
  'readiness',
  'path',
  'gaps',
] as const

export type PartKey = (typeof PART_KEYS)[number]

/** Fallback headings for a part that is missing from the JSON (spec 23 §11.11.3). */
export const PART_FALLBACK_TITLES: Record<PartKey, string> = {
  atAGlance: 'At a glance',
  process: 'The process',
  measures: 'Volume and measures',
  map: 'Process map and steps',
  steps: 'Step-by-step AI assessment',
  route: 'Recommended route',
  assessment: 'Transformation assessment',
  potential: 'Hours a year',
  readiness: 'Readiness checklist',
  path: 'Suggested path',
  gaps: 'Gaps and sources',
}

/** A report as the page holds it: a part that failed its guard is null (shown as missing). */
export type LoadedReport = { cover: ReportCover | null; generatedAt: string } & { [K in PartKey]: DiscoveryReport[K] | null }
