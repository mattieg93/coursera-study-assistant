// src/ui_v2/web/src/components/ui/Progress.tsx
import { cn } from '@/lib/cn'

export function Progress({ value, label, className }: {
  value: number   // 0-100
  label?: string
  className?: string
}) {
  const clamped = Math.min(100, Math.max(0, value))
  return (
    <div className={cn('w-full', className)}>
      {label && (
        <div className="mb-1 flex justify-between text-xs text-gray-500 dark:text-gray-400">
          <span>{label}</span>
          <span>{clamped}%</span>
        </div>
      )}
      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
        <div
          className="h-full rounded-full bg-primary transition-all duration-300"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  )
}
