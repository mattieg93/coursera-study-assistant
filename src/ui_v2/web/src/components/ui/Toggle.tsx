// src/ui_v2/web/src/components/ui/Toggle.tsx
import { cn } from '@/lib/cn'

export function Toggle({ checked, onChange, label, className }: {
  checked: boolean
  onChange: (checked: boolean) => void
  label?: string
  className?: string
}) {
  return (
    <label className={cn('inline-flex cursor-pointer items-center gap-2', className)}>
      <button
        role="switch"
        aria-checked={checked}
        type="button"
        onClick={() => onChange(!checked)}
        className={cn(
          'relative h-5 w-9 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50',
          checked ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-600',
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
            checked ? 'translate-x-4' : 'translate-x-0',
          )}
        />
      </button>
      {label && <span className="text-sm text-gray-700 dark:text-gray-300">{label}</span>}
    </label>
  )
}
