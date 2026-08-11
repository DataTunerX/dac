"use client"

import type { ReactNode } from "react"
import Link from "next/link"
import { Briefcase, Database, Loader2 } from "lucide-react"
import type { SemanticGroupResponse } from "@/lib/api-types"
import type { CompositionDataAgent } from "@/lib/agents-composition"

export type { MemberDescriptorBucket, CompositionDataAgent } from "@/lib/agents-composition"
export { buildCompositionDataAgents } from "@/lib/agents-composition"

/** 语义关系图：每行 = 智能体卡片 + 虚线 + 右侧资源（flex 一体，避免绝对定位被裁切） */
const COMPOSITION_AGENT_W = 280
const COMPOSITION_ROW_GAP = 12
/** 虚线 + 资源框（与 CompositionResourceBox 结构一致） */
const COMPOSITION_RESOURCE_SLOT = 204
const COMPOSITION_ROW_W = COMPOSITION_AGENT_W + COMPOSITION_ROW_GAP + COMPOSITION_RESOURCE_SLOT
const COMPOSITION_BRANCH_GAP = 32
const COMPOSITION_AGENT_CARD =
  "box-border grid h-[188px] w-[280px] shrink-0 grid-rows-[auto_auto_minmax(0,1fr)_auto] gap-0 overflow-hidden rounded-xl border border-line bg-surface px-5 py-4 text-center shadow-sm"
const COMPOSITION_RESOURCE_BOX =
  "box-border flex h-[72px] w-[156px] shrink-0 flex-col justify-center overflow-hidden rounded-lg border border-dashed border-line/90 bg-surface-muted/40 px-3 py-2 text-left"

type CompositionResourceItem = { key: string; label: string; href: string }

function compositionBranchWidth(agentCount: number): number {
  if (agentCount <= 0) return COMPOSITION_ROW_W
  return agentCount * COMPOSITION_ROW_W + (agentCount - 1) * COMPOSITION_BRANCH_GAP
}

function compositionAgentCenterX(index: number): number {
  const rowStart = index * (COMPOSITION_ROW_W + COMPOSITION_BRANCH_GAP)
  return rowStart + COMPOSITION_AGENT_W / 2
}

/** 主干 X：与智能体卡片中心对齐（不用整行含资源框的宽度中点） */
function compositionSpineX(childCount: number): number {
  if (childCount <= 1) return compositionAgentCenterX(0)
  const first = compositionAgentCenterX(0)
  const last = compositionAgentCenterX(childCount - 1)
  return (first + last) / 2
}

/** 业务 → 数据智能体的实线树形连接（单条 SVG，避免错位与多余线段） */
function CompositionTreeLines({
  branchWidth,
  childCount,
}: {
  branchWidth: number
  childCount: number
}) {
  if (childCount <= 0) return null

  const height = childCount === 1 ? 40 : 36
  const busY = childCount === 1 ? height : 20
  const stroke = "var(--color-line)"
  const strokeWidth = 2

  const spineX = compositionSpineX(childCount)

  if (childCount === 1) {
    const x = spineX
    return (
      <svg
        width={branchWidth}
        height={height}
        className="block shrink-0"
        aria-hidden
      >
        <line
          x1={x}
          y1={0}
          x2={x}
          y2={height}
          stroke={stroke}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />
      </svg>
    )
  }

  const centers = Array.from({ length: childCount }, (_, i) => compositionAgentCenterX(i))
  const busLeft = centers[0]!
  const busRight = centers[centers.length - 1]!

  return (
    <svg width={branchWidth} height={height} className="block shrink-0" aria-hidden>
      <line
        x1={spineX}
        y1={0}
        x2={spineX}
        y2={busY}
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
      />
      <line
        x1={Math.min(busLeft, spineX)}
        y1={busY}
        x2={Math.max(busRight, spineX)}
        y2={busY}
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
      />
      {centers.map((x, i) => (
        <line
          key={i}
          x1={x}
          y1={busY}
          x2={x}
          y2={height}
          stroke={stroke}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />
      ))}
    </svg>
  )
}

/** 智能体 + 右侧资源：同一行整体布局（与 relation-graph 节点并排思路一致） */
function CompositionGraphRow({ agent, resource }: { agent: ReactNode; resource: ReactNode }) {
  return (
    <div
      className="flex shrink-0 items-center gap-3"
      style={{ minWidth: COMPOSITION_ROW_W, width: COMPOSITION_ROW_W }}
    >
      {agent}
      {resource}
    </div>
  )
}

