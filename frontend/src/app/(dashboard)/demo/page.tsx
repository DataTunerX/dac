"use client"

import Link from "next/link"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Circle,
  ExternalLink,
  Loader2,
  MessageSquare,
  Pause,
  Play,
  RotateCcw,
  SkipForward,
} from "lucide-react"
import { AssistantMessageBody } from "@/components/chat/AssistantMessageBody"
import { EMPTY_PROGRESS } from "@/components/chat/chat-message-types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { PageContainer } from "@/components/ui/page-container"
import { PageHeader } from "@/components/ui/page-header"
import {
  clearOptimisticRunId,
  markOptimisticRunId,
  safeDispatchEvent,
  safeLocalStorageSet,
  safeUUID,
  useChatStore,
} from "@/lib/chat-store"
import {
  REFRESH_CHAT_LIST_EVENT,
  RUN_ID_RECONCILED_EVENT,
  type NewChatEventDetail,
  type RunIdReconciledDetail,
} from "@/lib/events"
import {
  DEMO_SCENARIOS,
  DEMO_STEPS,
  getScenarioForStep,
  type DemoScenarioStatus,
  type DemoStep,
} from "@/lib/demo-scenarios"
import { cn } from "@/lib/utils"

type ResultStatus = "review" | "handoff" | "blocked" | "failed"

interface StepResult {
  status: ResultStatus
  finishedAt: string
  runId?: string
  note?: string
}

interface PersistedDemoState {
  version: 1
  cursor: number
  results: Record<string, StepResult>
}

const STORAGE_KEY = "dac_guided_demo_v1"

const EMPTY_SESSION = {
  messages: [],
  input: "",
  isLoading: false,
  isStreaming: false,
  streamProgressList: [],
  streamStartedAt: null,
  thinkingElapsedSec: null,
} as const

function scenarioStatusLabel(status: DemoScenarioStatus) {
  if (status === "ready") return "可运行"
  if (status === "partial") return "部分就绪"
  return "阻塞"
}

function resultLabel(status: ResultStatus) {
  if (status === "review") return "待验收"
  if (status === "handoff") return "人工步骤"
  if (status === "blocked") return "已记录阻塞"
  return "运行失败"
}

function parseStoredState(raw: string | null): PersistedDemoState | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<PersistedDemoState>
    if (parsed.version !== 1 || typeof parsed.cursor !== "number" || !parsed.results || typeof parsed.results !== "object") {
      return null
    }
    return {
      version: 1,
      cursor: Math.max(0, Math.min(DEMO_STEPS.length, Math.floor(parsed.cursor))),
      results: parsed.results as Record<string, StepResult>,
    }
  } catch {
    return null
  }
}

function PlanStepIcon({ result, active }: { result?: StepResult; active: boolean }) {
  if (result?.status === "review" || result?.status === "handoff") {
    return <CheckCircle2 className="h-4 w-4 text-success" aria-hidden />
  }
  if (result?.status === "blocked" || result?.status === "failed") {
    return <AlertTriangle className="h-4 w-4 text-warning" aria-hidden />
  }
  if (active) return <Play className="h-4 w-4 text-brand" aria-hidden />
  return <Circle className="h-4 w-4 text-content-muted/50" aria-hidden />
}

function StepTypeBadge({ step }: { step: DemoStep }) {
  if (step.kind === "chat") return <Badge variant="outline">自动查询</Badge>
  if (step.kind === "navigate") return <Badge variant="outline">控制台操作</Badge>
  return <Badge variant="secondary">环境阻塞</Badge>
}

