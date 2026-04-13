// src/ui_v2/web/src/hooks/useAgentStream.ts
import { useEffect, useRef, useState } from 'react'
import { wsUrl } from '@/lib/apiClient'

export type AgentEvent =
  | { type: 'item'; itemType: 'VIDEO' | 'READING'; current: number; total: number; title: string }
  | { type: 'stage'; stageNum: number; stageTotal: number; label: string }
  | { type: 'done'; itemType: string; current: number; total: number }
  | { type: 'found'; count: number }
  | { type: 'alldone' }
  | { type: 'log'; text: string }
  | { type: 'status'; status: 'running' | 'done' | 'error' }

export function useAgentStream(jobId: string | null) {
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!jobId) return
    setEvents([])
    setStatus('running')

    const ws = new WebSocket(wsUrl(`/ws/agent/${jobId}`))
    wsRef.current = ws

    ws.onmessage = (e) => {
      try {
        const event: AgentEvent = JSON.parse(e.data)
        setEvents((prev) => [...prev, event])
        if (event.type === 'status') {
          setStatus(event.status === 'done' ? 'done' : event.status === 'error' ? 'error' : 'running')
        }
        if (event.type === 'alldone') {
          setStatus('done')
        }
      } catch {
        setEvents((prev) => [...prev, { type: 'log', text: e.data }])
      }
    }

    ws.onerror = () => setStatus('error')
    ws.onclose = (e) => {
      if (e.code !== 1000) setStatus((s) => (s === 'running' ? 'error' : s))
    }

    return () => {
      ws.close(1000, 'unmount')
      wsRef.current = null
    }
  }, [jobId])

  return { events, status }
}
