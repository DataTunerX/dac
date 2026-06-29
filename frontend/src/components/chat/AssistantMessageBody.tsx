"use client"

import dynamic from "next/dynamic"
import { memo, useMemo } from "react"
import type { ChatProgressPayload } from "@/lib/api-types"
import { ChatMarkdown } from "@/components/markdown-chat"
import { stripModelLeakTags, stripModelLeakLines } from "@/lib/strip-model-leak-tags"
import { ChatMessage, EMPTY_PROGRESS } from "@/components/chat/chat-message-types"

const ThinkingProcess = dynamic(
  () =>
    import("@/components/chat/ThinkingProcess").then((m) => ({
      default: m.ThinkingProcess,
    })),
  { ssr: false }
)

export interface AssistantMessageBodyProps {
  readonly msg: ChatMessage
  readonly index: number
  readonly messagesLength: number
  readonly isStreaming: boolean
  readonly streamProgressList: readonly ChatProgressPayload[]
}

/** Renders one assistant message: progress list, thinking block, then answer. */
export const AssistantMessageBody = memo(function AssistantMessageBody({
  msg,
  index,
  messagesLength,
  isStreaming,
  streamProgressList,
}: AssistantMessageBodyProps) {
  const thinking = stripModelLeakTags((msg.reasoning_content ?? "").trim())
  const answer = stripModelLeakLines(stripModelLeakTags(msg.content ?? ""))
  const isLastMessage = index === messagesLength - 1
  const hasVisibleAnswer = answer.trim().length > 0
  const isThinkingNow = isLastMessage && isStreaming && !hasVisibleAnswer

  const progressList = useMemo<readonly ChatProgressPayload[]>(() => {
    if (!isLastMessage) return msg.progressList ?? EMPTY_PROGRESS
    if (msg.progressList && msg.progressList.length > 0) return msg.progressList
    if (streamProgressList.length > 0) return streamProgressList
    return EMPTY_PROGRESS
  }, [isLastMessage, msg.progressList, streamProgressList])

  const hasProgress = progressList.length > 0
  const showThinking = thinking.length > 0 || hasProgress || (isThinkingNow && isLastMessage)

  return (
    <>
      {showThinking ? (
        <ThinkingProcess
          content={thinking}
          isThinking={isThinkingNow}
          isLive={isLastMessage && isStreaming}
          progressList={progressList}
        />
      ) : null}
      <ChatMarkdown source={answer} isStreaming={isLastMessage && isStreaming} />
    </>
  )
})
