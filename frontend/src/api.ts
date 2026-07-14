import type {
  BriefingRecord,
  BriefingSummary,
  CalendarEvent,
  CatalystFeedbackRecord,
  DeepDiveResponse,
  PulseResponse,
  ResearchStatus,
  SportsBoardResponse,
  WireResponse,
} from './types'

const API_BASE = '/api'
const API_SECRET = import.meta.env.VITE_API_SECRET as string | undefined

export type WireParams = {
  page?: number
  page_size?: number
  min_impact?: number
  min_confidence?: number
  ticker?: string
  direction?: string
  catalyst_type?: string
  half_life?: string
}

function buildHeaders(extra?: HeadersInit): HeadersInit {
  const headers = new Headers(extra)
  if (API_SECRET) {
    headers.set('X-API-Secret', API_SECRET)
  }
  return headers
}

async function parseErrorMessage(res: Response): Promise<string> {
  const text = await res.text()
  if (!text) return `Request failed: ${res.status}`
  try {
    const data = JSON.parse(text) as { detail?: string | Array<{ msg?: string }> }
    if (typeof data.detail === 'string') return data.detail
    if (Array.isArray(data.detail)) {
      return data.detail.map((item) => item.msg || JSON.stringify(item)).join(', ')
    }
  } catch {
    // fall through
  }
  return text
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = buildHeaders(init?.headers)
  const res = await fetch(`${API_BASE}${url}`, { ...init, headers })
  if (!res.ok) {
    throw new Error(await parseErrorMessage(res))
  }
  return res.json()
}

export function getLatestBriefing(signal?: AbortSignal): Promise<BriefingRecord | null> {
  return fetchJson<BriefingRecord | null>('/briefing/latest', { signal })
}

export function getBriefingByDate(date: string, signal?: AbortSignal): Promise<BriefingRecord> {
  return fetchJson<BriefingRecord>(`/briefing/${date}`, { signal })
}

export function listBriefings(limit = 30, signal?: AbortSignal): Promise<BriefingSummary[]> {
  return fetchJson<BriefingSummary[]>(`/briefings?limit=${limit}`, { signal })
}

export function getStatus(signal?: AbortSignal): Promise<ResearchStatus> {
  return fetchJson<ResearchStatus>('/status', { signal })
}

export function runResearch(): Promise<ResearchStatus> {
  return fetchJson<ResearchStatus>('/research/run', { method: 'POST' })
}

export function getWire(params: WireParams, signal?: AbortSignal): Promise<WireResponse> {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') qs.set(k, String(v))
  })
  return fetchJson<WireResponse>(`/wire?${qs}`, { signal })
}

export function getPulse(signal?: AbortSignal): Promise<PulseResponse> {
  return fetchJson<PulseResponse>('/pulse', { signal })
}

export function getCalendar(days = 7, wireOnly = false, signal?: AbortSignal): Promise<CalendarEvent[]> {
  return fetchJson<CalendarEvent[]>(`/calendar?days=${days}&wire_only=${wireOnly}`, { signal })
}

export function getDeepDive(ticker: string, signal?: AbortSignal): Promise<DeepDiveResponse> {
  return fetchJson<DeepDiveResponse>(`/deepdive/${ticker}`, { signal })
}

export function getSports(signal?: AbortSignal): Promise<SportsBoardResponse> {
  return fetchJson<SportsBoardResponse>('/sports', { signal })
}

export function runCatalystScan(): Promise<{ status: string }> {
  return fetchJson<{ status: string }>('/catalyst/scan', { method: 'POST' })
}

export function postCatalystFeedback(
  id: number,
  label: string,
  notes = '',
): Promise<CatalystFeedbackRecord> {
  return fetchJson<CatalystFeedbackRecord>(`/catalysts/${id}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label, notes }),
  })
}
