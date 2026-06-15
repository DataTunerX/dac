"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0 space-y-1">
        <h1 className="text-2xl sm:text-3xl font-semibold text-content tracking-[-0.03em] text-balance">
          {title}
        </h1>
        {description ? (
          <p className="text-sm text-content-muted max-w-prose leading-relaxed">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  )
}
