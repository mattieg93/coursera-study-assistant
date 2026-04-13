// src/ui_v2/web/src/components/ui/Accordion.tsx
import { cn } from '@/lib/cn'
import type { ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'

export function Accordion({ title, children, className, defaultOpen = false }: {
  title: ReactNode
  children: ReactNode
  className?: string
  defaultOpen?: boolean
}) {
  return (
    <details open={defaultOpen} className={cn('group', className)}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-md px-3 py-2 text-sm font-medium hover:bg-gray-100 dark:hover:bg-gray-800 select-none">
        <span>{title}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-gray-500 transition-transform group-open:rotate-180" />
      </summary>
      <div className="px-3 pb-3 pt-1 text-sm text-gray-700 dark:text-gray-300">
        {children}
      </div>
    </details>
  )
}
