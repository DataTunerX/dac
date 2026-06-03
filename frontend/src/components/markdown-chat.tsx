"use client"

import React, { memo, useEffect, useMemo, useState } from "react"
import type { HTMLAttributes, ReactNode } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import nextDynamic from "next/dynamic"
import { Check, Copy } from "lucide-react"
import { toast } from "sonner"
import { prepareMarkdown } from "@/lib/prepare-markdown"
import { defaultMarkdownComponents } from "@/components/markdown"

const ChartBlock = nextDynamic(
  () => import("@/components/chart-block/index").then((m) => ({ default: m.ChartBlock })),
  { ssr: false }
)
const MermaidBlock = nextDynamic(
  () => import("@/components/mermaid-block/index").then((m) => ({ default: m.MermaidBlock })),
  { ssr: false }
)

type MarkdownCodeProps = HTMLAttributes<HTMLElement> & {
  inline?: boolean
  className?: string
  children?: ReactNode
}

async function copyToClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const ta = document.createElement("textarea")
  ta.value = text
  ta.style.position = "fixed"
  ta.style.left = "-9999px"
  document.body.appendChild(ta)
  ta.select()
  document.execCommand("copy")
  document.body.removeChild(ta)
}

function CodeBlock({ language, children }: { language: string; children: string }) {
  const [copied, setCopied] = useState(false)
  const [Highlighter, setHighlighter] = useState<typeof import("react-syntax-highlighter").Prism | null>(null)
  const [highlightStyle, setHighlightStyle] = useState<Record<string, React.CSSProperties> | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      import("react-syntax-highlighter").then((m) => m.Prism),
      import("react-syntax-highlighter/dist/esm/styles/prism").then((m) => m.vscDarkPlus),
    ])
      .then(([Prism, vscDarkPlus]) => {
        if (!cancelled) {
          setHighlighter(() => Prism)
          setHighlightStyle(vscDarkPlus)
        }
      })
      .catch(() => {
        if (!cancelled) setHighlightStyle({})
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleCopy = async () => {
    try {
      await copyToClipboard(children)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (e) {
      console.error("Copy code block failed", e)
      toast.error("复制失败（浏览器限制）")
    }
  }

  return (
    <div className="rounded-lg overflow-hidden my-3 border border-slate-700 bg-[#1e1e1e] shadow-sm group">
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#252526] border-b border-slate-700 text-xs text-content-muted select-none">
        <span className="font-mono">{language || "text"}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1.5 hover:text-content-inverse transition-colors cursor-pointer"
          aria-label={copied ? "已复制" : "复制代码"}
        >
          {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      {Highlighter && highlightStyle ? (
        <Highlighter
          language={language}
          style={highlightStyle}
          customStyle={{ margin: 0, padding: "1rem", fontSize: "0.875rem", lineHeight: "1.5" }}
          wrapLines
          wrapLongLines
        >
          {children}
        </Highlighter>
      ) : (
        <pre className="m-0 p-4 text-sm leading-relaxed overflow-x-auto">
          <code>{children}</code>
        </pre>
      )}
    </div>
  )
}

const chatMarkdownComponents = {
  ...defaultMarkdownComponents,
  code({ inline, className, children, ...props }: MarkdownCodeProps) {
    const match = /language-(\w+)/.exec(className || "")
    const language = match?.[1] || ""
    const raw = String(children).replace(/\n$/, "")

    if (!inline && language === "chart") {
      return <ChartBlock value={raw} className="my-3" />
    }
    if (!inline && language === "mermaid") {
      return <MermaidBlock value={raw} className="my-3" />
    }

    return !inline && match ? (
      <CodeBlock language={language}>{raw}</CodeBlock>
    ) : (
      <code
        className="bg-surface-muted px-1 py-0.5 rounded text-[12px] font-mono text-content border border-line"
        {...props}
      >
        {children}
      </code>
    )
  },
  a({ href, children }: { href?: string; children?: ReactNode }) {
    const isExternal = href?.startsWith("http")
    return (
      <a
        href={href}
        className="text-cta hover:text-cta/90 underline cursor-pointer transition-colors"
        target={isExternal ? "_blank" : undefined}
        rel={isExternal ? "noopener noreferrer" : undefined}
      >
        {children}
      </a>
    )
  },
}

const REMARK_GFM_ONLY = [remarkGfm]
const REMARK_GFM_MATH = [remarkGfm, remarkMath]
const REHYPE_KATEX = [rehypeKatex]
/** Stable empty list for ReactMarkdown when KaTeX is skipped. */
const REHYPE_NONE: [] = []

const MATH_DELIMITER_RE = /\\[\[\(]|\$\$?/

export function normalizeMathDelimiters(input: string) {
  return input
    .replaceAll("\\[", "$$")
    .replaceAll("\\]", "$$")
    .replaceAll("\\(", "$")
    .replaceAll("\\)", "$")
}

/**
 * Chat / history assistant answers: one entry for prepare + render.
 * `prepareMarkdown` runs before remark-gfm so tables and fences parse reliably.
 */
export const ChatMarkdown = memo(function ChatMarkdown({
  source,
  isStreaming = false,
}: {
  source: string
  /** When true, skip KaTeX until stream ends (perf during token updates). */
  isStreaming?: boolean
}) {
  const needsMath = useMemo(() => !isStreaming && MATH_DELIMITER_RE.test(source), [source, isStreaming])
  const markdown = useMemo(
    () => prepareMarkdown(normalizeMathDelimiters(source)),
    [source]
  )
  const remarkPlugins = useMemo(
    () => (needsMath ? REMARK_GFM_MATH : REMARK_GFM_ONLY),
    [needsMath]
  )
  const rehypePlugins = useMemo(
    () => (needsMath ? REHYPE_KATEX : REHYPE_NONE),
    [needsMath]
  )

  return (
    <div className="min-w-0 overflow-hidden [content-visibility:auto]">
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={chatMarkdownComponents}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  )
})
