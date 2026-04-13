// src/ui_v2/web/src/pages/AgentPage.tsx
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Play, X } from 'lucide-react'
import { apiFetch } from '@/lib/apiClient'
import { useAppStore } from '@/store/useAppStore'
import { useAgentStream, type AgentEvent } from '@/hooks/useAgentStream'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { Progress } from '@/components/ui/Progress'
import { Spinner } from '@/components/ui/Spinner'

type QueueItem = { url: string; status: 'pending' | 'running' | 'done' | 'error' }

function statusVariant(s: string) {
  if (s === 'done') return 'success'
  if (s === 'error') return 'error'
  if (s === 'running') return 'info'
  return 'default'
}

function AgentEventRow({ event }: { event: AgentEvent }) {
  if (event.type === 'item') {
    return (
      <div className="flex items-center gap-2 py-1 text-sm">
        <Badge variant="info">{event.itemType}</Badge>
        <span className="text-gray-500 dark:text-gray-400">{event.current}/{event.total}</span>
        <span className="text-gray-800 dark:text-gray-200 truncate">{event.title}</span>
      </div>
    )
  }
  if (event.type === 'stage') {
    return (
      <Progress
        value={(event.stageNum / event.stageTotal) * 100}
        label={`Stage ${event.stageNum}/${event.stageTotal}: ${event.label}`}
        className="py-1"
      />
    )
  }
  if (event.type === 'done') {
    return (
      <div className="flex items-center gap-2 py-0.5 text-sm text-green-700 dark:text-green-400">
        <span>✓ {event.itemType} {event.current}/{event.total} complete</span>
      </div>
    )
  }
  if (event.type === 'found') {
    return <p className="text-sm text-gray-600 dark:text-gray-400 py-0.5">Found {event.count} course items</p>
  }
  if (event.type === 'alldone') {
    return <p className="text-sm font-semibold text-green-700 dark:text-green-400 py-1">🎊 All items complete!</p>
  }
  if (event.type === 'log') {
    return <p className="font-mono text-xs text-gray-500 dark:text-gray-500 py-0.5 whitespace-pre-wrap">{event.text}</p>
  }
  return null
}

export function AgentPage() {
  const qc = useQueryClient()
  const { agentModel, selectedDocId } = useAppStore()
  const [urlInput, setUrlInput] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const { events, status } = useAgentStream(jobId)

  // Queue
  const { data: queueData } = useQuery({
    queryKey: ['agentQueue'],
    queryFn: () => apiFetch<{ queue: QueueItem[] }>('/api/agent/queue'),
  })
  const queue = queueData?.queue ?? []

  const addUrlMutation = useMutation({
    mutationFn: (url: string) =>
      apiFetch('/api/agent/queue/add', { method: 'POST', body: JSON.stringify({ url }), headers: { 'Content-Type': 'application/json' } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['agentQueue'] }); setUrlInput('') },
  })

  const removeUrlMutation = useMutation({
    mutationFn: (index: number) => apiFetch(`/api/agent/queue/${index}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agentQueue'] }),
  })

  const clearQueueMutation = useMutation({
    mutationFn: () => apiFetch('/api/agent/queue/clear', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agentQueue'] }),
  })

  const runMutation = useMutation({
    mutationFn: () =>
      apiFetch<{ job_id: string }>('/api/agent/run', {
        method: 'POST',
        body: JSON.stringify({ doc_id: selectedDocId, model: agentModel }),
        headers: { 'Content-Type': 'application/json' },
      }),
    onSuccess: (data) => { setJobId(data.job_id); qc.invalidateQueries({ queryKey: ['agentQueue'] }) },
  })

  const pendingCount = queue.filter((i) => i.status === 'pending').length
  const isRunning = status === 'running' || runMutation.isPending

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Coursera Agent</h1>
        <p className="mt-1 text-sm text-gray-500">Add Coursera module URLs, then run the agent to extract and index course content.</p>
      </div>

      {/* Add URL */}
      <div className="flex gap-2">
        <Input
          className="flex-1"
          placeholder="https://www.coursera.org/learn/..."
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && urlInput.trim()) addUrlMutation.mutate(urlInput.trim()) }}
          disabled={isRunning}
        />
        <Button
          onClick={() => addUrlMutation.mutate(urlInput.trim())}
          disabled={!urlInput.trim() || isRunning}
          loading={addUrlMutation.isPending}
        >
          <Plus className="h-4 w-4 mr-1" /> Add
        </Button>
      </div>

      {/* Queue */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-2 dark:border-gray-700">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Queue ({queue.length})</span>
          {queue.length > 0 && !isRunning && (
            <button onClick={() => clearQueueMutation.mutate()} className="text-xs text-red-600 hover:underline">Clear all</button>
          )}
        </div>
        {queue.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-gray-400">No URLs in queue</p>
        ) : (
          <ul className="divide-y divide-gray-100 dark:divide-gray-800">
            {queue.map((item, i) => (
              <li key={i} className="flex items-center gap-3 px-4 py-2.5">
                <Badge variant={statusVariant(item.status)}>{item.status}</Badge>
                <span className="flex-1 truncate text-xs text-gray-700 dark:text-gray-300">{item.url}</span>
                {item.status === 'pending' && !isRunning && (
                  <button onClick={() => removeUrlMutation.mutate(i)} className="text-gray-400 hover:text-red-600" title="Remove">
                    <X className="h-4 w-4" />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Run button */}
      <div className="flex items-center gap-3">
        <Button
          onClick={() => runMutation.mutate()}
          disabled={pendingCount === 0 || isRunning}
          loading={isRunning}
          className="gap-2"
        >
          <Play className="h-4 w-4" /> Run Agent ({pendingCount})
        </Button>
        {isRunning && <span className="text-sm text-gray-500 dark:text-gray-400">Agent is running…</span>}
        {status === 'done' && <Badge variant="success">Done</Badge>}
        {status === 'error' && <Badge variant="error">Error</Badge>}
      </div>

      {/* Live output */}
      {events.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Live output</span>
            {isRunning && <Spinner size="sm" className="text-gray-400" />}
          </div>
          <div className="space-y-0.5 max-h-80 overflow-y-auto">
            {events.map((evt, i) => (
              <AgentEventRow key={i} event={evt} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
