"use client"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Layers, Link2, Database, ChevronRight, Trash2 } from "lucide-react"
import type {
  SemanticGroupResponse,
  SemanticGroupInfoResponse,
  DDGroupRelationResponse,
} from "@/lib/api-types"

export const REL_GRAPH = {
  width: 1080,
  minWidthClass: "min-w-[1080px]",
  maxHeight: 560,
  minHeight: 320,
  gridDotOpacity: 0.1,
  gridDotSize: 20,
  nodeW: 280,
  nodeH: 96,
  groupX: 190,
  ddX: 900,
  edgeGap: 10,
  sgArrow: "#334155",
  strokeWidth: 2.2,
} as const

function bezier(startX: number, startY: number, endX: number, endY: number, curve: number) {
  const c1 = startX + curve
  const c2 = endX - curve
  return `M ${startX} ${startY} C ${c1} ${startY}, ${c2} ${endY}, ${endX} ${endY}`
}

function shortID(id: string) {
  const s = String(id || "")
  if (s.length <= 18) return s
  return `${s.slice(0, 8)}…${s.slice(-6)}`
}

export type RelationGraphDDBucket = {
  key: string
  dd_namespace: string
  dd_name: string
  items: DDGroupRelationResponse[]
  hasDD: boolean
  isLoading: boolean
}

export type RelationGraphProps = {
  group: SemanticGroupResponse | null
  groupId: string
  childGroups: SemanticGroupInfoResponse[]
  ddBuckets: RelationGraphDDBucket[]
  graphHeight: number
  isLoading: boolean
  markerId: string
  onOpenReason: (r: DDGroupRelationResponse) => void
  onDeleteRel: (r: DDGroupRelationResponse) => void
  onRemoveDDFromGroup?: (bucket: RelationGraphDDBucket) => void
  onNavigateToGroup: (id: string) => void
  onNavigateToDataSource: (namespace: string, name: string) => void
}

