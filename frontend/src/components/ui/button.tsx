"use client"

import * as React from "react"
import { Slot } from "@radix-ui/react-slot"

import { cn } from "@/lib/utils"

type Variant = "default" | "outline" | "ghost" | "link"
type Size = "default" | "sm" | "icon"

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  size?: Size
  asChild?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "default", size = "default", type = "button", asChild = false, ...props },
  ref,
) {
  const Comp = asChild ? Slot : "button"

  const variantClass =
    variant === "outline"
      ? "border border-line bg-surface shadow-sm hover:bg-surface-muted text-content"
      : variant === "ghost"
        ? "hover:bg-surface-muted hover:text-content"
        : variant === "link"
          ? "text-content underline-offset-4 hover:underline"
          : "bg-btn-primary text-content-inverse shadow hover:bg-btn-primary-hover"

  const sizeClass =
    size === "sm"
      ? "h-8 rounded-md px-3 text-xs"
      : size === "icon"
        ? "h-9 w-9"
        : "h-9 px-4 py-2"

  return (
    <Comp
      ref={ref}
      {...(!asChild ? { type } : {})}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium cursor-pointer transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cta focus-visible:ring-offset-2 focus-visible:ring-offset-surface disabled:pointer-events-none disabled:opacity-50 disabled:cursor-not-allowed",
        variantClass,
        sizeClass,
        className,
      )}
      {...props}
    />
  )
})

Button.displayName = "Button"
