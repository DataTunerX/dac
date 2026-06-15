"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

export function FieldReadonly({
  label,
  value,
  className,
}: {
  label: string
  value?: string
  className?: string
}) {
  return (
    <div className={cn("space-y-1", className)}>
      <span className="font-mono text-xs text-content-muted">{label}</span>
      <div className="text-sm font-mono text-content break-all rounded-md bg-surface-muted px-3 py-2 border border-line">
        {value?.trim() || <span className="text-content-muted">（空）</span>}
      </div>
    </div>
  )
}
