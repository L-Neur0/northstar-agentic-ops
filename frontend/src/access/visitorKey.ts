/**
 * The expert's visitor key and private resume link (spec 23 §3.2, spec 16 §3.1; AC-23.1–23.3).
 * Why: experts do not sign in; a random 128-bit key in `localStorage` scopes their sessions on the
 * server (`owner_id = sha256(key)`), and the resume link `<origin>/#k=<key>` carries it to another
 * device without the fragment ever reaching the server.
 * Rules: the key is a bearer secret. It is sent only as `X-Visitor-Key`, shown only in the resume
 * link box, and never written to a log line, an error message or any other URL. When storage is
 * blocked the key lives in memory for this tab only.
 */

export const VISITOR_KEY_STORAGE = 'discovery_visitor_key'
const VALID_KEY = /^[A-Za-z0-9_-]{22,64}$/

let memoryKey: string | null = null
let storageBroken = false
let accessNotice: string | null = null

function newKey(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  let binary = ''
  for (const b of bytes) binary += String.fromCharCode(b)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function readStored(): string | null {
  try {
    return localStorage.getItem(VISITOR_KEY_STORAGE)
  } catch {
    storageBroken = true
    return null
  }
}

function store(key: string): void {
  try {
    localStorage.setItem(VISITOR_KEY_STORAGE, key)
  } catch {
    storageBroken = true
  }
}

/** The key for this browser, created on first use. */
export function getVisitorKey(): string {
  if (memoryKey) return memoryKey
  const stored = readStored()
  if (stored && VALID_KEY.test(stored)) {
    memoryKey = stored
    return stored
  }
  const key = newKey()
  store(key)
  memoryKey = key
  return key
}

/** False when `localStorage` threw: the key will not survive this tab. */
export function isStorageAvailable(): boolean {
  getVisitorKey()
  return !storageBroken
}

export function resumeLink(): string {
  return `${window.location.origin}/#k=${getVisitorKey()}`
}

/**
 * Runs once before the first render: reads `#k=<key>`, stores a valid key (replacing the old one,
 * spec 23 Q2), removes the fragment and leaves a one-time notice for Home.
 */
export function consumeResumeFragment(): void {
  const hash = window.location.hash
  if (!hash.startsWith('#k=')) return
  const value = hash.slice(3)
  window.history.replaceState(null, '', window.location.pathname + window.location.search)
  if (VALID_KEY.test(value)) {
    store(value)
    memoryKey = value
    accessNotice = 'You opened a resume link. You now see the processes saved with it.'
  } else {
    accessNotice = 'This resume link is not valid.'
  }
}

/** The pending resume notice, or null, without clearing it (safe in a state initialiser). */
export function peekAccessNotice(): string | null {
  return accessNotice
}

/** The one-time resume notice, or null. Reading it clears it. */
export function takeAccessNotice(): string | null {
  const notice = accessNotice
  accessNotice = null
  return notice
}

export function resetVisitorKeyForTests(): void {
  memoryKey = null
  storageBroken = false
  accessNotice = null
}
