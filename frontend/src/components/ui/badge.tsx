"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

type Variant = "default" | "secondary" | "outline" | "destructive"

export type BadgeProps = React.HTMLAttributes<HTMLSpanElement> & {
  variant?: Variant
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  const v =
    variant === "outline"
      ? "text-content border border-line"
      : variant === "secondary"
        ? "border-transparent bg-surface-muted text-content hover:bg-surface-muted/80"
        : variant === "destructive"
          ? "border-transparent bg-red-500 text-content-inverse shadow hover:bg-red-500/80"
          : "border-transparent bg-surface-inverse text-content-inverse shadow hover:bg-surface-inverse/90"
  return <span className={cn("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-cta focus:ring-offset-2", v, className)} {...props} />
}

