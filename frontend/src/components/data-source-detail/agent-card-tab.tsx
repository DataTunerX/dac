"use client"

import { useState } from "react"
import { Loader2, Pencil, Plus, Sparkles } from "lucide-react"
import { toast } from "sonner"

import { updateDescriptorSemanticDomain } from "@/lib/descriptors-api"
import type { DataDescriptorSemanticDomain } from "@/lib/api-types"
import {
  applySkills,
  emptySkillDraft,
  parseAgentCard,
  skillsFromCard,
  stringifyAgentCard,
  type AgentCardObject,
  type AgentCardSkillDraft,
} from "@/lib/agent-card"
import { RbacWrapper } from "@/components/rbac"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Markdown } from "@/components/markdown"

export function DataSourceAgentCardTab({
  namespace,
  name,
  semanticDomain,
  isLoading,
  onSaved,
}: {
  namespace: string
  name: string
  semanticDomain: DataDescriptorSemanticDomain | null
  isLoading: boolean
  onSaved: () => Promise<unknown>
}) {
  const parsed = parseAgentCard(semanticDomain?.agent_card)
  const skills = skillsFromCard(parsed)
  const description = typeof parsed?.description === "string" ? parsed.description : ""
  const cardName = typeof parsed?.name === "string" ? parsed.name : ""
  const hasRecord = Boolean(semanticDomain?.semantic_domain_id || semanticDomain?.agent_card)

  const [cardOpen, setCardOpen] = useState(false)
  const [savingCard, setSavingCard] = useState(false)
  const [cardUseRaw, setCardUseRaw] = useState(false)
  const [cardRawFallback, setCardRawFallback] = useState("")
  const [cardNameDraft, setCardNameDraft] = useState("")
  const [cardDesc, setCardDesc] = useState("")
  const [cardSkills, setCardSkills] = useState<AgentCardSkillDraft[]>([])

  const openEditAgentCard = () => {
    const current = parseAgentCard(semanticDomain?.agent_card)
    if (!current) {
      setCardUseRaw(true)
      setCardRawFallback(semanticDomain?.agent_card || "")
      setCardNameDraft("")
      setCardDesc("")
      setCardSkills([])
    } else {
      setCardUseRaw(false)
      setCardRawFallback("")
      setCardNameDraft(String(current.name ?? ""))
      setCardDesc(String(current.description ?? ""))
      const nextSkills = skillsFromCard(current)
      setCardSkills(nextSkills.length > 0 ? nextSkills : [emptySkillDraft()])
    }
    setCardOpen(true)
  }

  const saveAgentCard = async () => {
    if (savingCard) return
    setSavingCard(true)
    try {
      let nextCard: AgentCardObject
      if (cardUseRaw) {
        const parsedRaw = parseAgentCard(cardRawFallback)
        if (!parsedRaw) {
          toast.error("agent_card 不是合法 JSON")
          return
        }
        nextCard = parsedRaw
      } else {
        const base = parseAgentCard(semanticDomain?.agent_card) ?? {}
        nextCard = applySkills(
          { ...base, name: cardNameDraft.trim(), description: cardDesc },
          cardSkills.filter((s) => s.id.trim() || s.name.trim()),
        )
      }
      await updateDescriptorSemanticDomain(namespace, name, stringifyAgentCard(nextCard))
      toast.success("Agent Card 已更新")
      setCardOpen(false)
      await onSaved()
    } catch (e) {
      console.error("update descriptor agent_card failed", e)
      const err = e as { response?: { data?: { message?: string } } }
      toast.error(err.response?.data?.message || "更新 Agent Card 失败")
    } finally {
      setSavingCard(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-content-muted">
        <Loader2 className="w-8 h-8 animate-spin mb-4 text-cta" />
        <p>正在加载 Agent Card…</p>
      </div>
    )
  }

  if (!hasRecord) {
    return (
      <div className="rounded-lg border border-dashed border-line bg-surface-muted p-12 text-center">
        <Sparkles className="mx-auto h-10 w-10 text-content-muted opacity-40" />
        <h3 className="mt-3 text-sm font-semibold text-content">尚未生成 Agent Card</h3>
        <p className="mt-1 text-sm text-content-muted">
          请先完成数据抽取，生成 semantic domain 后再编辑描述与 skills。
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6 pt-2">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold text-content flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-content-muted" />
          Agent Card
        </h3>
        <RbacWrapper requiredPermission="descriptor:update">
          <Button variant="outline" size="sm" onClick={openEditAgentCard}>
            <Pencil className="w-3.5 h-3.5 mr-1.5" />
            编辑
          </Button>
        </RbacWrapper>
      </div>

      <div className="bg-surface rounded-xl border border-line p-6 shadow-sm space-y-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1 min-w-0">
            <div className="text-xs text-content-muted">名称</div>
            <div className="text-sm text-content truncate">{cardName || "-"}</div>
          </div>
          <div className="space-y-1 min-w-0">
            <div className="text-xs text-content-muted">Skills</div>
            <div className="text-sm text-content">{skills.length} 个</div>
          </div>
        </div>

        <div className="space-y-2">
          <div className="text-xs text-content-muted">描述</div>
          {description ? (
            <div className="text-sm text-content leading-relaxed">
              <Markdown>{description}</Markdown>
            </div>
          ) : (
            <div className="text-sm text-content-muted">暂无描述</div>
          )}
        </div>

        <div className="space-y-2">
          <div className="text-xs text-content-muted">Skills</div>
          {skills.length > 0 ? (
            <ul className="space-y-2">
              {skills.map((sk, idx) => (
                <li key={`${sk.id}-${sk.name}-${idx}`} className="rounded-md border border-line px-3 py-2">
                  <div className="text-sm font-medium text-content truncate">
                    {sk.name || sk.id || "未命名 skill"}
                  </div>
                  {sk.id ? <div className="text-xs font-mono text-content-muted">{sk.id}</div> : null}
                  {sk.description ? (
                    <div className="mt-1 text-xs text-content-muted whitespace-pre-wrap break-words">
                      {sk.description}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-sm text-content-muted">暂无 skill</div>
          )}
        </div>
      </div>

      <Dialog open={cardOpen} onOpenChange={setCardOpen}>
        <DialogContent className="w-[min(96vw,48rem)] max-w-3xl max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50">
            <DialogTitle>编辑 Agent Card</DialogTitle>
          </DialogHeader>
          <div className="px-6 py-4 flex-1 min-h-0 overflow-y-auto space-y-4">
            {cardUseRaw ? (
              <div className="space-y-2">
                <Label htmlFor="dd-agent-card-raw">agent_card JSON</Label>
                <Textarea
                  id="dd-agent-card-raw"
                  className="min-h-[280px] font-mono text-xs"
                  value={cardRawFallback}
                  onChange={(e) => setCardRawFallback(e.target.value)}
                />
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  <Label htmlFor="dd-agent-card-name">名称</Label>
                  <Input
                    id="dd-agent-card-name"
                    value={cardNameDraft}
                    onChange={(e) => setCardNameDraft(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="dd-agent-card-desc">description</Label>
                  <Textarea
                    id="dd-agent-card-desc"
                    className="min-h-[160px]"
                    value={cardDesc}
                    onChange={(e) => setCardDesc(e.target.value)}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium text-content">Skills</div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCardSkills((prev) => [...prev, emptySkillDraft()])}
                  >
                    <Plus className="w-3.5 h-3.5 mr-1.5" />
                    添加 skill
                  </Button>
                </div>
                <div className="space-y-3">
                  {cardSkills.map((sk, idx) => (
                    <div key={`${idx}-${sk.id}`} className="rounded-md border border-line p-3 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-xs text-content-muted">Skill {idx + 1}</div>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-red-600 hover:text-red-700"
                          onClick={() => setCardSkills((prev) => prev.filter((_, i) => i !== idx))}
                        >
                          删除
                        </Button>
                      </div>
                      <Input
                        placeholder="id"
                        value={sk.id}
                        onChange={(e) =>
                          setCardSkills((prev) =>
                            prev.map((item, i) => (i === idx ? { ...item, id: e.target.value } : item)),
                          )
                        }
                      />
                      <Input
                        placeholder="name"
                        value={sk.name}
                        onChange={(e) =>
                          setCardSkills((prev) =>
                            prev.map((item, i) => (i === idx ? { ...item, name: e.target.value } : item)),
                          )
                        }
                      />
                      <Textarea
                        placeholder="description"
                        className="min-h-[72px]"
                        value={sk.description}
                        onChange={(e) =>
                          setCardSkills((prev) =>
                            prev.map((item, i) => (i === idx ? { ...item, description: e.target.value } : item)),
                          )
                        }
                      />
                      <Input
                        placeholder="tags，逗号分隔"
                        value={sk.tags}
                        onChange={(e) =>
                          setCardSkills((prev) =>
                            prev.map((item, i) => (i === idx ? { ...item, tags: e.target.value } : item)),
                          )
                        }
                      />
                      <Textarea
                        placeholder="examples，每行一条"
                        className="min-h-[64px]"
                        value={sk.examples}
                        onChange={(e) =>
                          setCardSkills((prev) =>
                            prev.map((item, i) => (i === idx ? { ...item, examples: e.target.value } : item)),
                          )
                        }
                      />
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCardOpen(false)} disabled={savingCard}>
              取消
            </Button>
            <Button onClick={() => void saveAgentCard()} disabled={savingCard}>
              {savingCard ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