export function RelationGraph({
  group,
  groupId,
  childGroups,
  ddBuckets,
  graphHeight,
  isLoading,
  markerId,
  onOpenReason,
  onDeleteRel,
  onRemoveDDFromGroup,
  onNavigateToGroup,
  onNavigateToDataSource,
}: RelationGraphProps) {
  const topPad = 56
  const gapY = 22
  const headerH = 88
  const rowH = 76
  const ddCardW = 380
  const ddCardX = REL_GRAPH.ddX
  const groupCenterY = graphHeight / 2
  const groupOutX = REL_GRAPH.groupX + REL_GRAPH.nodeW / 2 + REL_GRAPH.edgeGap
  const rightInX = ddCardX - ddCardW / 2 - REL_GRAPH.edgeGap
  const childBlockH =
    childGroups.length > 0
      ? childGroups.length * REL_GRAPH.nodeH + (childGroups.length - 1) * gapY
      : 0
  const ddStartY = topPad + childBlockH + (childBlockH > 0 && ddBuckets.length > 0 ? gapY : 0)

  return (
    <div
      className={`relative ${REL_GRAPH.minWidthClass} mx-auto`}
      style={{ height: graphHeight, width: REL_GRAPH.width }}
    >
      {/* edges */}
      <svg
        className="absolute left-0 top-0"
        width={REL_GRAPH.width}
        height={graphHeight}
        viewBox={`0 0 ${REL_GRAPH.width} ${graphHeight}`}
        aria-hidden="true"
        shapeRendering="geometricPrecision"
      >
        <defs>
          <style>{`
            @keyframes flow {
              from { stroke-dashoffset: 0; }
              to { stroke-dashoffset: -48; }
            }
            .flow-line {
              stroke-dasharray: 8 10;
              animation: flow 1.4s linear infinite;
            }
            @media (prefers-reduced-motion: reduce) {
              .flow-line { animation: none; }
            }
          `}</style>
          <marker id={markerId} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill={REL_GRAPH.sgArrow} opacity="0.9" />
          </marker>
        </defs>
        {childGroups.map((_, i) => {
          const centerY = topPad + i * (REL_GRAPH.nodeH + gapY) + REL_GRAPH.nodeH / 2
          const d = bezier(groupOutX, groupCenterY, rightInX, centerY, 180)
          return (
            <path
              key={`child-${i}`}
              d={d}
              fill="none"
              stroke={REL_GRAPH.sgArrow}
              strokeWidth={REL_GRAPH.strokeWidth}
              opacity={1}
              strokeLinecap="round"
              strokeLinejoin="round"
              markerEnd={`url(#${markerId})`}
              vectorEffect="non-scaling-stroke"
              className="flow-line"
            />
          )
        })}
        {(() => {
          let yCursor = ddStartY
          return ddBuckets.map((b) => {
            const h = Math.max(REL_GRAPH.nodeH, headerH + b.items.length * rowH)
            const centerY = yCursor + h / 2
            yCursor += h + gapY
            const d = bezier(groupOutX, groupCenterY, rightInX, centerY, 180)
            return (
              <path
                key={b.key}
                d={d}
                fill="none"
                stroke={REL_GRAPH.sgArrow}
                strokeWidth={REL_GRAPH.strokeWidth}
                opacity={1}
                strokeLinecap="round"
                strokeLinejoin="round"
                markerEnd={`url(#${markerId})`}
                vectorEffect="non-scaling-stroke"
                className="flow-line"
              />
            )
          })
        })()}
      </svg>

      {/* 当前组 node */}
      <div
        className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
        style={{
          left: REL_GRAPH.groupX,
          width: REL_GRAPH.nodeW,
          height: REL_GRAPH.nodeH,
          pointerEvents: "auto",
        }}
      >
        <div className="h-full rounded-xl border border-line bg-surface shadow-sm px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-cta/10 flex items-center justify-center text-cta shrink-0">
              <Layers className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-content-muted">语义组</div>
              <div className="mt-0.5 text-sm font-medium text-content truncate">
                {group?.group_name || groupId}
              </div>
              <div className="text-[11px] text-content-muted font-mono truncate">{shortID(groupId)}</div>
            </div>
          </div>
        </div>
      </div>

      {/* 右侧列 = 关联：先子分组，再 DD */}
      {childGroups.map((cg, i) => {
        const centerY = topPad + i * (REL_GRAPH.nodeH + gapY) + REL_GRAPH.nodeH / 2
        return (
          <div
            key={cg.id}
            className="absolute -translate-x-1/2 -translate-y-1/2"
            style={{
              left: REL_GRAPH.ddX,
              top: centerY,
              width: REL_GRAPH.nodeW,
              height: REL_GRAPH.nodeH,
              pointerEvents: "auto",
            }}
          >
            <button
              type="button"
              onClick={() => onNavigateToGroup(cg.id)}
              className="h-full w-full rounded-xl border border-line bg-surface shadow-sm px-4 py-3 flex items-center gap-2 text-left hover:border-cta/40 hover:shadow-md transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cta/50"
            >
              <div className="w-8 h-8 rounded-full bg-cta/10 flex items-center justify-center text-cta shrink-0">
                <Layers className="w-4 h-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs text-content-muted">子分组</div>
                <div className="mt-0.5 text-sm font-medium text-content truncate">{cg.group_name}</div>
              </div>
              <ChevronRight className="w-4 h-4 text-content-muted shrink-0" />
            </button>
          </div>
        )
      })}

      {/* DD buckets */}
      {isLoading && ddBuckets.length === 0 ? (
        <div
          className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-sm text-content-muted"
          style={{ left: REL_GRAPH.ddX }}
        >
          加载中…
        </div>
      ) : childGroups.length === 0 && ddBuckets.length === 0 ? (
        <div
          className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-sm text-content-muted"
          style={{ left: REL_GRAPH.ddX }}
        >
          暂无关联
        </div>
      ) : ddBuckets.length > 0 ? (
        (() => {
          const childBlockH =
            childGroups.length * REL_GRAPH.nodeH + (childGroups.length - 1) * gapY
          const ddStartY = topPad + childBlockH + (childGroups.length > 0 ? gapY : 0)
          let yCursor = ddStartY
          return ddBuckets.map((b) => {
            const h = Math.max(REL_GRAPH.nodeH, headerH + b.items.length * rowH)
            const centerY = yCursor + h / 2
            yCursor += h + gapY
            const ddFull = b.hasDD ? `${b.dd_namespace}/${b.dd_name}` : ""
            return (
              <div
                key={b.key}
                className={[
                  "absolute -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line bg-surface shadow-sm overflow-hidden flex flex-col",
                  b.hasDD ? "hover:border-indigo-200" : "opacity-80",
                ].join(" ")}
                style={{ top: centerY, left: REL_GRAPH.ddX, width: ddCardW, height: h }}
              >
                <div className="px-4 py-3 border-b border-line flex items-start justify-between gap-2">
                  <button
                    type="button"
                    disabled={!b.hasDD}
                    onClick={() => b.hasDD && onNavigateToDataSource(b.dd_namespace, b.dd_name)}
                    onKeyDown={(e) => {
                      if (!b.hasDD) return
                      if (e.key !== "Enter" && e.key !== " ") return
                      e.preventDefault()
                      onNavigateToDataSource(b.dd_namespace, b.dd_name)
                    }}
                    className={[
                      "relative min-w-0 flex-1 flex items-center gap-2 text-left rounded-lg",
                      "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-200",
                      b.hasDD ? "cursor-pointer" : "cursor-default",
                    ].join(" ")}
                    title={b.hasDD ? ddFull : b.isLoading ? "DD 信息加载中…" : "未关联数据源"}
                  >
                    {b.dd_namespace ? (
                      <Badge
                        variant="secondary"
                        className="absolute right-0 top-0 translate-y-[-2px] translate-x-[2px] bg-surface border border-line text-content font-mono text-[10px] h-5 px-2"
                      >
                        {b.dd_namespace}
                      </Badge>
                    ) : null}
                    <div className="w-8 h-8 rounded-full bg-indigo-50 flex items-center justify-center text-indigo-600 shrink-0">
                      <Database className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs text-content-muted">data descriptor</div>
                      <div className="mt-0.5 text-sm font-medium text-content truncate">
                        {!b.hasDD ? (b.isLoading ? "加载中…" : "未关联") : b.dd_name || "-"}
                      </div>
                      <div className="text-[11px] text-content-muted truncate">
                        由 {b.items.length} 个 semantic domain 映射到此数据源
                      </div>
                    </div>
                  </button>
                  {b.hasDD && b.items.length > 0 && onRemoveDDFromGroup ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0 text-red-600 hover:text-red-700"
                      onClick={(e) => {
                        e.stopPropagation()
                        onRemoveDDFromGroup(b)
                      }}
                      title={`将 ${ddFull} 移出语义组`}
                      aria-label={`将 ${ddFull} 移出语义组`}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  ) : null}
                </div>
                <div className="flex-1 min-h-0 overflow-auto divide-y divide-line">
                  {b.items.map((r) => (
                    <div
                      key={r.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => onOpenReason(r)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault()
                          onOpenReason(r)
                        }
                      }}
                      className="group px-4 py-2.5 flex items-start justify-between gap-3 hover:bg-surface-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-line-hover"
                      title="点击查看分组策略"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-full bg-cta/10 flex items-center justify-center text-cta shrink-0">
                            <Link2 className="w-4 h-4" />
                          </div>
                          <div className="min-w-0">
                            <div className="text-xs text-content-muted whitespace-nowrap">semantic domain</div>
                            <div className="mt-0.5 text-sm font-medium text-content truncate">{shortID(r.sd_id)}</div>
                          </div>
                        </div>
                        <div className="mt-1.5 text-xs text-content-muted line-clamp-1" title={r.association_reason || ""}>
                          {r.association_reason ? `分组策略：${r.association_reason}` : (
                            <span className="text-content-muted italic">暂无分组策略</span>
                          )}
                        </div>
                      </div>
                      <div className="shrink-0 flex items-center gap-1.5">
                        {b.hasDD ? (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-content hover:text-content opacity-0 group-hover:opacity-100 transition-opacity"
                            onClick={(e) => {
                              e.stopPropagation()
                              onNavigateToDataSource(b.dd_namespace, b.dd_name)
                            }}
                            title={ddFull ? `查看数据源：${ddFull}` : "查看数据源"}
                          >
                            <ChevronRight className="w-4 h-4" />
                          </Button>
                        ) : null}
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-red-600 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity"
                          onClick={(e) => {
                            e.stopPropagation()
                            onDeleteRel(r)
                          }}
                          title="解除关联"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )
          })
        })()
      ) : null}
    </div>
  )
}