export default function GuidedDemoPage() {
  const [cursor, setCursor] = useState(0)
  const [results, setResults] = useState<Record<string, StepResult>>({})
  const [promptDrafts, setPromptDrafts] = useState<Record<string, string>>({})
  const [hydrated, setHydrated] = useState(false)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [runningStepId, setRunningStepId] = useState<string | null>(null)
  const activeRunIdRef = useRef<string | null>(null)

  const startNew = useChatStore((state) => state.startNew)
  const stop = useChatStore((state) => state.stop)
  const remove = useChatStore((state) => state.remove)
  const activeSession = useChatStore((state) =>
    activeRunId ? state.sessions[activeRunId] : undefined
  ) ?? EMPTY_SESSION

  const currentStep = DEMO_STEPS[cursor]
  const currentScenario = currentStep ? getScenarioForStep(currentStep) : null
  const completedCount = Object.keys(results).filter((id) => DEMO_STEPS.some((step) => step.id === id)).length
  const progressPercent = Math.round((completedCount / DEMO_STEPS.length) * 100)

  useEffect(() => {
    const saved = parseStoredState(window.localStorage.getItem(STORAGE_KEY))
    if (saved) {
      setCursor(saved.cursor)
      setResults(saved.results)
      const latestRun = [...DEMO_STEPS]
        .reverse()
        .map((step) => saved.results[step.id]?.runId)
        .find(Boolean)
      if (latestRun) setActiveRunId(latestRun)
    }
    setHydrated(true)
  }, [])

  useEffect(() => {
    if (!hydrated) return
    const state: PersistedDemoState = { version: 1, cursor, results }
    safeLocalStorageSet(STORAGE_KEY, JSON.stringify(state))
  }, [cursor, hydrated, results])

  useEffect(() => {
    const onReconciled = (event: Event) => {
      if (!(event instanceof CustomEvent)) return
      const { oldId, newId } = event.detail as RunIdReconciledDetail
      if (activeRunIdRef.current !== oldId) return
      activeRunIdRef.current = newId
      setActiveRunId(newId)
    }
    window.addEventListener(RUN_ID_RECONCILED_EVENT, onReconciled)
    return () => window.removeEventListener(RUN_ID_RECONCILED_EVENT, onReconciled)
  }, [])

  const finishStep = useCallback((step: DemoStep, result: StepResult) => {
    setResults((previous) => ({ ...previous, [step.id]: result }))
    setCursor((previous) => {
      const stepIndex = DEMO_STEPS.findIndex((item) => item.id === step.id)
      return previous === stepIndex ? Math.min(stepIndex + 1, DEMO_STEPS.length) : previous
    })
  }, [])

  const runChatStep = useCallback(async (step: DemoStep, prompt: string) => {
    if (!prompt.trim()) return
    const optimisticRunId = safeUUID()
    const title = `[测试] ${step.title}`.slice(0, 30)
    activeRunIdRef.current = optimisticRunId
    setActiveRunId(optimisticRunId)
    setRunningStepId(step.id)
    markOptimisticRunId(optimisticRunId)
    safeLocalStorageSet(`dac_title_${optimisticRunId}`, title)
    safeDispatchEvent(
      new CustomEvent<NewChatEventDetail>(REFRESH_CHAT_LIST_EVENT, {
        detail: { id: optimisticRunId, title, created_at: new Date().toISOString() },
      })
    )

    try {
      await startNew(optimisticRunId, prompt.trim())
      const resolvedRunId = activeRunIdRef.current ?? optimisticRunId
      const session = useChatStore.getState().sessions[resolvedRunId]
      const hasAssistantOutput = session?.messages.some(
        (message) => message.role === "assistant" && message.content.trim().length > 0
      )
      finishStep(step, {
        status: hasAssistantOutput ? "review" : "failed",
        finishedAt: new Date().toISOString(),
        runId: resolvedRunId,
        note: hasAssistantOutput
          ? "查询已完成，请按本步骤的验收要点人工确认。"
          : "查询结束但没有可见的助手答案。",
      })
    } catch (error) {
      clearOptimisticRunId(optimisticRunId)
      remove(activeRunIdRef.current ?? optimisticRunId)
      finishStep(step, {
        status: "failed",
        finishedAt: new Date().toISOString(),
        note: error instanceof Error ? error.message : "无法开始测试查询。",
      })
    } finally {
      setRunningStepId(null)
    }
  }, [finishStep, remove, startNew])

  const handleNext = useCallback(async () => {
    if (!currentStep || runningStepId) return
    if (currentStep.kind === "chat") {
      await runChatStep(currentStep, promptDrafts[currentStep.id] ?? currentStep.prompt ?? "")
      return
    }
    if (currentStep.kind === "navigate") {
      const opened = currentStep.href ? window.open(currentStep.href, "_blank") : null
      if (opened) opened.opener = null
      finishStep(currentStep, {
        status: opened ? "handoff" : "failed",
        finishedAt: new Date().toISOString(),
        note: opened
          ? "控制台已在新标签页打开；完成所列操作后回到本页继续。"
          : "浏览器阻止了新标签页，请允许弹出窗口后重试或使用页面内链接。",
      })
      return
    }
    finishStep(currentStep, {
      status: "blocked",
      finishedAt: new Date().toISOString(),
      note: currentStep.blockedReason,
    })
  }, [currentStep, finishStep, promptDrafts, runChatStep, runningStepId])

  const handleSkip = useCallback(() => {
    if (!currentStep || runningStepId) return
    finishStep(currentStep, {
      status: currentStep.kind === "blocked" ? "blocked" : "handoff",
      finishedAt: new Date().toISOString(),
      note: currentStep.kind === "blocked" ? currentStep.blockedReason : "操作员跳过了此步骤。",
    })
  }, [currentStep, finishStep, runningStepId])

  const handleReset = useCallback(() => {
    if (runningStepId && activeRunIdRef.current) stop(activeRunIdRef.current)
    activeRunIdRef.current = null
    setRunningStepId(null)
    setActiveRunId(null)
    setCursor(0)
    setResults({})
    try {
      window.localStorage.removeItem(STORAGE_KEY)
    } catch {
      // Storage may be disabled; the in-memory reset still succeeds.
    }
  }, [runningStepId, stop])

  const activeResult = useMemo(() => {
    if (runningStepId) return undefined
    return [...DEMO_STEPS].reverse().map((step) => results[step.id]).find((result) => result?.runId)
  }, [results, runningStepId])

  const displayRunId = activeRunId ?? activeResult?.runId ?? null
  const isFinished = cursor >= DEMO_STEPS.length

  return (
    <PageContainer compact className="mx-auto flex min-h-full max-w-[1600px] flex-col">
      <PageHeader
        compact
        title="EIS 系统演示"
        description={`一次点击只执行一个测试动作。共 ${DEMO_SCENARIOS.length} 个场景、${DEMO_STEPS.length} 个步骤；回答完成后按右侧验收要点人工判定。`}
        actions={
          <Button variant="outline" size="sm" onClick={handleReset}>
            <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            重置进度
          </Button>
        }
      />

      <div className="grid flex-1 gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
        <Card className="min-h-0 overflow-hidden xl:sticky xl:top-4 xl:h-[calc(100vh-9.5rem)]">
          <CardHeader className="border-b border-line pb-3">
            <div className="flex items-center justify-between gap-3">
              <CardTitle>测试计划</CardTitle>
              <span className="text-xs tabular-nums text-content-muted">{completedCount}/{DEMO_STEPS.length}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-active" aria-label={`完成 ${progressPercent}%`}>
              <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${progressPercent}%` }} />
            </div>
          </CardHeader>
          <CardContent className="h-[calc(100%-76px)] overflow-y-auto px-3 py-3">
            <div className="space-y-4">
              {DEMO_SCENARIOS.map((scenario) => (
                <section key={scenario.id} aria-labelledby={`${scenario.id}-title`}>
                  <div className="mb-1.5 flex items-center justify-between gap-2 px-2">
                    <h2 id={`${scenario.id}-title`} className="text-xs font-semibold uppercase tracking-wide text-content-muted">
                      {scenario.label} · {scenario.title}
                    </h2>
                    <span className={cn(
                      "shrink-0 text-[11px]",
                      scenario.status === "ready" ? "text-success" : scenario.status === "blocked" ? "text-warning" : "text-brand"
                    )}>
                      {scenarioStatusLabel(scenario.status)}
                    </span>
                  </div>
                  <div className="space-y-1">
                    {scenario.steps.map((step) => {
                      const stepIndex = DEMO_STEPS.findIndex((item) => item.id === step.id)
                      const active = stepIndex === cursor
                      const result = results[step.id]
                      return (
                        <button
                          key={step.id}
                          type="button"
                          onClick={() => !runningStepId && setCursor(stepIndex)}
                          disabled={Boolean(runningStepId)}
                          className={cn(
                            "flex w-full items-start gap-2.5 rounded-lg border px-2.5 py-2 text-left text-sm transition-colors",
                            active ? "border-brand/30 bg-brand-subtle text-content" : "border-transparent hover:bg-surface-muted",
                            runningStepId && "cursor-not-allowed opacity-70"
                          )}
                        >
                          <span className="mt-0.5 shrink-0"><PlanStepIcon result={result} active={active} /></span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium">{step.title}</span>
                            <span className="block text-xs text-content-muted">
                              {result ? resultLabel(result.status) : step.estimatedTime}
                            </span>
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </section>
              ))}
            </div>
          </CardContent>
        </Card>

        <div className="min-w-0 space-y-4">
          {isFinished ? (
            <Card>
              <CardContent className="flex min-h-72 flex-col items-center justify-center gap-4 py-12 text-center">
                <span className="rounded-full bg-success-bg p-3"><Check className="h-7 w-7 text-success" aria-hidden /></span>
                <div>
                  <h2 className="text-xl font-semibold">测试计划已走完</h2>
                  <p className="mt-1 text-sm text-content-muted">已执行或记录全部 {DEMO_STEPS.length} 个步骤。可从左侧选择任一步骤复测。</p>
                </div>
                <Button variant="outline" onClick={() => setCursor(0)}>回到第一步</Button>
              </CardContent>
            </Card>
          ) : currentStep && currentScenario ? (
            <Card>
              <CardHeader className="border-b border-line">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-1">
                    <div className="text-xs font-medium text-brand">{currentScenario.label} · 步骤 {cursor + 1}/{DEMO_STEPS.length}</div>
                    <CardTitle className="text-xl">{currentStep.title}</CardTitle>
                    <p className="max-w-3xl text-sm leading-6 text-content-muted">{currentStep.purpose}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <StepTypeBadge step={currentStep} />
                    <Badge variant="secondary">{currentStep.estimatedTime}</Badge>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-5 py-5">
                {currentStep.prompt ? (
                  <section>
                    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-muted">将发送的提示词</h3>
                    <textarea
                      value={promptDrafts[currentStep.id] ?? currentStep.prompt}
                      onChange={(event) => setPromptDrafts((previous) => ({
                        ...previous,
                        [currentStep.id]: event.target.value,
                      }))}
                      aria-label={`${currentStep.title} 问题`}
                      className="min-h-32 w-full resize-y rounded-lg border border-line bg-surface-muted p-4 text-sm leading-6 outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/20"
                    />
                  </section>
                ) : null}

                {currentStep.kind === "navigate" && currentStep.href ? (
                  <section className="rounded-lg border border-line bg-surface-muted p-4">
                    <div className="flex items-center gap-2 text-sm font-medium"><ExternalLink className="h-4 w-4" aria-hidden />控制台页面</div>
                    <Link href={currentStep.href} target="_blank" className="mt-1 inline-block text-sm text-brand hover:underline">
                      {currentStep.href}
                    </Link>
                  </section>
                ) : null}

                {currentStep.blockedReason ? (
                  <div className="flex gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                    <div><div className="font-medium">当前无法自动执行</div><p className="mt-1 leading-6">{currentStep.blockedReason}</p></div>
                  </div>
                ) : null}

                {currentStep.caution ? (
                  <div className="flex gap-3 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                    <p className="leading-6">{currentStep.caution}</p>
                  </div>
                ) : null}

                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-muted">验收要点</h3>
                  <ul className="grid gap-2 md:grid-cols-2">
                    {currentStep.expected.map((item) => (
                      <li key={item} className="flex gap-2 rounded-lg bg-surface-muted px-3 py-2 text-sm leading-5">
                        <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </section>

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
                  <Button variant="ghost" size="sm" onClick={handleSkip} disabled={Boolean(runningStepId)}>
                    <SkipForward className="mr-1.5 h-4 w-4" aria-hidden />跳过并到下一步
                  </Button>
                  {runningStepId ? (
                    <div className="flex items-center gap-2">
                      <span className="flex items-center gap-2 text-sm text-content-muted"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />测试运行中</span>
                      <Button variant="outline" onClick={() => activeRunIdRef.current && stop(activeRunIdRef.current)}>
                        <Pause className="mr-1.5 h-4 w-4" aria-hidden />停止
                      </Button>
                    </div>
                  ) : (
                    <Button onClick={() => void handleNext()}>
                      {currentStep.kind === "blocked" ? "下一步：记录阻塞" : currentStep.kind === "navigate" ? "下一步：打开操作页面" : "下一步：运行此测试"}
                      <ArrowRight className="ml-1.5 h-4 w-4" aria-hidden />
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ) : null}

          {displayRunId ? (
            <Card>
              <CardHeader className="border-b border-line pb-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2"><MessageSquare className="h-4 w-4" aria-hidden />最近一次查询输出</CardTitle>
                    <p className="mt-1 font-mono text-[11px] text-content-muted">{displayRunId}</p>
                  </div>
                  <Button asChild variant="outline" size="sm">
                    <Link href={`/?run_id=${encodeURIComponent(displayRunId)}`} target="_blank">完整对话 <ExternalLink className="ml-1.5 h-3.5 w-3.5" aria-hidden /></Link>
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="max-h-[70vh] overflow-y-auto py-5">
                {activeSession.messages.length === 0 ? (
                  <div className="flex items-center gap-2 py-6 text-sm text-content-muted">
                    {runningStepId ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <AlertTriangle className="h-4 w-4" aria-hidden />}
                    {runningStepId ? "等待路由和回答…" : "内存中没有此历史运行的内容，请打开完整对话查看。"}
                  </div>
                ) : (
                  <div className="space-y-6">
                    {activeSession.messages.map((message, index) => (
                      <div key={message.id ?? `${message.role}-${index}`} className={cn("rounded-lg", message.role === "user" && "bg-surface-muted p-4")}>
                        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-muted">
                          {message.role === "user" ? "测试输入" : message.role === "assistant" ? "DAC 输出" : "系统"}
                        </div>
                        {message.role === "assistant" ? (
                          <AssistantMessageBody
                            msg={message}
                            index={index}
                            messagesLength={activeSession.messages.length}
                            isStreaming={activeSession.isStreaming}
                            streamProgressList={activeSession.streamProgressList ?? EMPTY_PROGRESS}
                            streamStartedAt={activeSession.streamStartedAt}
                            thinkingElapsedSec={activeSession.thinkingElapsedSec}
                          />
                        ) : (
                          <p className="whitespace-pre-wrap text-sm leading-6">{message.content}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </PageContainer>
  )
}
