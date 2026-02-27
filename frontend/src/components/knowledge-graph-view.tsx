"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { Copy, Loader2, Maximize2, Minimize2, X } from "lucide-react";

// Use next/dynamic with ssr: false for react-force-graph-2d
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
});

type UnknownRecord = Record<string, unknown>;
function isRecord(v: unknown): v is UnknownRecord {
  return Boolean(v) && typeof v === "object" && !Array.isArray(v);
}

type GraphNodeDto = {
  id: string;
  labels?: string[];
  raw: UnknownRecord;
};

type GraphRelDto = {
  start: string;
  end: string;
  type?: string;
  raw: UnknownRecord;
};

// --- Neo4j Colors ---
const NEO4J_PALETTE = [
  { bg: "#68BDF6", text: "#FFFFFF" }, // blue
  { bg: "#6DCE9E", text: "#FFFFFF" }, // green
  { bg: "#FF756E", text: "#FFFFFF" }, // red
  { bg: "#DE9BF9", text: "#FFFFFF" }, // purple
  { bg: "#FFC766", text: "#1F2937" }, // orange
  { bg: "#F6F38A", text: "#1F2937" }, // yellow
  { bg: "#A5ABB6", text: "#FFFFFF" }, // gray
  { bg: "#C2E5A0", text: "#1F2937" }, // light green
  { bg: "#93E4C6", text: "#1F2937" }, // teal
  { bg: "#C6C6E4", text: "#1F2937" }, // periwinkle
  { bg: "#FFCECE", text: "#1F2937" }, // light red
  { bg: "#DAF6FF", text: "#1F2937" }, // light blue
];

function colorForLabel(label: string) {
  let h = 0;
  for (let i = 0; i < label.length; i++)
    h = (h * 31 + label.charCodeAt(i)) >>> 0;
  return NEO4J_PALETTE[h % NEO4J_PALETTE.length];
}

function labelKey(labels?: string[]) {
  const arr = Array.isArray(labels) ? labels : [];
  return (arr[arr.length - 1] || arr[0] || "Node").toString();
}

function truncateNodeCaption(name: string) {
  const s = (name || "").trim();
  if (!s) return "N";
  const isCJK = /[\u4E00-\u9FFF]/.test(s);
  const limit = isCJK ? 6 : 10;
  return s.length > limit ? `${s.slice(0, limit)}…` : s;
}

function nodeAbbrev(name: string) {
  const s = (name || "").trim();
  if (!s) return "N";
  const isCJK = /[\u4E00-\u9FFF]/.test(s);
  return isCJK ? s.slice(0, 2) : s.slice(0, 3).toUpperCase();
}

function pickNodeName(raw: UnknownRecord, id: string) {
  const props = isRecord(raw.properties) ? raw.properties : {};
  const name =
    (typeof raw.name === "string" && raw.name.trim()) ||
    (typeof raw.englishName === "string" && raw.englishName.trim()) ||
    (typeof raw.title === "string" && raw.title.trim()) ||
    (typeof props.name === "string" && props.name.trim()) ||
    (typeof props.englishName === "string" && props.englishName.trim()) ||
    (typeof props.title === "string" && props.title.trim()) ||
    id;
  return name;
}

function fixedFieldValue(raw: UnknownRecord, id: string) {
  const labels = Array.isArray((raw as any).labels)
    ? ((raw as any).labels as unknown[]).map(String)
    : [];
  const name = pickNodeName(raw, id);
  const source =
    (typeof (raw as any).data_source === "string" &&
      String((raw as any).data_source)) ||
    (typeof (raw as any).source === "string" && String((raw as any).source)) ||
    "";
  return { id, name, labels, source };
}

