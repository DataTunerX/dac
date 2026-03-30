"use client"

import { useRef, useCallback } from "react"
import { ArrowUp, StopCircle } from "lucide-react"

const MAX_HEIGHT = 160

type ChatInputProps = {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop: () => void
  isLoading: boolean
  isStreaming: boolean
}

export function ChatInput({
  value,
  onChange,
  onSend,
  onStop,
  isLoading,
  isStreaming,
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const syncHeight = useCallback((el: HTMLTextAreaElement | null) => {
    if (el) {
      el.style.height = "auto"
      el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
    }
  }, [])

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange(e.target.value)
    requestAnimationFrame(() => syncHeight(e.target))
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }

  return (
    <div className="relative bg-surface rounded-2xl shadow-sm border border-line transition-all focus-within:border-line-hover focus-within:shadow-md">
      <textarea
        ref={(el) => {
          textareaRef.current = el
          syncHeight(el)
        }}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={isLoading ? "正在思考中…" : "给 DAC 发送消息"}
        className="w-full min-h-[48px] max-h-[160px] border-0 focus:ring-0 resize-none bg-transparent text-[15px] placeholder:text-content-muted px-4 pt-3 pb-1 focus-visible:outline-none disabled:opacity-60 disabled:cursor-not-allowed transition-all"
        disabled={isLoading}
        rows={1}
        style={{ height: "auto", minHeight: "48px" }}
      />
      <div className="flex items-center justify-end px-4 pb-3 gap-2">
        {isStreaming ? (
          <button
            type="button"
            onClick={onStop}
            className="min-w-[44px] min-h-[44px] h-10 w-10 rounded-full bg-surface-muted text-content hover:bg-surface-active transition-colors inline-flex items-center justify-center cursor-pointer touch-manipulation"
            aria-label="停止生成"
            title="停止生成"
          >
            <StopCircle className="w-5 h-5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={onSend}
            disabled={!value.trim()}
            className="min-w-[44px] min-h-[44px] h-10 w-10 rounded-full bg-btn-primary text-content-inverse hover:bg-btn-primary-hover disabled:bg-surface-active disabled:text-content-muted transition-colors inline-flex items-center justify-center cursor-pointer disabled:cursor-not-allowed touch-manipulation"
            aria-label="发送"
            title="发送"
          >
            <ArrowUp className="w-5 h-5" />
          </button>
        )}
      </div>
    </div>
  )
}
