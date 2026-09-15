"use client"

import dynamic from "next/dynamic"
import { memo, useMemo } from "react"
import type { ChatProgressPayload } from "@/lib/api-types"
import { ChatMarkdown } from "@/components/markdown-chat"
import { stripModelLeakTags, stripModelLeakLines, stripDacProtocolLines } from "@/lib/strip-model-leak-tags"
import { ChatMessage, EMPTY_PROGRESS } from "@/components/chat/chat-message-types"
import { EMPTY_EXECUTION_FLOW, type ExecutionFlowTask } from "@/lib/execution-flow"

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
  readonly streamExecutionFlowList?: readonly ExecutionFlowTask[]
  readonly streamStartedAt?: number | null
  readonly thinkingElapsedSec?: number | null
}

/** Renders one assistant message: progress list, thinking block, then answer. */
export const AssistantMessageBody = memo(function AssistantMessageBody({
  msg,
  index,
  messagesLength,
  isStreaming,
  streamProgressList,
  streamExecutionFlowList = EMPTY_EXECUTION_FLOW,
  streamStartedAt,
  thinkingElapsedSec,
}: AssistantMessageBodyProps) {
  const thinking = stripDacProtocolLines(stripModelLeakTags((msg.reasoning_content ?? "").trim()))
  const answer = stripDacProtocolLines(stripModelLeakLines(stripModelLeakTags(msg.content ?? "")))
  const isLastMessage = index === messagesLength - 1
  const hasVisibleAnswer = answer.trim().length > 0
  const isThinkingNow = isLastMessage && isStreaming && !hasVisibleAnswer

  const progressList = useMemo<readonly ChatProgressPayload[]>(() => {
    if (!isLastMessage) return msg.progressList ?? EMPTY_PROGRESS
    if (msg.progressList && msg.progressList.length > 0) return msg.progressList
    if (streamProgressList.length > 0) return streamProgressList
    return EMPTY_PROGRESS
  }, [isLastMessage, msg.progressList, streamProgressList])

  const executionFlowList = useMemo<readonly ExecutionFlowTask[]>(() => {
    // Historical messages use frozen executionFlowList; the live last message
    // prefers frozen data if present, otherwise the in-flight stream list.
    if (!isLastMessage) return msg.executionFlowList ?? EMPTY_EXECUTION_FLOW
    if (msg.executionFlowList && msg.executionFlowList.length > 0) return msg.executionFlowList
    if (streamExecutionFlowList.length > 0) return streamExecutionFlowList
    return EMPTY_EXECUTION_FLOW
  }, [isLastMessage, msg.executionFlowList, streamExecutionFlowList])

  const hasProgress = progressList.length > 0
  const hasExecutionFlow = executionFlowList.length > 0
  const showThinking = thinking.length > 0 || hasProgress || hasExecutionFlow || (isThinkingNow && isLastMessage)

  return (
    <>
      {showThinking ? (
        <ThinkingProcess
          content={thinking}
          isThinking={isThinkingNow}
          isLive={isLastMessage && isStreaming}
          progressList={progressList}
          executionFlowList={executionFlowList}
          startedAt={isLastMessage ? streamStartedAt : undefined}
          elapsedSec={isLastMessage ? thinkingElapsedSec : undefined}
        />
      ) : null}
      <ChatMarkdown source={answer} isStreaming={isLastMessage && isStreaming} />
    </>
  )
})