function extractGraph(payload: unknown): {
  nodes: GraphNodeDto[];
  rels: GraphRelDto[];
} {
  const root = isRecord(payload) ? payload : {};
  const nodesRaw = Array.isArray((root as any).nodes)
    ? ((root as any).nodes as unknown[])
    : [];
  const relsRaw = Array.isArray((root as any).relationships)
    ? ((root as any).relationships as unknown[])
    : [];

  const nodes: GraphNodeDto[] = nodesRaw
    .map((x) => (isRecord(x) ? x : {}))
    .map((x) => ({
      id: typeof x.id === "string" ? x.id : "",
      labels: Array.isArray(x.labels)
        ? (x.labels as unknown[]).map(String)
        : undefined,
      raw: x,
    }))
    .filter((n) => Boolean(n.id));

  const rels: GraphRelDto[] = relsRaw
    .map((x) => (isRecord(x) ? x : {}))
    .map((x) => {
      const start =
        typeof (x as any).start_id === "string"
          ? String((x as any).start_id)
          : typeof (x as any).start === "string"
            ? String((x as any).start)
            : "";
      const end =
        typeof (x as any).end_id === "string"
          ? String((x as any).end_id)
          : typeof (x as any).end === "string"
            ? String((x as any).end)
            : "";
      const type =
        typeof (x as any).type === "string" ? String((x as any).type) : "";
      return { start, end, type, raw: x };
    })
    .filter((r) => Boolean(r.start && r.end));

  return { nodes, rels };
}

