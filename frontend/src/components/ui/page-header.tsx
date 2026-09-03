"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

export function PageHeader({
  title,
  description,
  descriptionClassName,
  actions,
  className,
  compact,
}: {
  title: string
  description?: string
  descriptionClassName?: string
  actions?: React.ReactNode
  className?: string
  compact?: boolean
}) {
  return (
    <div className={cn("flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0 space-y-1">
        <h1 className={cn(
          "font-semibold text-content tracking-[-0.03em] text-balance",
          compact ? "text-xl" : "text-2xl sm:text-3xl",
        )}>
          {title}
        </h1>
        {description ? (
          <p className={cn("text-sm text-content-muted max-w-prose leading-relaxed", descriptionClassName)}>{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  )
}
