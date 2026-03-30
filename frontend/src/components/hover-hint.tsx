"use client"

import { useCallback, useMemo, useState } from "react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"

export function HoverHint({
  text,
  copyText,
  enableCopy,
  className,
  children,
}: {
  text: string
  copyText?: string
  enableCopy?: boolean
  className?: string
  children?: React.ReactNode
}) {
  const t = text ?? ""
  const canCopy = Boolean(enableCopy)
  const c = useMemo(() => (canCopy ? (copyText ?? t).trim() : ""), [canCopy, copyText, t])
  const [copied, setCopied] = useState(false)

  const fallbackCopy = async (text: string) => {
    if (typeof document === "undefined") throw new Error("clipboard unavailable")
    const el = document.createElement("textarea")
    el.value = text
    el.setAttribute("readonly", "true")
    el.style.position = "fixed"
    el.style.top = "0"
    el.style.left = "0"
    el.style.opacity = "0"
    document.body.appendChild(el)
    el.focus()
    el.select()
    const ok = document.execCommand("copy")
    document.body.removeChild(el)
    if (!ok) throw new Error("copy failed")
  }

  const onCopy = useCallback(async () => {
    if (!canCopy || !c) return
    try {
      const clip = typeof navigator !== "undefined" ? navigator.clipboard : undefined
      if (clip && typeof clip.writeText === "function") {
        try {
          await clip.writeText(c)
        } catch {
          // Some environments expose clipboard API but deny access (permissions policy / insecure context / webviews).
          // Fallback to legacy copy instead of failing hard.
          await fallbackCopy(c)
        }
      } else {
        await fallbackCopy(c)
      }
      setCopied(true)
      window.setTimeout(() => setCopied(false), 900)
    } catch (e) {
      console.error("copy failed", e)
      // Keep error feedback as toast; success is shown in tooltip.
      toast.error("复制失败")
    }
  }, [c, canCopy])

  return (
    <div
      className={cn("relative inline-flex min-w-0 max-w-full group", canCopy ? "cursor-copy" : "", className)}
      onClick={onCopy}
      title={canCopy ? "点击复制" : undefined}
    >
      {children ? children : <span className="truncate block w-full">{t}</span>}
      {/* custom tooltip to avoid native title inconsistencies */}
      <span className="pointer-events-none absolute left-0 top-full z-50 mt-2 w-max max-w-[min(80vw,36rem)] rounded-md border border-line bg-surface px-2.5 py-2 text-xs text-content shadow-lg opacity-0 translate-y-1 transition group-hover:opacity-100 group-hover:translate-y-0">
        <span className="break-words whitespace-pre-wrap">{t}</span>
        {canCopy ? <span className="ml-2 text-content-muted">{copied ? "已复制" : "点击复制"}</span> : null}
      </span>
    </div>
  )
}

