"use client"

import { useEffect, useRef, useState } from "react"
import { Loader2, X } from "lucide-react"

import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { authFetch } from "@/lib/auth-fetch"
import { consumeJobLogSse } from "@/lib/sinker-job-logs"

const MAX_LINES = 4000

type StreamState = "connecting" | "live" | "ended" | "error"

export function DataSourceJobLogDialog({
  open,
  onOpenChange,
  namespace,
  name,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  namespace: string
  name: string
}) {
  const [lines, setLines] = useState<string[]>([])
  const [state, setState] = useState<StreamState>("connecting")
  const [detail, setDetail] = useState("")
  const scrollerRef = useRef<HTMLPreElement>(null)
  const stickRef = useRef(true)

  useEffect(() => {
    if (!open || !namespace || !name) return
    const ac = new AbortController()
    let cancelled = false
    setLines([])
    setState("connecting")
    setDetail("")
    stickRef.current = true

    void (async () => {
      try {
        const res = await authFetch(
          `/api/v1/namespaces/${encodeURIComponent(namespace)}/descriptor-job-logs/${encodeURIComponent(name)}`,
          { signal: ac.signal, headers: { Accept: "text/event-stream" } },
        )
        if (cancelled) return
        if (!res.ok) {
          setState("error")
          setDetail(await readErrorMessage(res))
          return
        }
        if (!res.body) {
          setState("error")
          setDetail("日志流为空")
          return
        }
        setState("live")
        await consumeJobLogSse(res.body, ({ event, data }) => {
          if (cancelled) return
          if (event === "log") {
            setLines((prev) => {
              const next = prev.length >= MAX_LINES ? prev.slice(prev.length - MAX_LINES + 1) : prev.slice()
              next.push(data)
              return next
            })
            return
          }
          if (event === "error") {
            setState("error")
            setDetail(data || "日志流已中断")
            return
          }
          if (event === "end") setState("ended")
        })
        if (cancelled) return
        setState((current) => (current === "error" ? current : "ended"))
      } catch (err) {
        if (cancelled || ac.signal.aborted) return
        setState("error")
        setDetail(err instanceof Error ? err.message : "无法读取日志")
      }
    })()

    return () => {
      cancelled = true
      ac.abort()
    }
  }, [open, namespace, name])

  useEffect(() => {
    if (!stickRef.current) return
    const el = scrollerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  const statusText =
    state === "connecting" ? "连接中" : state === "live" ? "实时" : state === "ended" ? "已结束" : "失败"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(96vw,56rem)] max-w-4xl p-0 overflow-hidden">
        <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-line">
          <div className="min-w-0">
            <DialogTitle className="text-base">日志</DialogTitle>
            <DialogDescription className="mt-1 truncate font-mono text-xs">
              {namespace}/{name} · data-sinker-job
            </DialogDescription>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-muted px-2.5 py-0.5 text-xs text-content-muted">
              {state === "connecting" || state === "live" ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              {statusText}
            </span>
            <DialogClose asChild>
              <button
                type="button"
                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-content-muted hover:bg-surface-muted hover:text-content"
                aria-label="关闭"
                title="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            </DialogClose>
          </div>
        </div>
        <pre
          ref={scrollerRef}
          onScroll={(e) => {
            const el = e.currentTarget
            stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
          }}
          className="m-0 h-[min(70vh,32rem)] overflow-auto bg-zinc-950 px-4 py-3 font-mono text-xs leading-5 text-zinc-100 whitespace-pre-wrap break-all"
        >
          {lines.length === 0 ? (
            <span className="text-zinc-500">{detail || "等待日志…"}</span>
          ) : (
            lines.join("\n")
          )}
          {lines.length > 0 && detail ? `\n${detail}` : ""}
        </pre>
      </DialogContent>
    </Dialog>
  )
}

async function readErrorMessage(res: Response): Promise<string> {
  const text = await res.text()
  try {
    const body = JSON.parse(text) as { message?: string }
    if (body.message) return body.message
  } catch {
    // not JSON
  }
  if (res.status === 404) return "同步任务尚未就绪，或已经结束并被清理"
  if (res.status === 403) return "没有查看日志的权限"
  return text || "无法读取日志"
}
