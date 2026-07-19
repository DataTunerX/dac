"use client"

import { memo, useEffect, useRef, useState, useId } from "react"
import { Maximize2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { sanitizeSvg } from "@/lib/sanitize-svg"

type MermaidBlockProps = {
  value: string
  className?: string
}

/** 修复大模型常输出的错误 Mermaid 语法（引号、subgraph 格式） */
function normalizeMermaidFromLLM(source: string): string {
  let s = source
  // Strip diagram-level init overrides (can re-enable unsafe securityLevel)
  s = s.replace(/%%\{[\s\S]*?\}%%/g, "")
  // 1. 统一引号：中文/Unicode 弯引号 → ASCII
  s = s.replace(/\u201C|\u201D/g, '"')
  s = s.replace(/\u2018|\u2019/g, "'")

  // 2. 同行且紧跟 -->：subgraph "标题" F --> xxx → subgraph 用另一 id 避免 F 既是 subgraph 又是节点导致 cycle
  s = s.replace(
    /subgraph\s+(?:"([^"]*)"|'([^']*)')\s+([A-Za-z][A-Za-z0-9]*)\s*(-->)([^\n]*)/g,
    (_, dq, sq, id, arrow, rest) => `subgraph sub_${id}["${dq || sq}"]\n  ${id}${arrow}${rest}`
  )
  // 3. 同行无 -->：subgraph "标题" F → subgraph 用 sub_F 避免与节点 F 重名
  s = s.replace(
    /subgraph\s+(?:"([^"]*)"|'([^']*)')\s+([A-Za-z][A-Za-z0-9]*)\b/g,
    (_, dq, sq, id) => `subgraph sub_${id}["${dq || sq}"]`
  )
  // 4. 换行：subgraph "标题" 后换行再写 id 及本行剩余 → subgraph sub_id["标题"] 换行 id + 剩余（sub_ 避免 cycle）
  s = s.replace(
    /subgraph\s+(?:"([^"]*)"|'([^']*)')\s*\n\s*([A-Za-z][A-Za-z0-9]*)([^\n]*)/g,
    (_, dq, sq, id, rest) => `subgraph sub_${id}["${dq || sq}"]\n  ${id}${rest}`
  )
  return s
}

export const MermaidBlock = memo(function MermaidBlock({ value, className }: MermaidBlockProps) {
  const raw = (value ?? "").trim()
  const containerRef = useRef<HTMLDivElement>(null)
  const [svg, setSvg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const id = useId().replace(/:/g, "-")

  useEffect(() => {
    if (!raw) {
      setSvg(null)
      setError("空内容")
      return
    }
    setError(null)
    let cancelled = false
    const normalized = normalizeMermaidFromLLM(raw)

    const run = async () => {
      try {
        const mermaid = (await import("mermaid")).default
        const config = {
          startOnLoad: false,
          // Disable HTML labels / click callbacks from untrusted LLM diagrams
          securityLevel: "strict" as const,
          theme: "base",
          themeVariables: {
            primaryColor: "#e0f2fe",
            primaryTextColor: "#0c4a6e",
            primaryBorderColor: "#0ea5e9",
            lineColor: "#64748b",
            secondaryColor: "#f1f5f9",
            tertiaryColor: "#f8fafc",
            background: "#fafafa",
            mainBkg: "#f1f5f9",
            nodeBorder: "#94a3b8",
            clusterBkg: "#e2e8f0",
            clusterBorder: "#94a3b8",
            titleColor: "#334155",
            edgeLabelBackground: "#f8fafc",
            nodeTextColor: "#1e293b",
            fontFamily: "ui-sans-serif, system-ui, sans-serif",
          },
        }
        mermaid.initialize(config as Parameters<typeof mermaid.initialize>[0])
        const uid = `mermaid-${id}-${Math.random().toString(36).slice(2, 9)}`
        const { svg: out } = await mermaid.render(uid, normalized)
        if (!cancelled) setSvg(sanitizeSvg(out))
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        if (!cancelled) {
          setError(msg)
          setSvg(null)
        }
      }
    }

    run()
    return () => {
      cancelled = true
    }
  }, [raw, id])

  if (!raw) {
    return (
      <div className={className}>
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
          Mermaid 内容为空
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={className}>
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
          图表解析失败：{error}
        </div>
        <pre className="mt-2 rounded-lg border border-line bg-surface-muted p-3 text-[12px] leading-5 text-content whitespace-pre-wrap overflow-x-auto">
          {raw}
        </pre>
      </div>
    )
  }

  if (!svg) {
    return (
      <div className={className}>
        <div className="rounded-lg border border-line bg-surface shadow-sm overflow-hidden p-6 flex items-center justify-center min-h-[120px]">
          <div className="animate-pulse text-[12px] text-content-muted">渲染中…</div>
        </div>
      </div>
    )
  }

  return (
    <div className={className}>
      <div
        className="relative rounded-xl border border-line/80 bg-gradient-to-br from-slate-50 to-white shadow-sm overflow-auto min-h-[140px]"
        ref={containerRef}
      >
        <div className="absolute right-3 top-3 z-10">
          <Button
            variant="outline"
            size="icon"
            className="h-8 w-8 rounded-lg bg-surface/95 shadow-sm border-line hover:bg-surface-muted hover:border-line-hover"
            onClick={() => setOpen(true)}
            aria-label="放大"
            title="放大"
          >
            <Maximize2 className="w-4 h-4 text-content" />
          </Button>
        </div>
        <div
          className="p-6 flex items-center justify-center [&_svg]:max-w-full [&_svg]:h-auto [&_svg]:drop-shadow-sm"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[min(96vw,72rem)] max-w-none max-h-[90vh] flex flex-col p-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50 flex-shrink-0 flex flex-row items-center justify-between gap-3">
            <DialogTitle>Mermaid 图表预览</DialogTitle>
            <Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="关闭" title="关闭">
              <X className="w-4 h-4" />
            </Button>
          </DialogHeader>
          <div className="p-6 overflow-auto flex-1 min-h-0 bg-gradient-to-br from-slate-50/80 to-white">
            <div
              className="p-8 [&_svg]:max-w-full [&_svg]:h-auto [&_svg]:drop-shadow-sm"
              dangerouslySetInnerHTML={{ __html: svg }}
            />
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
})
