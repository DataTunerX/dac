"use client"

import type { ComponentType } from "react"

export type EmptyStateProps = {
  icon: ComponentType<{ className?: string }>
  message: string
  subMessage?: string
  className?: string
}

export function EmptyState({
  icon: Icon,
  message,
  subMessage,
  className = "",
}: EmptyStateProps) {
  return (
    <div className={`py-24 flex flex-col items-center justify-center text-content-muted ${className}`}>
      <div className="w-12 h-12 rounded-lg border border-line bg-surface flex items-center justify-center mb-5">
        <Icon className="w-5 h-5 text-content-muted" />
      </div>
      <p className="text-base font-medium text-content tracking-[-0.01em]">{message}</p>
      {subMessage ? <p className="text-sm mt-2 text-content-muted max-w-sm text-center leading-relaxed">{subMessage}</p> : null}
    </div>
  )
}
