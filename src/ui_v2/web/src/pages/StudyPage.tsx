// src/ui_v2/web/src/pages/StudyPage.tsx
import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Send, ImagePlus, CheckCircle, XCircle } from 'lucide-react'
import { apiFetch, apiUpload, streamSSE } from '@/lib/apiClient'
import { cn } from '@/lib/cn'
import { useAppStore } from '@/store/useAppStore'
import { Button } from '@/components/ui/Button'
import { Textarea } from '@/components/ui/Textarea'
import { Toggle } from '@/components/ui/Toggle'
import { Spinner } from '@/components/ui/Spinner'
import { Badge } from '@/components/ui/Badge'
import { Accordion } from '@/components/ui/Accordion'

// ── Types ──────────────────────────────────────────────────────────────────

type Role = 'user' | 'assistant' | 'system'

interface Message {
  id: string
  role: Role
  content: string
  thinking?: boolean
}

// Shape returned by the backend extract endpoints
interface RawOption { letter: string; text: string }
interface RawQuestion {
  text: string
  options: RawOption[]
  correct: string
  type?: string
  ai_answer?: string
  explanation?: string
}
// Shape of each SSE frame from /api/chat/answer-stream
interface RawStreamEvent {
  index?: number
  answer?: string
  question?: RawQuestion & { ai_answer?: string }
  done?: boolean
}

// Normalised shapes used by the UI
interface QuizQuestion {
  question: string
  options: Record<string, string>
  correct: string
  explanation?: string
}

interface QuizAnswer {
  question_num: number
  predicted_answer: string
  explanation: string
  is_correct: boolean
}

function normalizeQuestion(raw: RawQuestion): QuizQuestion {
  const opts: Record<string, string> = {}
  for (const o of raw.options ?? []) opts[o.letter] = o.text
  return { question: raw.text, options: opts, correct: raw.correct, explanation: raw.explanation }
}

// ── helpers ────────────────────────────────────────────────────────────────

function uid() { return Math.random().toString(36).slice(2) }

function QuestionCard({ q, idx, answer }: { q: QuizQuestion; idx: number; answer?: QuizAnswer }) {
  const optionLetters = Object.keys(q.options).sort()
  // Support both single-select ("A") and multi-select ("A, D, E")
  const predictedSet = new Set(
    answer
      ? answer.predicted_answer.split(/[\s,]+/).map(s => s.trim().toUpperCase()).filter(Boolean)
      : []
  )

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <p className="mb-3 font-medium text-gray-900 dark:text-gray-100">
        <span className="mr-2 text-gray-400">{idx + 1}.</span>{q.question}
      </p>
      <ul className="space-y-1.5">
        {optionLetters.map((letter) => {
          const verdict = answer ? (predictedSet.has(letter) ? true : false) : null
          return (
            <li
              key={letter}
              className={cn(
                'flex items-start gap-2 rounded-md border px-3 py-2 text-sm',
                verdict === null  && 'border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/40',
                verdict === true  && 'border-green-300 bg-green-50 dark:border-green-700/60 dark:bg-green-900/25',
                verdict === false && 'border-red-200 bg-red-50/60 dark:border-red-900/40 dark:bg-red-950/20',
              )}
            >
              <span className={cn(
                'mt-0.5 shrink-0 w-6 font-bold',
                verdict === null  && 'text-gray-500 dark:text-gray-400',
                verdict === true  && 'text-green-700 dark:text-green-400',
                verdict === false && 'text-red-600 dark:text-red-400',
              )}>{letter})</span>
              <span className={cn(
                'flex-1 leading-snug',
                verdict === null  && 'text-gray-700 dark:text-gray-300',
                verdict === true  && 'font-medium text-green-800 dark:text-green-200',
                verdict === false && 'text-red-800/80 dark:text-red-300/80',
              )}>{q.options[letter]}</span>
              {verdict === true  && (
                <span className="ml-1 flex shrink-0 items-center gap-1 text-xs font-semibold text-green-700 dark:text-green-400">
                  <CheckCircle className="h-4 w-4" /> Correct
                </span>
              )}
              {verdict === false && (
                <span className="ml-1 flex shrink-0 items-center gap-1 text-xs font-semibold text-red-500 dark:text-red-400">
                  <XCircle className="h-4 w-4" /> Incorrect
                </span>
              )}
            </li>
          )
        })}
      </ul>
      {answer?.explanation && (
        <Accordion title="Explanation" className="mt-3">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700 dark:text-gray-300">
            {answer.explanation}
          </p>
        </Accordion>
      )}
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────

