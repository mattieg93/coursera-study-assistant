// src/ui_v2/web/src/components/Sidebar.tsx
import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation } from 'wouter'
import { BookOpen, Bot, Database, RefreshCw, Trash2, Plus, Pencil, Moon, Sun } from 'lucide-react'
import { apiFetch } from '@/lib/apiClient'
import { cn } from '@/lib/cn'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import { Spinner } from '@/components/ui/Spinner'
import { useAppStore } from '@/store/useAppStore'

// ── Types ──────────────────────────────────────────────────────────────────

type Doc = { id: string; name: string }

interface InitData {
  docs: Doc[]
  prefs: { agent_model: string; vision_model: string }
  models: string[]
  vision_models: string[]
}

// ── Component ──────────────────────────────────────────────────────────────

export function Sidebar() {
  const qc = useQueryClient()
  const [location] = useLocation()
  const {
    agentModel, visionModel, selectedDocId, darkMode,
    setAgentModel, setVisionModel, setSelectedDocId, toggleDarkMode,
  } = useAppStore()

  // ── Single bootstrap query — replaces 4 separate queries ────────────────
  const { data: initData, isLoading } = useQuery<InitData>({
    queryKey: ['appInit'],
    queryFn:  () => apiFetch<InitData>('/api/init'),
    staleTime: 60_000,
    retry: 2,
  })

  const docs         = initData?.docs         ?? []
  const rawModels    = initData?.models        ?? []
  const rawVision    = initData?.vision_models ?? []
  const visionModels = ['Auto-detect', ...rawVision]

  // v1 parity: ensure the saved model appears in the list even if Ollama
  // returns a different set (e.g. model loaded via .env / prefs)
  const models =
    rawModels.length > 0 && agentModel && !rawModels.includes(agentModel)
      ? [agentModel, ...rawModels]
      : rawModels

  // ── First-load initialization from server prefs ──────────────────────────
  // Mirror exactly what v1 does in session_state init:
  //   agent_model  → prefs.agent_model   (never override if user already changed it)
  //   vision_model → prefs.vision_model  (override blindly on first load)
  //   selectedDocId → first doc if current value not in the returned list
  const didInit = useRef(false)
  useEffect(() => {
    if (!initData || didInit.current) return
    didInit.current = true

    const { prefs } = initData

    // Always apply prefs on first load (store default is '' / 'Auto-detect')
    if (prefs.agent_model) setAgentModel(prefs.agent_model)
    if (prefs.vision_model && prefs.vision_model !== 'Auto-detect') {
      setVisionModel(prefs.vision_model)
    }

    // Auto-select first doc if current selectedDocId is missing or stale
    const validDoc = initData.docs.find((d) => d.id === selectedDocId)
    if (!validDoc && initData.docs.length > 0) {
      const firstId = initData.docs[0].id
      setSelectedDocId(firstId)
      apiFetch(`/api/docs/select/${firstId}`, { method: 'POST' }).catch(() => {})
    } else if (validDoc && selectedDocId) {
      // Let backend know which doc this session should use
      apiFetch(`/api/docs/select/${selectedDocId}`, { method: 'POST' }).catch(() => {})
    }
  }, [initData]) // eslint-disable-line react-hooks/exhaustive-deps

  // Persist model preference to server on change
  const updatePrefs = (patch: { agent_model?: string; vision_model?: string }) =>
    apiFetch('/api/docs/prefs', {
      method: 'PATCH',
      body: JSON.stringify(patch),
      headers: { 'Content-Type': 'application/json' },
    })

  // ── Doc dialog state ─────────────────────────────────────────────────────
  const [docDialogOpen, setDocDialogOpen] = useState(false)
  const [editingDoc, setEditingDoc]       = useState<Doc | null>(null)
  const [docIdInput, setDocIdInput]       = useState('')
  const [docNameInput, setDocNameInput]   = useState('')

  const saveDocMutation = useMutation({
    mutationFn: (d: Doc) =>
      apiFetch('/api/docs', { method: 'POST', body: JSON.stringify(d), headers: { 'Content-Type': 'application/json' } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['appInit'] }); setDocDialogOpen(false) },
  })

  const selectDocMutation = useMutation({
    mutationFn: (id: string) => apiFetch(`/api/docs/select/${id}`, { method: 'POST' }),
    onSuccess: (_data, id) => setSelectedDocId(id),
  })

  function openAddDoc() { setEditingDoc(null); setDocIdInput(''); setDocNameInput(''); setDocDialogOpen(true) }
  function openEditDoc(doc: Doc) { setEditingDoc(doc); setDocIdInput(doc.id); setDocNameInput(doc.name); setDocDialogOpen(true) }

  // ── KB stats ─────────────────────────────────────────────────────────────
  const { data: statsData } = useQuery({
    queryKey: ['kbStats'],
    queryFn:  () => apiFetch<{ stats: string }>('/api/kb/stats'),
    staleTime: 30_000,
    enabled: !!selectedDocId,
  })

  // ── Sync KB ───────────────────────────────────────────────────────────────
  const [syncing, setSyncing] = useState(false)
  async function handleSync() {
    setSyncing(true)
    try {
      await apiFetch('/api/kb/sync', {
        method: 'POST',
        body: JSON.stringify({ doc_id: selectedDocId || '' }),
        headers: { 'Content-Type': 'application/json' },
      })
    } finally {
      setSyncing(false)
      qc.invalidateQueries({ queryKey: ['kbStats'] })
    }
  }

  // ── Clear chat ────────────────────────────────────────────────────────────
  const clearChat = useMutation({
    mutationFn: () => apiFetch('/api/chat/history', { method: 'DELETE' }),
    onSuccess:  () => qc.invalidateQueries({ queryKey: ['chatHistory'] }),
  })

  // ── Dark mode ─────────────────────────────────────────────────────────────
  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode)
  }, [darkMode])

  // ── Nav links ─────────────────────────────────────────────────────────────
  const navLinks = [
    { to: '/',       label: 'Study',          icon: BookOpen  },
    { to: '/agent',  label: 'Agent',          icon: Bot       },
    { to: '/kb',     label: 'Knowledge Base', icon: Database  },
  ]

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900">
      {/* Logo */}
      <div className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">
        <span className="text-sm font-bold text-gray-900 dark:text-gray-100">Study Assistant</span>
      </div>

      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        {/* Navigation — Link renders <a> directly; no nested <a> */}
        <nav className="flex flex-col gap-1">
          {navLinks.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              href={to}
              className={cn(
                'flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                location === to
                  ? 'bg-primary text-white'
                  : 'text-gray-700 hover:bg-gray-200 dark:text-gray-300 dark:hover:bg-gray-800',
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </Link>
          ))}
        </nav>

        <hr className="border-gray-200 dark:border-gray-700" />

        {isLoading ? (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Spinner size="sm" /> Loading…
          </div>
        ) : (
          <>
            {/* Agent model */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold uppercase tracking-wide text-gray-500">Model</label>
              {models.length > 0 ? (
                <select
                  className="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
                  value={agentModel}
                  onChange={(e) => {
                    const v = e.target.value
                    setAgentModel(v)
                    updatePrefs({ agent_model: v })
                  }}
                >
                  {models.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              ) : (
                <>
                  <Input
                    placeholder="e.g. gemma4:latest"
                    value={agentModel}
                    onChange={(e) => setAgentModel(e.target.value)}
                    onBlur={() => updatePrefs({ agent_model: agentModel })}
                  />
                  <p className="text-xs text-yellow-600 dark:text-yellow-400">
                    ⚠️ Ollama not running — enter model tag manually.
                  </p>
                </>
              )}
            </div>

            {/* Vision model */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold uppercase tracking-wide text-gray-500">Vision Model</label>
              {visionModels.length > 1 ? (
                <select
                  className="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
                  value={visionModel || 'Auto-detect'}
                  onChange={(e) => {
                    const v = e.target.value
                    setVisionModel(v === 'Auto-detect' ? '' : v)
                    updatePrefs({ vision_model: v === 'Auto-detect' ? '' : v })
                  }}
                >
                  {visionModels.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              ) : (
                <p className="text-xs text-gray-400">
                  No vision models found — pull <code>llava</code> or <code>minicpm-v</code>.
                </p>
              )}
            </div>

            <hr className="border-gray-200 dark:border-gray-700" />

            {/* Google Doc */}
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold uppercase tracking-wide text-gray-500">Google Doc</label>
                <button onClick={openAddDoc} className="rounded p-0.5 text-gray-500 hover:text-primary" title="Add doc">
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
              {docs.length > 0 ? (
                <div className="flex items-center gap-1">
                  <select
                    className="flex-1 rounded-md border border-gray-300 bg-white px-2 py-1.5 text-xs dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
                    value={selectedDocId}
                    onChange={(e) => {
                      const id = e.target.value
                      setSelectedDocId(id)
                      selectDocMutation.mutate(id)
                    }}
                  >
                    {docs.map((d) => (
                      <option key={d.id} value={d.id}>{d.name || d.id}</option>
                    ))}
                  </select>
                  {selectedDocId && (
                    <button
                      onClick={() => { const d = docs.find((x) => x.id === selectedDocId); if (d) openEditDoc(d) }}
                      className="rounded p-1 text-gray-500 hover:text-primary"
                      title="Edit"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              ) : (
                <p className="text-xs text-gray-400">No docs saved yet.</p>
              )}
              {selectedDocId && (
                <a
                  href={`https://docs.google.com/document/d/${selectedDocId}/edit`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-blue-600 hover:underline dark:text-blue-400"
                >
                  View in Google Docs ↗
                </a>
              )}
            </div>
          </>
        )}

        <hr className="border-gray-200 dark:border-gray-700" />

        {/* Actions */}
        <div className="flex flex-col gap-2">
          <Button variant="secondary" size="sm" onClick={handleSync} loading={syncing} className="justify-start gap-2">
            <RefreshCw className="h-3.5 w-3.5" /> Sync from Google Doc
          </Button>
          <Button
            variant="ghost" size="sm"
            onClick={() => clearChat.mutate()}
            className="justify-start gap-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
          >
            <Trash2 className="h-3.5 w-3.5" /> Clear Chat
          </Button>
        </div>

        {/* KB Stats */}
        {statsData?.stats && (
          <div className="rounded-md bg-gray-100 p-2 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-400 whitespace-pre-wrap">
            {statsData.stats}
          </div>
        )}
      </div>

      {/* Dark mode toggle */}
      <div className="border-t border-gray-200 px-4 py-3 dark:border-gray-700">
        <button
          onClick={toggleDarkMode}
          className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
        >
          {darkMode ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          {darkMode ? 'Light mode' : 'Dark mode'}
        </button>
      </div>

      {/* Doc Dialog */}
      <Dialog
        open={docDialogOpen}
        onClose={() => setDocDialogOpen(false)}
        title={editingDoc ? 'Edit Google Doc' : 'Add Google Doc'}
      >
        <div className="flex flex-col gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300">
              Doc ID (from URL)
            </label>
            <Input
              placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74…"
              value={docIdInput}
              onChange={(e) => setDocIdInput(e.target.value)}
              disabled={!!editingDoc}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300">
              Display name (optional)
            </label>
            <Input
              placeholder="e.g. CU - MSDS - Prereqs"
              value={docNameInput}
              onChange={(e) => setDocNameInput(e.target.value)}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDocDialogOpen(false)}>Cancel</Button>
            <Button
              size="sm"
              onClick={() => saveDocMutation.mutate({ id: docIdInput.trim(), name: docNameInput.trim() })}
              loading={saveDocMutation.isPending}
              disabled={!docIdInput.trim()}
            >
              Save
            </Button>
          </div>
        </div>
      </Dialog>
    </aside>
  )
}
