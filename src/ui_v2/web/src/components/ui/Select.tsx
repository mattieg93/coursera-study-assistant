// src/ui_v2/web/src/components/ui/Select.tsx
import { cn } from '@/lib/cn'
import { type SelectHTMLAttributes, forwardRef } from 'react'

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  options: string[]
  placeholder?: string
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, options, placeholder, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        'w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm',
        'focus:outline-none focus:ring-2 focus:ring-gray-900',
        'dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {placeholder && <option value="">{placeholder}</option>}
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  ),
)
Select.displayName = 'Select'
