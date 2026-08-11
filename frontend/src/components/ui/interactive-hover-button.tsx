"use client"

import { cn } from "@/lib/utils"

export function InteractiveHoverButton({
  children,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-md border border-line bg-btn-primary px-6 py-2.5 text-sm font-medium text-content-inverse transition-colors duration-200 hover:bg-btn-primary-hover active:scale-[0.98]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-line-hover focus-visible:ring-offset-2 focus-visible:ring-offset-surface",
        className
      )}
      {...props}
    >
      {children}
    </button>
  )
}