export function StudyPage() {
  const { agentModel, visionModel, selectedDocId, tbNotesMode, setTbNotesMode, pendingNotes, setPendingNotes } = useAppStore()

  // Local messages (mirrors server, but updated optimistically)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Quiz state
  const [questions, setQuestions] = useState<QuizQuestion[]>([])
  const [answers, setAnswers] = useState<Map<number, QuizAnswer>>(new Map())
  const [extracting, setExtracting] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [writing, setWriting] = useState(false)

  // Load history on mount
  useQuery({
    queryKey: ['chatHistory'],
    queryFn: async () => {
      const data = await apiFetch<{ messages: Array<{ role: Role; content: string }> }>('/api/chat/history')
      setMessages(data.messages.map((m) => ({ ...m, id: uid() })))
      return data
    },
  })

  // Auto-scroll
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, answers, extracting, streaming])

  const appendMessage = useCallback((role: Role, content: string, thinking = false) => {
    const msg: Message = { id: uid(), role, content, thinking }
    setMessages((prev) => [...prev, msg])
    return msg.id
  }, [])

  const replaceMessage = useCallback((id: string, content: string, thinking = false) => {
    setMessages((prev) => prev.map((m) => m.id === id ? { ...m, content, thinking } : m))
  }, [])

  // ── Send a text question ─────────────────────────────────────────────────

  // ── Textbook notes mode ──────────────────────────────────────────────────

  async function handleSendTextbookNotes(topic: string) {
    const thinkId = appendMessage('assistant', '', true)
    setThinking(true)
    try {
      const data = await apiFetch<{ notes: string; textbook: string }>('/api/textbook/generate-notes', {
        method: 'POST',
        body: JSON.stringify({ topic, doc_id: selectedDocId, model: agentModel }),
        headers: { 'Content-Type': 'application/json' },
      })
      setPendingNotes(data.notes)
      replaceMessage(
        thinkId,
        `📖 **${data.textbook}**\n\nNotes generated — review them in the panel below, then write to Google Doc or discard.`,
      )
    } catch (err) {
      replaceMessage(thinkId, `Error: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setThinking(false)
    }
  }

  async function handleWriteToDoc() {
    if (!pendingNotes) return
    setWriting(true)
    try {
      await apiFetch('/api/textbook/write-to-doc', {
        method: 'POST',
        body: JSON.stringify({ doc_id: selectedDocId, notes: pendingNotes }),
        headers: { 'Content-Type': 'application/json' },
      })
      await apiFetch('/api/kb/sync', {
        method: 'POST',
        body: JSON.stringify({ doc_id: selectedDocId }),
        headers: { 'Content-Type': 'application/json' },
      })
      appendMessage('assistant', '✅ Notes written to Google Doc and knowledge base re-synced.')
      setPendingNotes(null)
    } catch (err) {
      appendMessage('system', `Write failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setWriting(false)
    }
  }

  // ── Send a text question ─────────────────────────────────────────────────

  async function handleSend() {
    const query = input.trim()
    if (!query || thinking) return
    setInput('')
    appendMessage('user', query)
    if (tbNotesMode) {
      await handleSendTextbookNotes(query)
      return
    }
    const thinkId = appendMessage('assistant', '', true)
    setThinking(true)

    try {
      const data = await apiFetch<{ type: string; answer?: string; question_num?: number; correct_answer?: string; question_data?: QuizQuestion }>('/api/chat/answer', {
        method: 'POST',
        body: JSON.stringify({ query, model: agentModel, doc_id: selectedDocId }),
        headers: { 'Content-Type': 'application/json' },
      })

      if (data.type === 'correction' && data.question_num && data.correct_answer) {
        // Confirm correction to backend
        await apiFetch('/api/chat/correct', {
          method: 'POST',
          body: JSON.stringify({ question_num: data.question_num, correct_answer: data.correct_answer }),
          headers: { 'Content-Type': 'application/json' },
        })
        replaceMessage(thinkId, `Correction saved: Q${data.question_num} → ${data.correct_answer}`)
      } else {
        replaceMessage(thinkId, data.answer ?? '')
      }
    } catch (err) {
      replaceMessage(thinkId, `Error: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setThinking(false)
    }
  }

  // ── Extract quiz from image file ─────────────────────────────────────────

  async function handleImageFile(file: File) {
    setExtracting(true)
    setQuestions([])
    setAnswers(new Map())

    try {
      const form = new FormData()
      form.append('file', file)
      if (visionModel) form.append('vision_model', visionModel)
      if (agentModel) form.append('model', agentModel)
      if (selectedDocId) form.append('doc_id', selectedDocId)

      const data = await apiUpload<{ questions: RawQuestion[] }>('/api/chat/extract-quiz', form)
      const normalized = (data.questions ?? []).map(normalizeQuestion)
      setQuestions(normalized)

      if (normalized.length) {
        await runAnswerStream(normalized)
      }
    } catch (err) {
      appendMessage('system', `Extraction failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setExtracting(false)
    }
  }

  // ── Extract quiz from clipboard image (base64) ───────────────────────────

  async function handlePastedImage(blob: Blob) {
    setExtracting(true)
    setQuestions([])
    setAnswers(new Map())

    try {
      const reader = new FileReader()
      const b64 = await new Promise<string>((resolve, reject) => {
        reader.onload = () => resolve((reader.result as string).split(',')[1])
        reader.onerror = reject
        reader.readAsDataURL(blob)
      })

      const data = await apiFetch<{ questions: RawQuestion[] }>('/api/chat/extract-quiz-b64', {
        method: 'POST',
        body: JSON.stringify({ data: b64, vision_model: visionModel, model: agentModel, doc_id: selectedDocId }),
        headers: { 'Content-Type': 'application/json' },
      })
      const normalized = (data.questions ?? []).map(normalizeQuestion)
      setQuestions(normalized)

      if (normalized.length) {
        await runAnswerStream(normalized)
      }
    } catch (err) {
      appendMessage('system', `Paste extraction failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setExtracting(false)
    }
  }

  // ── SSE answer stream ────────────────────────────────────────────────────

  async function runAnswerStream(_qs: QuizQuestion[]) {
    setStreaming(true)
    const newAnswers = new Map<number, QuizAnswer>()

    try {
      await streamSSE<RawStreamEvent>(
        '/api/chat/answer-stream',
        { model: agentModel, doc_id: selectedDocId },
        (evt) => {
          if (evt.done || evt.index == null) return  // skip sentinel
          const predicted = (evt.question?.ai_answer ?? '').trim().toUpperCase()
          const correct   = (evt.question?.correct  ?? '').trim().toUpperCase()
          const answer: QuizAnswer = {
            question_num: evt.index + 1,
            predicted_answer: predicted,
            explanation: evt.answer ?? '',
            is_correct: predicted !== '' && predicted === correct,
          }
          newAnswers.set(answer.question_num, answer)
          setAnswers(new Map(newAnswers))
        },
      )
    } catch (err) {
      appendMessage('system', `Streaming error: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setStreaming(false)
    }
  }

  // ── Paste handler on textarea ────────────────────────────────────────────

  function handlePaste(e: React.ClipboardEvent) {
    const items = Array.from(e.clipboardData.items)
    const imageItem = items.find((i) => i.type.startsWith('image/'))
    if (imageItem) {
      e.preventDefault()
      const blob = imageItem.getAsFile()
      if (blob) handlePastedImage(blob)
    }
  }

  // ── File input ────────────────────────────────────────────────────────────

  const fileInputRef = useRef<HTMLInputElement>(null)

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm shadow-sm ${
              msg.role === 'user'
                ? 'bg-indigo-600 text-white'
                : msg.role === 'system'
                ? 'bg-yellow-50 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-300 text-xs'
                : 'bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100'
            }`}>
              {msg.thinking ? (
                <span className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
                  <Spinner size="sm" /> Thinking…
                </span>
              ) : (
                <span className="whitespace-pre-wrap">{msg.content}</span>
              )}
            </div>
          </div>
        ))}

        {/* Quiz extraction */}
        {extracting && (
          <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
            <Spinner size="sm" /> Extracting questions…
          </div>
        )}

        {/* Quiz cards */}
        {questions.length > 0 && (
          <div className="mt-2 space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">{questions.length} Questions</span>
              {streaming && <Badge variant="info"><Spinner size="sm" className="mr-1" />Answering…</Badge>}
              {!streaming && answers.size > 0 && (
                <Badge variant={answers.size === questions.length ? 'success' : 'info'}>
                  {answers.size}/{questions.length} answered
                </Badge>
              )}
            </div>
            {questions.map((q, i) => (
              <QuestionCard key={i} q={q} idx={i} answer={answers.get(i + 1)} />
            ))}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Pending textbook notes panel */}
      {pendingNotes && (
        <div className="border-t border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-800/40 dark:bg-amber-950/30">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300">
            📋 Generated notes — review &amp; confirm
          </p>
          <pre className="mb-3 max-h-48 overflow-y-auto rounded-md border border-amber-100 bg-white/80 p-2 text-xs whitespace-pre-wrap text-gray-700 dark:border-amber-900 dark:bg-gray-900/80 dark:text-gray-300">
            {pendingNotes}
          </pre>
          <div className="flex gap-2">
            <Button size="sm" onClick={handleWriteToDoc} loading={writing}>Write to Google Doc</Button>
            <Button size="sm" variant="ghost" onClick={() => setPendingNotes(null)} disabled={writing}>Discard</Button>
          </div>
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-950">
        <div className="mb-2 flex items-center">
          <Toggle
            checked={tbNotesMode}
            onChange={(v) => { setTbNotesMode(v); if (!v) setPendingNotes(null) }}
            label="📖 Textbook Notes"
          />
        </div>
        <div className="flex items-end gap-2">
          {/* File upload button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            className="shrink-0 rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-300"
            title="Upload quiz image"
            disabled={extracting}
          >
            <ImagePlus className="h-5 w-5" />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) handleImageFile(f); e.target.value = '' }}
          />

          <Textarea
            ref={textareaRef}
            className="max-h-32 flex-1"
            rows={1}
            placeholder={tbNotesMode
              ? "Describe the chapter or topic (e.g. 'Chapter 10: Elementary Data Structures')…"
              : "Ask a question, paste a quiz screenshot, or type a correction like 'Question 3 answer is B'…"
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
            }}
            disabled={thinking}
          />

          <Button
            onClick={handleSend}
            disabled={!input.trim() || thinking}
            loading={thinking}
            className="shrink-0"
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
        <p className="mt-1.5 text-xs text-gray-400">
          {tbNotesMode
            ? 'Type a chapter or topic to generate notes from the associated textbook'
            : 'Paste a screenshot with Ctrl+V / ⌘+V to extract a quiz'
          }
        </p>
      </div>
    </div>
  )
}
