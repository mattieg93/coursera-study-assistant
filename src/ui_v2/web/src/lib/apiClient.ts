// src/ui_v2/web/src/lib/apiClient.ts
/**
 * Base HTTP client for all API calls.
 * - Auto-attaches X-Session-ID header (UUID from localStorage).
 * - streamSSE: consume POST-based SSE using fetch + ReadableStream
 *   (NOT EventSource — that only supports GET).
 */

const SESSION_KEY = 'csa_session_id'

function getSessionId(): string {
  let id = localStorage.getItem(SESSION_KEY)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(SESSION_KEY, id)
  }
  return id
}

function defaultHeaders(): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'X-Session-ID': getSessionId(),
  }
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: {
      ...defaultHeaders(),
      ...(options.headers as Record<string, string> | undefined),
    },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`API ${res.status}: ${body}`)
  }
  return res.json() as Promise<T>
}

export async function apiUpload<T>(
  path: string,
  formData: FormData,
): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'X-Session-ID': getSessionId() },
    body: formData,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`Upload ${res.status}: ${body}`)
  }
  return res.json() as Promise<T>
}

/**
 * Stream a POST-based SSE endpoint.
 * Calls onEvent for each parsed `data:` frame; calls onDone when stream ends.
 */
export async function streamSSE<T>(
  path: string,
  body: unknown,
  onEvent: (data: T) => void,
  onDone?: () => void,
): Promise<void> {
  const res = await fetch(path, {
    method: 'POST',
    headers: {
      ...defaultHeaders(),
    },
    body: JSON.stringify(body),
  })

  if (!res.ok || !res.body) {
    const err = await res.text().catch(() => '')
    throw new Error(`SSE ${res.status}: ${err}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // Split on SSE double-newline frame boundaries
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''  // keep any incomplete trailing frame

    for (const frame of frames) {
      for (const line of frame.split('\n')) {
        if (line.startsWith('data: ')) {
          const raw = line.slice(6).trim()
          try {
            const parsed = JSON.parse(raw) as T
            onEvent(parsed)
          } catch {
            // ignore malformed frames
          }
        }
      }
    }
  }

  onDone?.()
}

export function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${path}`
}

export { getSessionId }
