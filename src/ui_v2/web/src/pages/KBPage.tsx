// src/ui_v2/web/src/pages/KBPage.tsx
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { apiFetch } from '@/lib/apiClient'
import { useAppStore } from '@/store/useAppStore'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Textarea } from '@/components/ui/Textarea'

export function KBPage() {
  const { selectedDocId } = useAppStore()
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [tab, setTab] = useState('Manual')
  const [successMsg, setSuccessMsg] = useState('')

  const addMutation = useMutation({
    mutationFn: () =>
      apiFetch('/api/kb/add', {
        method: 'POST',
        body: JSON.stringify({ title: title.trim(), content: content.trim(), tab }),
        headers: { 'Content-Type': 'application/json' },
      }),
    onSuccess: () => {
      setTitle('')
      setContent('')
      setSuccessMsg('Entry added to knowledge base')
      setTimeout(() => setSuccessMsg(''), 3000)
    },
  })

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Knowledge Base</h1>
        <p className="mt-1 text-sm text-gray-500">Manually add lecture notes or summaries to the knowledge base.</p>
      </div>

      <div className="w-full max-w-2xl rounded-lg border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900">
        <h2 className="mb-4 text-sm font-semibold text-gray-800 dark:text-gray-200">Add Entry</h2>

        <div className="flex flex-col gap-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Title / Topic</label>
            <Input
              placeholder="e.g. Week 3 – Gradient Descent"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Tab / Category</label>
            <Input
              placeholder="Manual"
              value={tab}
              onChange={(e) => setTab(e.target.value)}
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-400">Content</label>
            <Textarea
              rows={8}
              placeholder="Paste lecture notes, summaries, or any content to add to the knowledge base…"
              value={content}
              onChange={(e) => setContent(e.target.value)}
            />
          </div>

          {addMutation.isError && (
            <p className="text-sm text-red-600 dark:text-red-400">
              {addMutation.error instanceof Error ? addMutation.error.message : 'Failed to add entry'}
            </p>
          )}

          {successMsg && (
            <p className="text-sm text-green-700 dark:text-green-400">{successMsg}</p>
          )}

          <div className="flex justify-end">
            <Button
              onClick={() => addMutation.mutate()}
              disabled={!title.trim() || !content.trim()}
              loading={addMutation.isPending}
              className="gap-2"
            >
              <Plus className="h-4 w-4" /> Add to Knowledge Base
            </Button>
          </div>
        </div>
      </div>

      {!selectedDocId && (
        <p className="text-sm text-yellow-700 dark:text-yellow-400">
          No Google Doc selected. Select a doc in the sidebar for full KB functionality.
        </p>
      )}
    </div>
  )
}