function CompositionResourceBox({
  label,
  items,
  emptyText,
  onLinkClick,
}: {
  label: string
  items: CompositionResourceItem[]
  emptyText?: string
  onLinkClick?: () => void
}) {
  return (
    <div className="flex shrink-0 items-center pl-1">
      <div className="mx-2 h-px w-7 shrink-0 border-t border-dashed border-line" aria-hidden />
      <div className={COMPOSITION_RESOURCE_BOX}>
        <div className="text-[10px] font-medium tracking-wide text-content-muted">{label}</div>
        {items.length === 0 ? (
          <span className="mt-1 block truncate text-xs text-content-muted">{emptyText ?? "-"}</span>
        ) : (
          <ul className="mt-1 space-y-0.5 overflow-hidden">
            {items.map((item) => (
              <li key={item.key} className="min-w-0">
                <Link
                  href={item.href}
                  className="block truncate text-xs font-medium text-cta hover:underline"
                  title={item.label}
                  onClick={() => onLinkClick?.()}
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function AgentNodeCard({
  kind,
  displayName,
  viewHref,
  onLinkClick,
}: {
  kind: "business" | "data"
  displayName: string
  viewHref: string
  onLinkClick?: () => void
}) {
  const isBusiness = kind === "business"
  return (
    <div className={COMPOSITION_AGENT_CARD}>
      <div
        className={`mx-auto flex h-10 w-10 items-center justify-center rounded-full ${
          isBusiness ? "bg-cta/10 text-cta" : "bg-indigo-50 text-indigo-600"
        }`}
      >
        {isBusiness ? <Briefcase className="h-5 w-5" /> : <Database className="h-5 w-5" />}
      </div>
      <p className="mt-2.5 text-[10px] font-medium uppercase tracking-wider text-content-muted">
        {isBusiness ? "业务智能体" : "数据智能体"}
      </p>
      <p
        className="mt-2 overflow-hidden text-sm font-medium leading-[1.35] text-content break-words line-clamp-3"
        title={displayName}
      >
        {displayName || "-"}
      </p>
      <Link
        href={viewHref}
        className="mt-3 inline-flex h-8 w-full items-center justify-center self-end rounded-md border border-line bg-surface text-xs font-medium text-content hover:bg-surface-muted"
        onClick={() => onLinkClick?.()}
      >
        查看
      </Link>
    </div>
  )
}

/** 业务智能体下方的数据智能体：横向并排，连线由 CompositionTreeLines 统一绘制 */
function DataAgentsBranch({
  dataAgents,
  onLinkClick,
}: {
  dataAgents: CompositionDataAgent[]
  onLinkClick?: () => void
}) {
  return (
    <div className="flex flex-row flex-nowrap items-start gap-8">
      {dataAgents.map((da) => {
        const viewHref = `/agents/${encodeURIComponent(da.namespace)}/${encodeURIComponent(da.name)}`
        const dataSources: CompositionResourceItem[] = da.coveredDescriptors.map((d) => ({
          key: `${d.namespace}/${d.name}`,
          label: d.name,
          href: `/datasources/${encodeURIComponent(d.namespace)}/${encodeURIComponent(d.name)}`,
        }))
        return (
          <CompositionGraphRow
            key={da.key}
            agent={
              <AgentNodeCard
                kind="data"
                displayName={da.displayName}
                viewHref={viewHref}
                onLinkClick={onLinkClick}
              />
            }
            resource={
              <CompositionResourceBox
                label="数据源"
                items={dataSources}
                emptyText="未绑定"
                onLinkClick={onLinkClick}
              />
            }
          />
        )
      })}
    </div>
  )
}

export function BizAgentCompositionGraph({
  bizDisplayName,
  bizNamespace,
  bizName,
  semanticGroup,
  dataAgents,
  isLoading,
  onLinkClick,
}: {
  bizDisplayName: string
  bizNamespace: string
  bizName: string
  semanticGroup: SemanticGroupResponse | null
  dataAgents: CompositionDataAgent[]
  isLoading: boolean
  onLinkClick?: () => void
}) {
  const groupId = semanticGroup?.id ?? ""
  const groupName = semanticGroup?.group_name || groupId || "-"
  const bizViewHref = `/agents/${encodeURIComponent(bizNamespace)}/${encodeURIComponent(bizName)}`
  const semanticResources: CompositionResourceItem[] = groupId
    ? [
        {
          key: groupId,
          label: groupName,
          href: `/semantic-groups/${encodeURIComponent(groupId)}`,
        },
      ]
    : []

  const branchCount = isLoading ? 1 : Math.max(dataAgents.length, 1)
  const branchWidth = compositionBranchWidth(isLoading ? 1 : dataAgents.length)
  const showConnector = isLoading || dataAgents.length > 0
  const spineX = compositionSpineX(branchCount)
  const bizRowPadLeft = branchCount > 1 ? spineX - COMPOSITION_AGENT_W / 2 : 0

  return (
    <div className="w-full overflow-x-auto overflow-y-visible py-8 px-4 sm:px-6">
      <div
        className="mx-auto flex shrink-0 flex-col overflow-visible"
        style={{ width: showConnector ? branchWidth : "max-content" }}
      >
        <div
          className="flex w-full justify-start overflow-visible"
          style={bizRowPadLeft > 0 ? { paddingLeft: bizRowPadLeft } : undefined}
        >
          <CompositionGraphRow
            agent={
              <AgentNodeCard
                kind="business"
                displayName={bizDisplayName || bizName}
                viewHref={bizViewHref}
                onLinkClick={onLinkClick}
              />
            }
            resource={
              <CompositionResourceBox
                label="语义组"
                items={semanticResources}
                emptyText="未绑定"
                onLinkClick={onLinkClick}
              />
            }
          />
        </div>

        {showConnector ? (
          <CompositionTreeLines branchWidth={branchWidth} childCount={branchCount} />
        ) : null}

        {isLoading ? (
          <div className="flex items-center gap-2 py-3 text-xs text-content-muted">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            加载数据智能体…
          </div>
        ) : dataAgents.length === 0 ? (
          <p className="py-3 text-center text-sm text-content-muted">暂无关联的数据智能体</p>
        ) : (
          <DataAgentsBranch dataAgents={dataAgents} onLinkClick={onLinkClick} />
        )}
      </div>
    </div>
  )
}
