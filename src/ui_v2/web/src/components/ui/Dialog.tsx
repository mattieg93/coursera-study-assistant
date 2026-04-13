// src/ui_v2/web/src/components/ui/Dialog.tsx
import { cn } from '@/lib/cn'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { useEffect } from 'react'

export function Dialog({ open, onClose, title, children, className }: {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  className?: string
}) {
  // Close on Escape
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Panel */}
      <div className={cn(
        'relative z-10 w-full max-w-md rounded-lg bg-white shadow-xl dark:bg-gray-900',
        'border border-gray-200 dark:border-gray-700',
        className,
      )}>
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700">
          {title && <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{title}</h2>}
          <button
            onClick={onClose}
            className="ml-auto rounded-md p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-300"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="px-4 py-4">{children}</div>
      </div>
    </div>
  )
}
