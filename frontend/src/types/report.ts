/**
 * Wire types of the discovery report, a mirror of `DiscoveryReport` and its part models in the
 * backend's `models/process_discovery_wire.py` (report v2: spec 27 §3.1, §4; spec 23 part 2 §12,
 * Q7/Q8, amended 2026-11-21 (report v2), AC-23.152).
 * Why: the report page renders exactly what `GET /api/sessions/{id}/report` sends, and a drift
 * between the server's names and this file must break the build or the contract test
 * (`services/contract.test.ts` parses a recorded report), not a screen in front of the expert.
 * Rules: every number and level is a display-ready string ("96 h", "Strong fit") because the
 * server formats everything (Q8 resolved: strings); a level is shown as the server's words, never
 * yes / no; hours only, no euro field (R5). Must not: hold logic, add fields the server does not
 * send, or format any value.
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

export interface SummaryPart extends PartBase {
  /** Fixed code sentences (spec 27 §3.5), each left out by the server when its data is missing. */
  sentences: string[]
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
  /** 'strong' | 'partial' | 'weak' | 'not_rated', or null when not assessed (spec 27 §3.3). */
  level: string | null
  /** The server's words for the level ("Strong fit"); never yes / no. */
  levelLabel: string
  /** The step signals behind the level, in fixed words. */
  because: string[]
  /** 'automate' | 'assist' | 'human', or null when not assessed (spec 26). */
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

export interface QuestionRow {
  key: 'q1' | 'q2' | 'q3'
  question: string
  level: string
  /** The server's words ("Strong fit", "Either can work"); never yes / no. */
  levelLabel: string
  why: string
  /** The expert's words behind the motivation, or "". */
  quote: string
}

/** Part 6 (spec 27 §3.1): A the three questions, B readiness, C bullets and the gaps line. */
export interface FeasibilityPart extends PartBase {
  questions: QuestionRow[]
  readiness: ReadinessRow[]
  readinessFooter: string
  bullets: string[]
  gaps: string
}

export interface DiscoveryReport {
  cover: ReportCover
  summary: SummaryPart
  process: FieldsPart
  measures: FieldsPart
  map: MapPart
  steps: StepsPart
  feasibility: FeasibilityPart
  generatedAt: string
}

/** The six part keys in report order (spec 27 §3.1); the client fixes the order, not the titles. */
export const PART_KEYS = ['summary', 'process', 'measures', 'map', 'steps', 'feasibility'] as const

export type PartKey = (typeof PART_KEYS)[number]

/** Fallback headings for a part that is missing from the JSON (spec 23 §11.11.3). */
export const PART_FALLBACK_TITLES: Record<PartKey, string> = {
  summary: 'Summary',
  process: 'The process',
  measures: 'Volume and measures',
  map: 'Process map and steps',
  steps: 'Step-by-step AI assessment',
  feasibility: 'AI readiness and feasibility',
}

/** A report as the page holds it: a part that failed its guard is null (shown as missing). */
export type LoadedReport = { cover: ReportCover | null; generatedAt: string } & { [K in PartKey]: DiscoveryReport[K] | null }
