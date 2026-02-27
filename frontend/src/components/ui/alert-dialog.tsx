"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

type CtxType = {
  open: boolean
  onOpenChange?: (open: boolean) => void
}
const Ctx = React.createContext<CtxType | null>(null)

export function AlertDialog({
  open,
  onOpenChange,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: React.ReactNode
}) {
  return <Ctx.Provider value={{ open, onOpenChange }}>{children}</Ctx.Provider>
}

export function AlertDialogContent({ children, className }: { children: React.ReactNode; className?: string }) {
  const ctx = React.useContext(Ctx)
  if (!ctx?.open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onMouseDown={() => ctx.onOpenChange?.(false)}>
      <div
        className={cn("w-full max-w-md rounded-lg border border-slate-200 bg-white shadow-lg", className)}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  )
}

export function AlertDialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-6 pt-6", className)} {...props} />
}

export function AlertDialogTitle({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("text-base font-semibold text-slate-900", className)} {...props} />
}

export function AlertDialogDescription({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mt-1 text-sm text-slate-500", className)} {...props} />
}

export function AlertDialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-6 pb-6 pt-4 flex items-center justify-end gap-2", className)} {...props} />
}

export function AlertDialogCancel({ className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const ctx = React.useContext(Ctx)
  return (
    <button
      type="button"
      className={cn("h-9 px-4 rounded-md border border-slate-200 text-slate-700 hover:bg-slate-50", className)}
      onClick={(e) => {
        props.onClick?.(e)
        ctx?.onOpenChange?.(false)
      }}
      {...props}
    />
  )
}

export function AlertDialogAction({ className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={cn("h-9 px-4 rounded-md bg-slate-900 text-white hover:bg-slate-800", className)}
      {...props}
    />
  )
}

