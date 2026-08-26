"use client"

import { cn } from "@/lib/utils"

export type SegmentedTab<T extends string> = {
  value: T
  label: string
  count?: number
}

export function SegmentedTabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: SegmentedTab<T>[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div className="inline-flex items-center gap-1 rounded-lg border border-line bg-surface-muted/60 p-1">
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          onClick={() => onChange(t.value)}
          className={cn(
            "rounded-md px-3 py-1.5 text-sm transition-colors",
            value === t.value
              ? "bg-surface font-medium text-content shadow-sm"
              : "text-content-muted hover:text-content",
          )}
        >
          {t.label}
          {typeof t.count === "number" && (
            <span className="ml-1.5 text-xs text-content-muted">{t.count}</span>
          )}
        </button>
      ))}
    </div>
  )
}
