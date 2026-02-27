"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

export function Avatar({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("inline-flex h-9 w-9 items-center justify-center rounded-full bg-slate-200", className)} {...props} />
}

export function AvatarFallback({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("text-xs font-semibold text-slate-700", className)} {...props} />
}

