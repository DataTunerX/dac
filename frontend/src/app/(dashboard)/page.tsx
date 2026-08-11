"use client"

// Next.js requires useSearchParams() to be wrapped in Suspense.
// We make this page dynamic to avoid prerender failures in production builds.
export const dynamic = "force-dynamic"

import { useState, useRef, useEffect, useCallback, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useShallow } from "zustand/react/shallow"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { ArrowDown, Copy, Loader2, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { REFRESH_CHAT_LIST_EVENT, RUN_ID_RECONCILED_EVENT, type NewChatEventDetail, type RunIdReconciledDetail } from "@/lib/events"
import { cn } from "@/lib/utils"
import { ChatInput } from "@/components/chat/ChatInput"
import { AssistantMessageBody } from "@/components/chat/AssistantMessageBody"
import { EMPTY_PROGRESS } from "@/components/chat/chat-message-types"
import { stripModelLeakTags } from "@/lib/strip-model-leak-tags"
import {
  EMPTY_SESSION_STATE,
  markOptimisticRunId,
  safeDispatchEvent,
  safeLocalStorageSet,
  safeUUID,
  clearOptimisticRunId,
  shouldLoadHistoryForRunId,
  useChatStore,
} from "@/lib/chat-store"

async function copyToClipboard(text: string) {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && typeof window !== "undefined" && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return
    }
  } catch {
    // fall through to legacy fallback
  }

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

function ChatContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const runId = searchParams.get("run_id")

  const [draftInput, setDraftInput] = useState("")
  const ensure = useChatStore((s) => s.ensure)
  const setStoreInput = useChatStore((s) => s.setInput)
  const send = useChatStore((s) => s.send)
  const stop = useChatStore((s) => s.stop)
  const loadHistory = useChatStore((s) => s.loadHistory)
  const regenerate = useChatStore((s) => s.regenerate)
  const startNew = useChatStore((s) => s.startNew)

  const { messages, storeInput, isLoading, isStreaming, streamProgressList, streamStartedAt, thinkingElapsedSec } = useChatStore(
    useShallow((state) => {
      const session = runId ? state.sessions[runId] : undefined
      return {
        runId,
        messages: session?.messages ?? EMPTY_SESSION_STATE.messages,
        storeInput: session?.input ?? "",
        isLoading: session?.isLoading ?? false,
        isStreaming: session?.isStreaming ?? false,
        streamProgressList: session?.streamProgressList ?? EMPTY_SESSION_STATE.streamProgressList,
        streamStartedAt: session?.streamStartedAt ?? EMPTY_SESSION_STATE.streamStartedAt,
        thinkingElapsedSec: session?.thinkingElapsedSec ?? EMPTY_SESSION_STATE.thinkingElapsedSec,
      }
    })
  )
  const input = runId ? storeInput : draftInput

  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const autoScrollRef = useRef(true)
  const lastScrollTopRef = useRef(0)
  const [showJumpToBottom, setShowJumpToBottom] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const activeRunIdRef = useRef<string | null>(null)

  useEffect(() => {
    activeRunIdRef.current = runId
  }, [runId])

  // Load history when navigating to a conversation (does not abort other sessions' streams).
  useEffect(() => {
    if (!runId) {
      setHistoryLoading(false)
      return
    }
    ensure(runId)

    const cached = useChatStore.getState().sessions[runId]
    if (cached?.messages.length && !cached.isStreaming) {
      setHistoryLoading(false)
      return
    }
    if (!shouldLoadHistoryForRunId(runId)) {
      setHistoryLoading(false)
      return
    }

    let cancelled = false
    setHistoryLoading(true)
    void loadHistory(runId).then((result) => {
      if (cancelled) return
      setHistoryLoading(false)
      if (activeRunIdRef.current !== runId) return
      if (result === "not_found") {
        router.replace("/")
      }
    })

    return () => {
      cancelled = true
      setHistoryLoading(false)
    }
  }, [runId, ensure, loadHistory, router])

  // Sync URL when backend reconciles optimistic run_id.
  useEffect(() => {
    const onReconciled = (e: Event) => {
      if (!(e instanceof CustomEvent)) return
      const { oldId, newId } = e.detail as RunIdReconciledDetail
      if (activeRunIdRef.current !== oldId) return
      router.replace(`/?run_id=${encodeURIComponent(newId)}`)
    }
    window.addEventListener(RUN_ID_RECONCILED_EVENT, onReconciled)
    return () => window.removeEventListener(RUN_ID_RECONCILED_EVENT, onReconciled)
  }, [router])

  const setInput = useCallback(
    (value: string) => {
      if (runId) {
        ensure(runId)
        setStoreInput(runId, value)
      } else {
        setDraftInput(value)
      }
    },
    [runId, ensure, setStoreInput]
  )

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior })
    lastScrollTopRef.current = el.scrollTop
  }, [])

  const resumeAutoScroll = useCallback(
    (behavior: ScrollBehavior = "auto") => {
      autoScrollRef.current = true
      setShowJumpToBottom(false)
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          scrollToBottom(behavior)
        })
      })
    },
    [scrollToBottom]
  )

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    const THRESHOLD_PX = 64
    lastScrollTopRef.current = el.scrollTop

    const syncJumpButton = () => {
      const distanceToBottom = el.scrollHeight - (el.scrollTop + el.clientHeight)
      const isNearBottom = distanceToBottom <= THRESHOLD_PX
      if (isNearBottom) {
        autoScrollRef.current = true
        setShowJumpToBottom(false)
      }
    }

    const onScroll = () => {
      const scrollingUp = el.scrollTop < lastScrollTopRef.current - 2
      lastScrollTopRef.current = el.scrollTop
      if (scrollingUp) {
        autoScrollRef.current = false
        setShowJumpToBottom(true)
        return
      }
      syncJumpButton()
    }

    syncJumpButton()
    el.addEventListener("scroll", onScroll, { passive: true })

    return () => {
      el.removeEventListener("scroll", onScroll)
    }
  }, [runId])

  // Follow stream output: message text, progress cards, and layout growth (markdown/thinking).
  const lastMessage = messages[messages.length - 1]
  const scrollContentKey =
    (lastMessage?.content?.length ?? 0) +
    (lastMessage?.reasoning_content?.length ?? 0) +
    streamProgressList.length

  useEffect(() => {
    if (!autoScrollRef.current) return
    const behavior = isStreaming ? "auto" : "smooth"
    let rafId2: number | undefined
    const rafId1 = window.requestAnimationFrame(() => {
      rafId2 = window.requestAnimationFrame(() => {
        if (!autoScrollRef.current) return
        scrollToBottom(behavior)
      })
    })
    return () => {
      window.cancelAnimationFrame(rafId1)
      if (typeof rafId2 === "number") window.cancelAnimationFrame(rafId2)
    }
  }, [scrollContentKey, isStreaming, scrollToBottom])

  // Catch DOM height changes that do not go through store (markdown layout, thinking panel).
  useEffect(() => {
    const content = contentRef.current
    if (!content || !isStreaming) return

    const ro = new ResizeObserver(() => {
      if (!autoScrollRef.current) return
      scrollToBottom("auto")
    })
    ro.observe(content)
    return () => ro.disconnect()
  }, [runId, isStreaming, scrollToBottom])

  // New-chat transition hides the list until run_id is set; re-enable follow once visible.
  useEffect(() => {
    if (!runId || !isStreaming) return
    resumeAutoScroll("auto")
  }, [runId, isStreaming, resumeAutoScroll])

  const handleRegenerate = async () => {
    if (!runId || isLoading || messages.length === 0) return
    resumeAutoScroll("auto")
    await regenerate(runId)
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || historyLoading) return

    resumeAutoScroll("auto")

    if (!runId) {
      const newRunId = safeUUID()
      markOptimisticRunId(newRunId)

      const title = text.slice(0, 30) || "New Chat"
      safeLocalStorageSet(`dac_title_${newRunId}`, title)
      setDraftInput("")

      try {
        const streamPromise = startNew(newRunId, text)
        router.replace(`/?run_id=${encodeURIComponent(newRunId)}`)

        safeDispatchEvent(
          new CustomEvent<NewChatEventDetail>(REFRESH_CHAT_LIST_EVENT, {
            detail: {
              id: newRunId,
              title,
              created_at: new Date().toISOString(),
            },
          })
        )

        await streamPromise
      } catch (error) {
        console.error("Failed to start new chat", error)
        clearOptimisticRunId(newRunId)
        useChatStore.getState().remove(newRunId)
        router.replace("/")
        toast.error("无法开始新对话")
      }
      return
    }

    ensure(runId)
    await send(runId)
  }

  const handleStop = () => {
    if (runId) stop(runId)
  }

  const isNewChat = !runId
  const showConversationLoading = Boolean(runId) && messages.length === 0 && (historyLoading || isLoading)
  const showEmptyConversation = Boolean(runId) && messages.length === 0 && !isLoading && !historyLoading

  return (
    <div className="h-full flex flex-col relative bg-surface">
      <div className={`flex-1 overflow-hidden relative ${isNewChat ? "hidden" : "block"}`}>
        <ScrollArea ref={scrollRef} className="h-full px-4 py-8 md:px-10 bg-surface">
          <div ref={contentRef} className="space-y-8 pb-6 max-w-4xl mx-auto">
            {showConversationLoading ? (
              <div className="flex items-center justify-center py-16 text-content-muted">
                <Loader2 className="h-5 w-5 animate-spin mr-2" />
                <span className="text-sm">{historyLoading ? "加载对话中…" : "正在连接…"}</span>
              </div>
            ) : null}
            {showEmptyConversation ? (
              <div className="flex items-center justify-center py-16 text-sm text-content-muted">
                暂无消息，在下方输入开始对话
              </div>
            ) : null}
            {messages.map((msg, index) => (
              <div
                key={msg.id ?? index}
                className={`flex [content-visibility:auto] ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={cn(
                    "flex flex-col min-w-0",
                    msg.role === "user"
                      ? "max-w-[92%] md:max-w-[78%] items-end"
                      : "w-full items-start"
                  )}
                >
                  <div
                    className={
                      msg.role === "user"
                        ? "px-5 py-3 rounded-2xl bg-cta/10 text-content text-base leading-7"
                        : "text-content w-full min-w-0 overflow-hidden text-base"
                    }
                  >
                    {msg.role === "user" ? (
                      msg.content
                    ) : (
                      <>
                        <AssistantMessageBody
                          msg={msg}
                          index={index}
                          messagesLength={messages.length}
                          isStreaming={
                            isStreaming &&
                            index === messages.length - 1 &&
                            msg.role === "assistant"
                          }
                          streamProgressList={
                            index === messages.length - 1 ? streamProgressList : EMPTY_PROGRESS
                          }
                          streamStartedAt={index === messages.length - 1 ? streamStartedAt : undefined}
                          thinkingElapsedSec={index === messages.length - 1 ? thinkingElapsedSec : undefined}
                        />
                        <div className="flex items-center gap-2 mt-3">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 text-content-muted hover:text-content hover:bg-surface-muted rounded-md"
                            onClick={async () => {
                              try {
                                await copyToClipboard(stripModelLeakTags(msg.content || ""))
                                toast.success("已复制到剪贴板")
                              } catch (e) {
                                console.error("Copy failed", e)
                                toast.error("复制失败（浏览器限制）")
                              }
                            }}
                            title="复制内容"
                            aria-label="复制内容"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                          {index === messages.length - 1 && !isLoading && (
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6 text-content-muted hover:text-content hover:bg-surface-muted rounded-md"
                              onClick={handleRegenerate}
                              title="重新生成"
                              aria-label="重新生成"
                            >
                              <RefreshCw className="w-3.5 h-3.5" />
                            </Button>
                          )}
                        </div>
                      </>
                    )}
                  </div>

                  {msg.role === "user" && (
                    <div className="flex items-center gap-2 mt-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 text-content-muted hover:text-content hover:bg-surface-muted rounded-md"
                        onClick={async () => {
                          try {
                            await copyToClipboard(msg.content || "")
                            toast.success("已复制到剪贴板")
                          } catch (e) {
                            console.error("Copy failed", e)
                            toast.error("复制失败（浏览器限制）")
                          }
                        }}
                        title="复制内容"
                        aria-label="复制内容"
                      >
                        <Copy className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>

        {showJumpToBottom && (
          <div className="absolute left-1/2 -translate-x-1/2 bottom-6 z-10">
            <button
              type="button"
              onClick={() => {
                autoScrollRef.current = true
                setShowJumpToBottom(false)
                scrollToBottom("smooth")
              }}
              className="min-h-[44px] h-10 px-4 py-2 rounded-full bg-surface/90 backdrop-blur border border-line shadow-sm text-content hover:bg-surface hover:shadow transition flex items-center gap-2 cursor-pointer touch-manipulation"
              aria-label="回到底部"
              title="回到底部"
            >
              <ArrowDown className="w-4 h-4" />
              <span className="text-sm">回到底部</span>
            </button>
          </div>
        )}
      </div>

      {isNewChat && (
        <div className="flex-1 flex flex-col items-center justify-center p-4 sm:-mt-20">
          <div className="flex items-center gap-3 mb-8">
            <div
              className="w-10 h-10 bg-surface border border-line shadow-sm rounded-xl flex items-center justify-center text-cta font-bold text-xl"
              aria-hidden="true"
            >
              D
            </div>
            <h1 className="text-2xl font-semibold text-content">今天有什么可以帮到你？</h1>
          </div>

          <div className="w-full px-4 md:px-10">
            <div className="max-w-4xl mx-auto">
              <ChatInput
                value={input}
                onChange={setInput}
                onSend={handleSend}
                onStop={handleStop}
                isLoading={isLoading || historyLoading}
                isStreaming={isStreaming}
              />
            </div>
          </div>
        </div>
      )}

      {!isNewChat && (
        <div className="w-full px-4 md:px-10 py-6 bg-transparent">
          <div className="max-w-4xl mx-auto">
            <ChatInput
              value={input}
              onChange={setInput}
              onSend={handleSend}
              onStop={handleStop}
              isLoading={isLoading || historyLoading}
              isStreaming={isStreaming}
            />
            <div className="text-center mt-3 text-xs text-content-muted">内容由 AI 生成，请仔细甄别</div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-content-muted" />
        </div>
      }
    >
      <ChatContent />
    </Suspense>
  )
}