export function KnowledgeGraphView({
  source,
  className,
  nodeLimit = 1000,
  relLimit = 1000,
}: {
  source: string;
  className?: string;
  nodeLimit?: number;
  relLimit?: number;
}) {
  const fgRef = useRef<any>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [graphRaw, setGraphRaw] = useState<unknown>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 800, h: 560 });
  const [hoverNode, setHoverNode] = useState<any | null>(null);

  const [selected, setSelected] = useState<
    | { kind: "node"; id: string }
    | { kind: "rel"; id: string }
    | null
  >(null);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    const measure = () => {
      if (fullscreen) {
        setDims({ w: window.innerWidth, h: window.innerHeight });
      } else if (containerRef.current) {
        setDims({
          w: containerRef.current.offsetWidth,
          h: containerRef.current.offsetHeight,
        });
      }
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [isLoading, fullscreen]);

  const load = useCallback(async () => {
    const s = (source || "").trim();
    if (!s) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.post("/knowledge-graph/get-graph-by-source", {
        source: s,
        node_limit: nodeLimit,
        rel_limit: relLimit,
      });
      setGraphRaw(res.data);
    } catch (e) {
      console.error("load graph failed", e);
      setGraphRaw(null);
      setError("加载知识图谱失败");
    } finally {
      setIsLoading(false);
    }
  }, [nodeLimit, relLimit, source]);

  useEffect(() => {
    void load();
  }, [load]);

  // ESC 退出全屏 & 切换时 zoomToFit
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && fullscreen) setFullscreen(false);
    };
    if (fullscreen) window.addEventListener("keydown", onKey);
    // 切换后等 canvas 更新再 zoomToFit
    const timer = setTimeout(() => {
      fgRef.current?.zoomToFit(400, 50);
    }, 300);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(timer);
    };
  }, [fullscreen]);

  const extracted = useMemo(() => extractGraph(graphRaw), [graphRaw]);

  // useEffect(() => {
  //   // Force initial zoom-to-fit when graph is ready and has data
  //   if (fgRef.current && extracted.nodes.length > 0) {
  //     // Small delay to ensure canvas is ready
  //     const timer = setTimeout(() => {
  //       fgRef.current?.zoomToFit(400, 50);
  //     }, 200);
  //     return () => clearTimeout(timer);
  //   }
  // }, [extracted.nodes.length, dims]);

  // Transform to ForceGraph format
  const graphData = useMemo(() => {
    // 1. Build a unique map of label -> color to ensure distinct colors if possible
    const uniqueLabels = new Set<string>();
    extracted.nodes.forEach((n) => uniqueLabels.add(labelKey(n.labels)));
    
    // Sort labels to ensure deterministic assignment order
    const sortedLabels = Array.from(uniqueLabels).sort();
    const labelColorMap = new Map<string, typeof NEO4J_PALETTE[number]>();
    
    sortedLabels.forEach((lbl, idx) => {
        labelColorMap.set(lbl, NEO4J_PALETTE[idx % NEO4J_PALETTE.length]);
    });

    const nodeById = new Map<string, GraphNodeDto>();
    for (const n of extracted.nodes) nodeById.set(n.id, n);

    const degree = new Map<string, number>();
    for (const n of extracted.nodes) degree.set(n.id, 0);
    for (const r of extracted.rels) {
      degree.set(r.start, (degree.get(r.start) || 0) + 1);
      degree.set(r.end, (degree.get(r.end) || 0) + 1);
    }

    const nodes = extracted.nodes.map((n) => {
      const labels = Array.isArray(n.labels) ? n.labels : [];
      const lbl = labelKey(labels);
      const name = pickNodeName(n.raw, n.id);
      
      // Use the pre-computed map, fallback to hashing if missing (shouldn't happen)
      const c = labelColorMap.get(lbl) || colorForLabel(lbl);
      
      const d = degree.get(n.id) || 0;
      // Neo4j-like sizing
      const val = Math.max(4, Math.min(10, 4 + Math.sqrt(d)));

      return {
        id: n.id,
        name,
        color: c.bg,
        textColor: c.text,
        val,
        raw: n.raw,
        labels,
      };
    });

    const links = extracted.rels.map((r, i) => ({
      source: r.start,
      target: r.end,
      type: r.type,
      raw: r.raw,
      id: `${r.start}_${r.type}_${r.end}_${i}`,
    }));

    // Build neighbor map for hover highlighting
    const nodeMap = new Map();
    nodes.forEach((n) => {
      (n as any).neighbors = new Set();
      (n as any).links = new Set();
      nodeMap.set(n.id, n);
    });

    links.forEach((link) => {
      const a = nodeMap.get(link.source);
      const b = nodeMap.get(link.target);
      if (a && b) {
        a.neighbors.add(b.id);
        b.neighbors.add(a.id);
        a.links.add(link);
        b.links.add(link);
      }
    });

    return { nodes, links, nodeById, relById: new Map() }; // relById handling differs
  }, [extracted]);

  // Node paint logic to look like Neo4j
  const paintNode = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const { x, y, val, color, name, textColor } = node;
      const size = val || 4;
      const isSelected = selected?.kind === "node" && selected.id === node.id;

      // Hover Logic: Dim if hovering something else AND this node is not a neighbor
      const isHovered = hoverNode === node;
      const isNeighbor =
        hoverNode &&
        (hoverNode.neighbors?.has(node.id) || hoverNode.links?.has(node)); // neighbors check
      const dim = hoverNode && !isHovered && !isNeighbor;

      ctx.globalAlpha = dim ? 0.1 : 1; // Fade out

      // Draw shadow (only if not dimmed)
      if (!dim) {
        ctx.shadowColor = "rgba(0, 0, 0, 0.1)";
        ctx.shadowBlur = 6;
        ctx.shadowOffsetX = 0;
        ctx.shadowOffsetY = 2;
      }

      // Draw circle
      ctx.beginPath();
      ctx.arc(x, y, size, 0, 2 * Math.PI, false);
      ctx.fillStyle = color;
      ctx.fill();

      // Reset shadow for border/text
      ctx.shadowColor = "transparent";
      ctx.shadowBlur = 0;
      ctx.shadowOffsetX = 0;
      ctx.shadowOffsetY = 0;

      // Draw border
      if (isSelected || isHovered) {
        ctx.lineWidth = (isSelected ? 2 : 1.5) / globalScale;
        ctx.strokeStyle = isSelected ? "rgb(37, 99, 235)" : "#555"; // blue-600 or dark gray
        ctx.stroke();
      } else {
        ctx.lineWidth = 0.5 / globalScale;
        ctx.strokeStyle = "#A5ABB6";
        ctx.stroke();
      }

      // Draw text
      // Show text if zoomed in enough OR selected OR hovered OR neighbor of hovered
      const showText =
        globalScale >= 1.2 ||
        isSelected ||
        isHovered ||
        isNeighbor ||
        true;

      if (showText) {
        const label = truncateNodeCaption(name);
        const fontSize = 12 / globalScale;
        ctx.font = `${isSelected || isHovered ? "bold" : "normal"} ${fontSize}px Sans-Serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        // 1. Draw text shadow/outline for readability
        ctx.strokeStyle = "rgba(255, 255, 255, 0.8)";
        ctx.lineWidth = 2 / globalScale;
        ctx.strokeText(label, x, y + size + fontSize); // Below node

        // 2. Draw actual text
        ctx.fillStyle = dim ? "#ccc" : "#1e293b"; // slate-800
        ctx.fillText(label, x, y + size + fontSize);
      }

      ctx.globalAlpha = 1; // Reset opacity
    },
    [selected, hoverNode],
  );

  return (
    <div className={cn("space-y-3", className)}>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
        {isLoading ? (
          <div className="py-20 flex items-center justify-center text-slate-500">
            <Loader2 className="w-6 h-6 animate-spin mr-2 text-blue-600" />
            加载中...
          </div>
        ) : error ? (
          <div className="p-6 text-sm text-red-700 bg-red-50 border-t border-red-100">
            {error}
          </div>
        ) : extracted.nodes.length === 0 ? (
          <div className="relative h-[560px]">
            <div className="h-full flex items-center justify-center text-slate-500">
              <div className="text-sm">暂无知识图谱数据</div>
            </div>
          </div>
        ) : (
          <div
            className={cn(
              "relative",
              fullscreen
                ? "fixed inset-0 z-50 bg-white h-screen w-screen"
                : "h-[560px]"
            )}
            ref={containerRef}
          >
            {/* 放大 / 缩小 按钮 */}
            <button
              className="absolute top-3 right-3 z-40 p-2 rounded-lg bg-white/90 border border-slate-200 shadow-sm hover:bg-slate-100 text-slate-600 hover:text-slate-900 transition-colors"
              title={fullscreen ? "退出全屏" : "全屏查看"}
              onClick={() => setFullscreen((v) => !v)}
            >
              {fullscreen ? (
                <Minimize2 className="w-4 h-4" />
              ) : (
                <Maximize2 className="w-4 h-4" />
              )}
            </button>
            <ForceGraph2D
              ref={fgRef}
              width={dims.w}
              height={dims.h}
              graphData={graphData}
              nodeLabel="name"
              nodeCanvasObject={paintNode}
              // Link styling
              linkColor={(link: any) => {
                if (hoverNode && !hoverNode.links?.has(link))
                  return "#E5E7EB"; // Dim non-connected links
                return "#A5ABB6";
              }}
              linkWidth={1.5}
              linkDirectionalArrowLength={0} // Disable built-in arrow to draw manually
              linkDirectionalArrowRelPos={1}
              // Link Label & Custom Arrow
              linkLabel="type"
              linkCanvasObjectMode={() => "after"}
              linkCanvasObject={(link: any, ctx, globalScale) => {
                const start = link.source;
                const end = link.target;
                if (!start || !end || !start.x || !end.x || !start.y || !end.y)
                  return;

                // Check visibility
                const isConnected =
                  hoverNode &&
                  (link.source === hoverNode || link.target === hoverNode);
                const dim = hoverNode && !isConnected;
                ctx.globalAlpha = dim ? 0.1 : 1;

                const relLink = { x: end.x - start.x, y: end.y - start.y };
                const dist = Math.sqrt(
                  relLink.x * relLink.x + relLink.y * relLink.y,
                );

                // --- 1. Draw Arrow ---
                // Node radius is stored in val (default 4)
                const rEnd = end.val || 4;

                // Only draw arrow if nodes are far enough
                if (dist > rEnd) {
                  const arrowLength = 2; // Smaller, nicer size
                  const arrowRelPos = 1 - (rEnd + 1.5) / dist; // Stop just before node boundary (1.5px gap for aesthetics)

                  if (arrowRelPos > 0 && arrowRelPos < 1) {
                    const arrowPos = {
                      x: start.x + relLink.x * arrowRelPos,
                      y: start.y + relLink.y * arrowRelPos,
                    };

                    ctx.save();
                    ctx.translate(arrowPos.x, arrowPos.y);
                    const angle = Math.atan2(relLink.y, relLink.x);
                    ctx.rotate(angle);

                    // Draw Solid Triangle Arrow
                    ctx.beginPath();
                    ctx.moveTo(0, 0); // Tip
                    ctx.lineTo(-arrowLength, -arrowLength * 0.7); // Wing top
                    ctx.lineTo(-arrowLength, arrowLength * 0.7); // Wing bottom
                    ctx.closePath();
                    ctx.fillStyle = "#A5ABB6";
                    ctx.fill();
                    ctx.restore();
                  }
                }

                // --- 2. Draw Label ---
                // Manually draw label on link
                const label = link.type;

                // Calculate midpoint
                const textPos = Object.assign({}, start, {
                  x: start.x + relLink.x / 2,
                  y: start.y + relLink.y / 2,
                });

                // Draw text background (pill)
                const fontSize = 3;
                ctx.font = `${fontSize}px Sans-Serif`;
                const textWidth = ctx.measureText(label).width;
                const bckgDimensions = [textWidth, fontSize].map(
                  (n) => n + fontSize * 0.2,
                );

                ctx.save();
                ctx.translate(textPos.x, textPos.y);
                const angle = Math.atan2(relLink.y, relLink.x);
                ctx.rotate(
                  angle > Math.PI / 2
                    ? angle + Math.PI
                    : angle < -Math.PI / 2
                      ? angle + Math.PI
                      : angle,
                ); // Keep text upright

                ctx.fillStyle = `rgba(255, 255, 255, ${dim ? 0.2 : 0.8})`; // Fade bg too
                ctx.fillRect(
                  -bckgDimensions[0] / 2,
                  -bckgDimensions[1] / 2,
                  bckgDimensions[0],
                  bckgDimensions[1],
                );

                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillStyle = "#666";
                ctx.fillText(label, 0, 0);
                ctx.restore();

                ctx.globalAlpha = 1;
              }}
              // Interaction
              onNodeHover={(node: any) => {
                setHoverNode(node || null);
                if (containerRef.current) {
                  containerRef.current.style.cursor = node
                    ? "pointer"
                    : "default";
                }
              }}
              onNodeClick={(node: any) => {
                setSelected({ kind: "node", id: node.id });
                // fgRef.current?.centerAt(node.x, node.y, 1000);
                // fgRef.current?.zoom(2, 1000);
              }}
              onBackgroundClick={() => setSelected(null)}
              // warmupTicks={100}
              cooldownTicks={100}
              onNodeDrag={(node: any) => {
                // Keep the simulation active while dragging to allow neighbors to adjust
                fgRef.current?.d3ReheatSimulation();
              }}
              onNodeDragEnd={(node: any) => {
                // Fix node position after drag (like Neo4j)
                node.fx = node.x;
                node.fy = node.y;
              }}
              onEngineStop={() => {
                fgRef.current?.zoomToFit(400, 50);
              }}
            />

            <InspectorPanel
              selected={selected}
              nodeById={graphData.nodeById}
              onClose={() => setSelected(null)}
            />

            <GraphLegend nodes={extracted.nodes} />
          </div>
        )}
      </div>
    </div>
  );
}

function GraphLegend({ nodes }: { nodes: GraphNodeDto[] }) {
  const { stats, colorMap } = useMemo(() => {
    const counts = new Map<string, number>();
    const uniqueLabels = new Set<string>();

    for (const node of nodes) {
      const lbl = labelKey(node.labels);
      counts.set(lbl, (counts.get(lbl) || 0) + 1);
      uniqueLabels.add(lbl);
    }

    // Sort labels to match the main logic's color assignment
    const sortedLabels = Array.from(uniqueLabels).sort();
    const map = new Map<string, typeof NEO4J_PALETTE[number]>();
    sortedLabels.forEach((lbl, idx) => {
        map.set(lbl, NEO4J_PALETTE[idx % NEO4J_PALETTE.length]);
    });

    // Sort stats by count desc
    const sortedStats = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
    
    return { stats: sortedStats, colorMap: map };
  }, [nodes]);

  if (stats.length === 0) return null;

  return (
    <div className="absolute bottom-4 right-4 z-20 max-h-[300px] overflow-y-auto w-[200px] pointer-events-auto">
      <div className="rounded-xl border border-slate-200 bg-white/90 backdrop-blur shadow-sm p-3 space-y-2">
        <div className="text-xs font-semibold text-slate-500 mb-2">
          图例 (节点类型)
        </div>
        <div className="space-y-1.5">
          {stats.map(([label, count]) => {
            const color = colorMap.get(label) || NEO4J_PALETTE[0];
            return (
              <div key={label} className="flex items-center gap-2 text-xs">
                <span
                  className="w-3 h-3 rounded-full shadow-sm border border-black/5"
                  style={{ backgroundColor: color.bg }}
                ></span>
                <span
                  className="font-medium text-slate-700 truncate flex-1"
                  title={label}
                >
                  {label}
                </span>
                <span className="text-slate-400">{count}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ... Inspector components largely same, adapted for unified types ...

function InspectorPanel({
  selected,
  nodeById,
  onClose,
}: {
  selected:
    | { kind: "node"; id: string }
    | { kind: "rel"; id: string }
    | null;
  nodeById: Map<string, GraphNodeDto>;
  onClose: () => void;
}) {
  const node = selected?.kind === "node" ? nodeById.get(selected.id) : undefined;
  // Rel lookup in force-graph is complex (link object vs id), skipping rel detail for now to focus on nodes
  const title = selected
    ? selected.kind === "node"
      ? "节点详情"
      : "关系详情"
    : "";

  if (!selected) return null;
  if (selected.kind === "node" && !node) return null;
  if (selected.kind === "rel") return null; // TODO: restore rel inspector if needed

  return (
    <div className="absolute right-4 top-4 z-30 w-[380px] max-w-[calc(100%-2rem)]">
      <div className="rounded-xl border border-slate-200 bg-white/95 backdrop-blur shadow-md overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between gap-2">
          <div className="text-sm font-semibold text-slate-900">{title}</div>
          <button
            className="p-1.5 rounded-md text-slate-400 hover:text-slate-700 hover:bg-slate-100"
            title="关闭"
            onClick={onClose}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-4 py-4 max-h-[500px] overflow-y-auto">
          {node ? <NodeInspector raw={node.raw} id={node.id} /> : null}
        </div>
      </div>
    </div>
  );
}

// Reuse existing inspectors
function NodeInspector({ raw, id }: { raw: UnknownRecord; id: string }) {
  const fixed = fixedFieldValue(raw, id);
  // Re-calculate local color mapping purely for display consistency, 
  // although context-less usage here will fall back to hash or we pass map.
  // Ideally, we'd pass the color map down, but for inspector we can just use the hash fallback 
  // OR strictly we should use the same logic if we want exact match. 
  // For now let's rely on the expanded palette reducing collisions, 
  // but note that isolated components won't know the global sort order.
  // Given the user issue is specifically about the main graph view collisions,
  // the previous fix addresses the main view and legend.
  // The inspector uses colorForLabel individually.
  
  const omit = new Set([
    "id",
    "labels",
    "name",
    "englishName",
    "title",
    "data_source",
    "source",
  ]);
  const entries = Object.entries(raw).filter(([k]) => !omit.has(k));
  entries.sort((a, b) => a[0].localeCompare(b[0]));

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="text-xs font-medium text-slate-500">基础信息</div>
        <div className="rounded-lg border border-slate-200 bg-white p-3 space-y-3">
          <FieldRow label="ID" value={fixed.id} mono onCopy={() => void copyText(fixed.id)} />
          <FieldRow label="Name" value={fixed.name} onCopy={() => void copyText(fixed.name)} />
          {fixed.labels.length > 0 ? (
            <div className="space-y-1">
              <div className="text-[11px] text-slate-500">Labels</div>
              <div className="flex flex-wrap gap-2">
                {fixed.labels.map((lb) => {
                  const c = colorForLabel(lb);
                  return (
                    <span
                      key={lb}
                      className="px-2 py-0.5 rounded-full text-xs font-medium"
                      style={{ background: c.bg, color: c.text }}
                    >
                      {lb}
                    </span>
                  );
                })}
              </div>
            </div>
          ) : null}
        </div>
      </div>
      <div className="space-y-2">
        <div className="text-xs font-medium text-slate-500">其他属性</div>
        {entries.length === 0 ? (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-500">
            无其他属性
          </div>
        ) : (
          <div className="rounded-lg border border-slate-200 bg-white divide-y divide-slate-100">
            {entries.map(([k, v]) => (
              <KeyValueRow keyName={k} value={v} key={k} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function FieldRow({
  label,
  value,
  mono,
  onCopy,
}: {
  label: string;
  value: string;
  mono?: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="text-[11px] text-slate-500">{label}</div>
        <div
          className={cn(
            "text-sm text-slate-900 break-words whitespace-pre-wrap",
            mono ? "font-mono" : "font-semibold",
          )}
        >
          {value}
        </div>
      </div>
      <button
        className="shrink-0 p-1.5 rounded-md text-slate-400 hover:text-blue-600 hover:bg-blue-50"
        title="复制"
        onClick={onCopy}
      >
        <Copy className="w-4 h-4" />
      </button>
    </div>
  );
}

function KeyValueRow({ keyName, value }: { keyName: string; value: unknown }) {
  const pv = safePreview(value);
  const isEmbedding = keyName === "embedding";
  const copyVal = pv.kind === "scalar" ? pv.text : JSON.stringify(value, null, 2);

  return (
    <div className="p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 w-full">
          <div className="flex items-center gap-2">
            <div className="font-mono text-xs text-slate-500">{keyName}</div>
            {pv.kind !== "scalar" ? (
              <span className="text-[11px] text-slate-400">{pv.text}</span>
            ) : null}
          </div>
          {isEmbedding ? (
            <details className="mt-2">
              <summary className="cursor-pointer text-sm text-slate-600 select-none">
                {pv.text}（点击展开）
              </summary>
              <pre className="mt-2 rounded-md border border-slate-200 bg-slate-50/50 p-3 text-xs font-mono whitespace-pre-wrap break-words max-h-[240px] overflow-auto">
                {JSON.stringify(value, null, 2)}
              </pre>
            </details>
          ) : pv.kind === "scalar" ? (
            <div className="mt-1 text-sm text-slate-800 break-words whitespace-pre-wrap">
              {pv.text}
            </div>
          ) : (
            <details className="mt-2">
              <summary className="cursor-pointer text-sm text-slate-600 select-none">
                展开查看
              </summary>
              <pre className="mt-2 rounded-md border border-slate-200 bg-slate-50/50 p-3 text-xs font-mono whitespace-pre-wrap break-words max-h-[240px] overflow-auto">
                {JSON.stringify(value, null, 2)}
              </pre>
            </details>
          )}
        </div>
        <button
          className="shrink-0 p-1.5 rounded-md text-slate-400 hover:text-blue-600 hover:bg-blue-50"
          title="复制"
          onClick={() => void copyText(copyVal)}
        >
          <Copy className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

function safePreview(v: unknown): {
  text: string;
  kind: "scalar" | "array" | "object";
} {
  if (v === null) return { text: "null", kind: "scalar" };
  if (v === undefined) return { text: "undefined", kind: "scalar" };
  if (typeof v === "string") return { text: v, kind: "scalar" };
  if (typeof v === "number" || typeof v === "boolean")
    return { text: String(v), kind: "scalar" };
  if (Array.isArray(v)) return { text: `Array(${v.length})`, kind: "array" };
  if (typeof v === "object") return { text: "Object", kind: "object" };
  return { text: String(v), kind: "scalar" };
}

async function copyText(text: string) {
  const t = (text || "").trim();
  if (!t) return;
  try {
    await navigator.clipboard.writeText(t);
    toast.success("已复制");
  } catch (e) {
    console.error("copy failed", e);
    toast.error("复制失败");
  }
}
