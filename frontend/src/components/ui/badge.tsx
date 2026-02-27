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
      ? "text-slate-950 border border-slate-200"
      : variant === "secondary"
        ? "border-transparent bg-slate-100 text-slate-900 hover:bg-slate-100/80"
        : variant === "destructive"
          ? "border-transparent bg-red-500 text-slate-50 shadow hover:bg-red-500/80"
          : "border-transparent bg-slate-900 text-slate-50 shadow hover:bg-slate-900/90"
  return <span className={cn("inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-slate-950 focus:ring-offset-2", v, className)} {...props} />
}

