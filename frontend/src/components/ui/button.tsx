"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

type Variant = "default" | "outline" | "ghost" | "link"
type Size = "default" | "sm" | "icon"

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  size?: Size
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "default", size = "default", type = "button", ...props },
  ref
) {
  const variantClass =
    variant === "outline"
      ? "border border-slate-200 bg-white shadow-sm hover:bg-slate-50 text-slate-900"
      : variant === "ghost"
        ? "hover:bg-slate-100 hover:text-slate-900"
        : variant === "link"
          ? "text-slate-900 underline-offset-4 hover:underline"
        : "bg-slate-900 text-slate-50 shadow hover:bg-slate-900/90"

  const sizeClass =
    size === "sm"
      ? "h-8 rounded-md px-3 text-xs"
      : size === "icon"
        ? "h-9 w-9"
        : "h-9 px-4 py-2"

  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-slate-950 disabled:pointer-events-none disabled:opacity-50",
        variantClass,
        sizeClass,
        className
      )}
      {...props}
    />
  )
})

