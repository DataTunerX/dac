"use client"

import { memo, useEffect, useMemo, useRef, useState } from "react"
import ReactECharts from "echarts-for-react"
import * as echarts from "echarts"
import { Maximize2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"

type ChartBlockProps = {
  value: string
  className?: string
}

function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n))
}

function isProbablyCompleteJson(raw: string) {
  const t = raw.trim()
  if (!t) return false
  return (t.startsWith("{") || t.startsWith("[")) && /[}\]]\s*$/.test(t)
}

function legendCount(option: unknown): number {
  if (!option || typeof option !== "object") return 0
  const legend = (option as Record<string, unknown>).legend
  const readDataLen = (x: unknown) => {
    if (!x || typeof x !== "object") return 0
    const data = (x as Record<string, unknown>).data
    return Array.isArray(data) ? data.length : 0
  }
  if (Array.isArray(legend)) return legend.reduce((sum, x) => sum + readDataLen(x), 0)
  return readDataLen(legend)
}

function normalizeEChartsOption(input: Record<string, unknown>) {
  const o = input as Record<string, any>
  const out: Record<string, any> = { ...o }

  const series = Array.isArray(o.series) ? o.series : o.series ? [o.series] : []
  const types = new Set(
    series
      .map((s: any) => (s && typeof s === "object" ? String(s.type || "") : ""))
      .filter(Boolean),
  )
  const isCartesian = ["line", "bar", "scatter", "candlestick", "boxplot"].some((t) =>
    types.has(t),
  )

  const looksLikeDefaultTop = (top: any) => {
    if (top == null) return true
    if (top === 0 || top === "0" || top === "0%") return true
    if (top === "top") return true
    if (typeof top === "number" && top <= 8) return true
    return false
  }

  const fixTitle = (t: any) => {
    if (!t || typeof t !== "object") return t
    const next = { ...t }
    if (next.left == null && next.right == null) next.left = "center"
    if (looksLikeDefaultTop(next.top)) next.top = 8
    if (next.textStyle == null) next.textStyle = {}
    return next
  }

  if (o.title) {
    out.title = Array.isArray(o.title) ? o.title.map(fixTitle) : fixTitle(o.title)
  }

  const fixLegend = (lg: any) => {
    if (!lg || typeof lg !== "object") return lg
    const next = { ...lg }
    const topLooksDefault = looksLikeDefaultTop(next.top)
    const titleObj = Array.isArray(out.title) ? out.title[0] : out.title
    if (topLooksDefault && next.bottom == null) {
      next.top = titleObj?.subtext ? 64 : 52
    }
    if (next.left == null && next.right == null) next.left = "center"
    if (next.itemGap == null) next.itemGap = 12
    if (next.padding == null) next.padding = [0, 8, 0, 8]
    const dataLen = Array.isArray(next.data) ? next.data.length : 0
    if (dataLen >= 8 && next.type == null) next.type = "scroll"
    return next
  }

  if (o.legend) {
    out.legend = Array.isArray(o.legend) ? o.legend.map(fixLegend) : fixLegend(o.legend)
  }

  if (isCartesian) {
    const hasGrid = o.grid != null
    const hasTitle = Boolean(out.title)
    const hasLegend = Boolean(out.legend)
    const titleObj = Array.isArray(out.title) ? out.title[0] : out.title
    const topBase = 12 + (hasTitle ? (titleObj?.subtext ? 60 : 46) : 0) + (hasLegend ? 54 : 0)

    if (!hasGrid) {
      out.grid = {
        top: clamp(topBase, 72, 180),
        left: "8%",
        right: "6%",
        bottom: "10%",
        containLabel: true,
      }
    } else if (o.grid && typeof o.grid === "object" && !Array.isArray(o.grid)) {
      out.grid = { ...o.grid }
      if (out.grid.containLabel == null) out.grid.containLabel = true
      if (out.grid.top == null) out.grid.top = clamp(topBase, 72, 180)
    }
  }

  return out
}

export const ChartBlock = memo(function ChartBlock({ value, className }: ChartBlockProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [inlineHeight, setInlineHeight] = useState(360)

  const raw = useMemo(() => (value ?? "").trim(), [value])
  const [option, setOption] = useState<Record<string, unknown> | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [isParsing, setIsParsing] = useState(false)

  useEffect(() => {
    const t = raw
    if (!t) {
      setIsParsing(false)
      setParseError("空配置")
      setOption(null)
      return
    }

    setIsParsing(true)
    setParseError(null)
    const timer = window.setTimeout(() => {
      try {
        const next = JSON.parse(t) as Record<string, unknown>
        setOption(next)
        setParseError(null)
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        if (isProbablyCompleteJson(t)) setParseError(msg)
      } finally {
        setIsParsing(false)
      }
    }, 300)

    return () => window.clearTimeout(timer)
  }, [raw])

  const normalizedOption = useMemo(() => (option ? normalizeEChartsOption(option) : null), [option])

  useEffect(() => {
    if (!normalizedOption) return
    const el = containerRef.current
    if (!el) return

    const lc = legendCount(normalizedOption)
    const extra = lc >= 10 ? 160 : lc >= 7 ? 120 : lc >= 4 ? 80 : 0

    const calc = () => {
      const w = el.clientWidth || 0
      const base = clamp(Math.round(w * 0.55), 320, 560)
      setInlineHeight(clamp(base + extra, 320, 820))
    }

    calc()
    const ro = new ResizeObserver(() => calc())
    ro.observe(el)
    return () => ro.disconnect()
  }, [normalizedOption])

  if (!raw || !normalizedOption) {
    return (
      <div className={className}>
        <div className="rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="p-4">
            <div className="h-[12px] w-40 rounded bg-slate-100 animate-pulse" />
            <div className="mt-3 h-[10px] w-64 rounded bg-slate-100 animate-pulse" />
            <div className="mt-4 h-[240px] rounded bg-slate-50 border border-slate-100 animate-pulse" />
            <div className="mt-3 text-[12px] text-slate-500">
              {raw && parseError ? `图表配置解析失败：${parseError}` : isParsing ? "图表生成中…" : "图表生成中…"}
            </div>
          </div>
          {raw && parseError && isProbablyCompleteJson(raw) ? (
            <pre className="border-t border-slate-200 bg-slate-50 p-3 text-[12px] leading-5 text-slate-700 whitespace-pre-wrap">
              {raw}
            </pre>
          ) : null}
        </div>
      </div>
    )
  }

  return (
    <div className={className}>
      <div
        ref={containerRef}
        className="relative rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden"
      >
        <div className="absolute right-2 top-2 z-10">
          <Button
            variant="outline"
            size="icon"
            className="h-7 w-7 bg-white/90 backdrop-blur"
            onClick={() => setOpen(true)}
            aria-label="放大"
            title="放大"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </Button>
        </div>
        <ReactECharts
          echarts={echarts}
          option={normalizedOption}
          notMerge={true}
          lazyUpdate={true}
          style={{ width: "100%", height: inlineHeight }}
        />
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[min(96vw,72rem)] max-w-none max-h-[90vh]">
          <DialogHeader className="flex flex-row items-center justify-between gap-3">
            <DialogTitle>图表预览</DialogTitle>
            <Button variant="ghost" size="icon" onClick={() => setOpen(false)} aria-label="关闭">
              <X className="w-4 h-4" />
            </Button>
          </DialogHeader>
          <div className="px-6 pb-6 pt-4">
            <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
              <ReactECharts
                echarts={echarts}
                option={normalizedOption}
                notMerge={true}
                lazyUpdate={true}
                style={{ width: "100%", height: "70vh" }}
              />
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
})

