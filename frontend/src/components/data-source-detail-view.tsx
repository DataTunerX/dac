"use client";

import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import axios from "axios";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardFooter,
} from "@/components/ui/card";
import {
  ArrowLeft,
  Database,
  LayoutGrid,
  Loader2,
  RefreshCw,
  Search,
  Table as TableIcon,
  Network,
  FileText,
  ChevronRight,
  Home,
  GitBranch,
  ChevronDown,
  Info,
  Briefcase,
  BookOpen,
  Layers,
  Maximize2,
  X,
} from "lucide-react";
import { Markdown, defaultMarkdownComponents } from "@/components/markdown";
import { BrandIcon } from "@/components/brand-icon";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { HoverHint } from "@/components/hover-hint";
import { KnowledgeGraphView } from "@/components/knowledge-graph-view";

type UnknownRecord = Record<string, unknown>;

function sourceBadgeClass(sourceType: string) {
  const t = (sourceType || "").toLowerCase();
  if (t.includes("gitee")) return "bg-red-50 text-red-700 border-red-100";
  if (t.includes("github"))
    return "bg-slate-50 text-slate-700 border-slate-200";
  if (t.includes("gitlab"))
    return "bg-orange-50 text-orange-700 border-orange-100";
  if (t.includes("mysql")) return "bg-sky-50 text-sky-700 border-sky-100";
  if (t.includes("postgres"))
    return "bg-indigo-50 text-indigo-700 border-indigo-100";
  if (t.includes("clickhouse"))
    return "bg-amber-50 text-amber-700 border-amber-100";
  return "bg-blue-50 text-blue-700 border-blue-100";
}

function getStatusColor(phase?: string) {
  const p = (phase || "").toLowerCase();
  if (p === "ready" || p === "succeeded" || p === "running") {
    return {
      badge: "bg-emerald-50 border-emerald-100 text-emerald-700",
      dot: "bg-emerald-500",
    };
  }
  if (p === "failed" || p === "error" || p === "notready") {
    return {
      badge: "bg-red-50 border-red-100 text-red-700",
      dot: "bg-red-500",
    };
  }
  return {
    badge: "bg-slate-100 border-slate-200 text-slate-700",
    dot: "bg-slate-400",
  };
}

function isRecord(v: unknown): v is UnknownRecord {
  return typeof v === "object" && v !== null;
}

type DataDescriptor = {
  name: string;
  namespace: string;
  descriptor_type?: string;
  overall_phase?: string;
  sources?: unknown[];
  source_statuses?: unknown[];
  created_at?: string;
  updated_at?: string;
  consumed_by?: unknown[];
};

type Signature = UnknownRecord;
type SemanticDomain = UnknownRecord;

type KnowledgeResult = {
  content?: string;
  metadata?: UnknownRecord;
  score?: number;
};

type LineageConsumer = {
  kind: "agent" | "unknown";
  name: string;
  namespace: string;
};

function kv(v: unknown): string {
  if (v === null || v === undefined) return "-";
  if (typeof v === "string") return v.trim() || "-";
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return "-";
}

function getCodeRepoFromSource(source: any): { type: string; path: string; branch?: string } | null {
  // Backend contract (dac-apiserver): sources[].codeRepo.{codeRepoType,codeRepoPath,codeRepoBranch}
  const cr = source?.codeRepo
  const type = typeof cr?.codeRepoType === "string" ? cr.codeRepoType.trim() : ""
  const path = typeof cr?.codeRepoPath === "string" ? cr.codeRepoPath.trim() : ""
  const branch = typeof cr?.codeRepoBranch === "string" ? cr.codeRepoBranch.trim() : ""
  if (!path) return null
  return { type, path, branch: branch || undefined }
}

function toRepoBrandSlug(t: string): "github" | "gitee" | "gitea" | "git" {
  const v = String(t || "").trim().toLowerCase()
  if (v === "github") return "github"
  if (v === "gitee") return "gitee"
  if (v === "gitea") return "gitea"
  return "git"
}

export function DataSourceDetailView() {
  const router = useRouter();
  const params = useParams<{ namespace: string; name: string }>();
  const namespace = decodeURIComponent(params?.namespace || "default");
  const name = decodeURIComponent(params?.name || "");
  const knowledgeGraphSource = useMemo(() => {
    // Must match data-sinkers `generate_collection_name`:
    // collection_name = f"{namespace}_{name}".replace("-", "_")
    return `${namespace}_${name}`.replaceAll("-", "_");
  }, [namespace, name]);

  const [isLoading, setIsLoading] = useState(false);
  const [dd, setDD] = useState<DataDescriptor | null>(null);
  const [signature, setSignature] = useState<Signature | null>(null);
  const [semanticDomain, setSemanticDomain] = useState<SemanticDomain | null>(
    null,
  );
  const [agentConsumers, setAgentConsumers] = useState<LineageConsumer[]>([]);

  const [tab, setTab] = useState<
    "overview" | "structure" | "knowledge" | "graph" | "lineage"
  >("overview");
  const [selectedTable, setSelectedTable] = useState<{
    tableName: string;
    md: string;
  } | null>(null);
  const [selectedKnowledge, setSelectedKnowledge] =
    useState<KnowledgeResult | null>(null);

  const [isLoadingKnowledge, setIsLoadingKnowledge] = useState(false);
  const [results, setResults] = useState<KnowledgeResult[]>([]);

  const [isPromptsDialogOpen, setIsPromptsDialogOpen] = useState(false);
  const [isLoadingPromptsDetail, setIsLoadingPromptsDetail] = useState(false);
  const [promptsDetail, setPromptsDetail] = useState<UnknownRecord | null>(
    null,
  );
  const [promptsDetailError, setPromptsDetailError] = useState<string | null>(
    null,
  );

  const title = useMemo(() => dd?.name || name, [dd?.name, name]);
  const updatedAtText = useMemo(() => {
    const v = dd?.updated_at;
    if (typeof v !== "string" || !v.trim()) return "";
    return v.replace("T", " ").replace("Z", "");
  }, [dd?.updated_at]);

  const connectionInfo = useMemo(() => {
    // 1. Try to get connection info from dd.sources[0].metadata
    if (dd?.sources && Array.isArray(dd.sources) && dd.sources.length > 0) {
      const s = dd.sources[0] as any;
      if (s?.metadata && isRecord(s.metadata)) {
        return {
          host: s.metadata.host,
          port: s.metadata.port,
          database: s.metadata.database,
          username: s.metadata.user, // Note: API returns 'user', UI displays 'username'
        };
      }
    }

    // 2. Fallback to signature.location_info (legacy)
    if (isRecord(signature)) {
      const v = signature.location_info;
      if (isRecord(v)) {
        return {
          host: v.host,
          port: v.port,
          database: v.database,
          username: v.username,
        };
      }
    }

    return { host: null, port: null, database: null, username: null };
  }, [dd?.sources, signature]);

  const signatureMeta = useMemo(() => {
    if (!isRecord(signature)) return null;
    const v = signature.metadata_content;
    return isRecord(v) ? (v as UnknownRecord) : null;
  }, [signature]);

  const sourceConfig = useMemo(() => {
    if (!dd?.sources || !Array.isArray(dd.sources) || dd.sources.length === 0)
      return null;
    const s = dd.sources[0] as any;
    return {
      promptsConfig: s?.prompts?.configMapName,
      codeRepo: getCodeRepoFromSource(s),
    };
  }, [dd?.sources]);

  const semanticDomainText = useMemo(() => {
    if (isRecord(semanticDomain)) {
      const v = semanticDomain.semantic_domain;
      return typeof v === "string" ? v : "";
    }
    return "";
  }, [semanticDomain]);

  const openPromptsDetail = async () => {
    const cmName = sourceConfig?.promptsConfig?.trim() || "";
    if (!cmName) return;
    setIsPromptsDialogOpen(true);
    setPromptsDetailError(null);
    setIsLoadingPromptsDetail(true);
    try {
      const res = await api.get(
        `/namespaces/${encodeURIComponent(namespace)}/configmaps/${encodeURIComponent(
          cmName,
        )}`,
      );
      const data = res.data as unknown;
      setPromptsDetail(isRecord(data) ? (data as UnknownRecord) : {});
    } catch (e) {
      console.error("load prompts configmap failed", e);
      setPromptsDetail(null);
      setPromptsDetailError("加载提示词配置详情失败");
    } finally {
      setIsLoadingPromptsDetail(false);
    }
  };

  const agentCard = useMemo(() => {
    if (!isRecord(semanticDomain)) return null;
    const raw = semanticDomain.agent_card;
    if (typeof raw !== "string" || !raw.trim()) return null;
    try {
      const obj = JSON.parse(raw) as unknown;
      return isRecord(obj) ? (obj as UnknownRecord) : null;
    } catch {
      return null;
    }
  }, [semanticDomain]);

  const tableCount = useMemo(() => {
    const meta = signatureMeta;
    if (!meta) return null;
    // 1. Try meta.table_count
    if (typeof meta.table_count === "number") return meta.table_count;

    // 2. Try meta.tables array length
    if (Array.isArray(meta.tables)) return meta.tables.length;

    // 3. Try meta.tables_schema_md_list array length (fallback)
    if (Array.isArray(meta.tables_schema_md_list))
      return meta.tables_schema_md_list.length;

    return null;
  }, [signatureMeta]);

  const tablesDetailMap = useMemo(() => {
    const detailStr = signatureMeta?.tables_detail;
    if (typeof detailStr !== "string") return {};
    const map: Record<string, { entity: string; desc: string }> = {};

    // Split by numbered list pattern "1. ", "2. " etc.
    const parts = detailStr.split(/\n\d+\.\s+/);
    parts.forEach((part) => {
      if (!part.trim()) return;
      // table name: name(entity)，table description: desc
      const match = part.match(
        /table name:\s*([^(]+?)(?:\(([^)]+)\))?[,，]?\s*table description:\s*(.*)/,
      );
      if (match) {
        const name = match[1].trim();
        const entity = match[2] ? match[2].trim() : "";
        const desc = match[3] ? match[3].trim() : "";
        map[name] = { entity, desc };
      }
    });
    return map;
  }, [signatureMeta?.tables_detail]);

  const tableList = useMemo(() => {
    if (!Array.isArray(signatureMeta?.tables_schema_md_list)) return [];
    return signatureMeta.tables_schema_md_list.map((item: any) => {
      const tableName = typeof item === "string" ? "" : item?.table_name || "";
      const md = typeof item === "string" ? item : item?.table_schema || "";
      const detail = tablesDetailMap[tableName] || {};
      return {
        tableName,
        md,
        entity: detail.entity || "-",
        desc: detail.desc || "-",
      };
    });
  }, [signatureMeta?.tables_schema_md_list, tablesDetailMap]);

  const load = async () => {
    if (!name) return;
    setIsLoading(true);
    try {
      // Clear stale data while switching between pages.
      setDD(null);
      setSignature(null);
      setSemanticDomain(null);
      setAgentConsumers([]);
      const res = await api.get(
        `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}`,
      );
      const data = res.data as unknown;
      const r = isRecord(data) ? data : {};
      setDD({
        name: String(r.name ?? name),
        namespace: String(r.namespace ?? namespace),
        descriptor_type:
          typeof r.descriptor_type === "string" ? r.descriptor_type : undefined,
        overall_phase:
          typeof r.overall_phase === "string" ? r.overall_phase : undefined,
        sources: Array.isArray(r.sources) ? r.sources : undefined,
        source_statuses: Array.isArray(r.source_statuses)
          ? r.source_statuses
          : undefined,
        created_at: typeof r.created_at === "string" ? r.created_at : undefined,
        updated_at: typeof r.updated_at === "string" ? r.updated_at : undefined,
        consumed_by: Array.isArray(r.consumed_by) ? r.consumed_by : undefined,
      });

      // 血缘依赖补全：consumed_by 可能为空，需要从 agent 列表反查引用关系
      try {
        const ares = await api.get("/agents");
        const payload = (ares.data?.data ?? ares.data) as unknown;
        const rr = isRecord(payload) ? payload : {};
        const items = Array.isArray(rr.items)
          ? rr.items
          : Array.isArray(rr.data)
            ? rr.data
            : Array.isArray(payload)
              ? payload
              : [];
        const deps: LineageConsumer[] = [];

        for (const a0 of items) {
          const a = isRecord(a0) ? a0 : {};
          const an = typeof a.name === "string" ? a.name : "";
          const ans = typeof a.namespace === "string" ? a.namespace : "default";
          if (!an) continue;

          let hit = false;
          // dataPolicy.sourceNameSelector: string[]
          const dp = isRecord(a.dataPolicy)
            ? (a.dataPolicy as UnknownRecord)
            : {};
          const sel = Array.isArray(dp.sourceNameSelector)
            ? dp.sourceNameSelector
            : [];
          if (sel.some((x) => typeof x === "string" && x === name)) hit = true;

          // activeDataDescriptors: [{name, namespace}]
          const ads = Array.isArray(a.activeDataDescriptors)
            ? a.activeDataDescriptors
            : [];
          if (
            ads.some((x) => {
              const z = isRecord(x) ? x : {};
              const dn = typeof z.name === "string" ? z.name : "";
              const dns =
                typeof z.namespace === "string" ? z.namespace : "default";
              return dn === name && dns === namespace;
            })
          ) {
            hit = true;
          }

          if (hit) deps.push({ kind: "agent", name: an, namespace: ans });
        }

        // Deduplicate
        const uniq = new Map<string, LineageConsumer>();
        for (const d of deps) {
          const k = `${d.kind}/${d.namespace}/${d.name}`;
          if (!uniq.has(k)) uniq.set(k, d);
        }
        setAgentConsumers(Array.from(uniq.values()));
      } catch (e) {
        // best-effort only
        console.warn("load agent lineage deps failed", e);
      }
    } catch (e) {
      if (axios.isAxiosError(e) && e.response?.status === 404) {
        // Not found is a valid UI state; don't spam console/toast.
        setDD(null);
        return;
      }
      toast.error("加载数据源详情失败");
      setDD(null);
    } finally {
      setIsLoading(false);
    }
  };

  const lineageConsumers = useMemo(() => {
    const fromConsumedBy: LineageConsumer[] = Array.isArray(dd?.consumed_by)
      ? dd!.consumed_by
          .map((c: any) => {
            const nm = typeof c?.name === "string" ? c.name : "";
            if (!nm) return null;
            return {
              kind:
                typeof c?.kind === "string" && c.kind === "agent"
                  ? "agent"
                  : "unknown",
              name: nm,
              namespace:
                typeof c?.namespace === "string" ? c.namespace : "default",
            } as LineageConsumer;
          })
          .filter((x): x is LineageConsumer => Boolean(x))
      : [];

    const all = [...fromConsumedBy, ...agentConsumers];
    const uniq = new Map<string, LineageConsumer>();
    for (const d of all) {
      const k = `${d.kind}/${d.namespace}/${d.name}`;
      if (!uniq.has(k)) uniq.set(k, d);
    }
    return Array.from(uniq.values());
  }, [dd?.consumed_by, agentConsumers]);

  const loadSignature = async () => {
    if (!name) return;
    try {
      const res = await api.get(
        `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}/signature`,
      );
      const data = res.data as unknown;
      const r = isRecord(data) ? data : {};
      const sig = r.data;
      setSignature(isRecord(sig) ? sig : sig ? (sig as UnknownRecord) : null);
    } catch (e) {
      if (axios.isAxiosError(e) && e.response?.status === 404) {
        setSignature(null);
        return;
      }
      setSignature(null);
    }
  };

  const loadSemanticDomain = async () => {
    if (!name) return;
    try {
      const res = await api.get(
        `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}/semantic-domain`,
      );
      const data = res.data as unknown;
      const r = isRecord(data) ? data : {};
      const sd = r.data;
      setSemanticDomain(isRecord(sd) ? sd : sd ? (sd as UnknownRecord) : null);
    } catch (e) {
      if (axios.isAxiosError(e) && e.response?.status === 404) {
        setSemanticDomain(null);
        return;
      }
      setSemanticDomain(null);
    }
  };

  useEffect(() => {
    void load();
    void loadSignature();
    void loadSemanticDomain();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namespace, name]);

  const loadKnowledge = async () => {
    setIsLoadingKnowledge(true);
    try {
      // Call GET /knowledge endpoint to retrieve all fragments
      const res = await api.get(
        `/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}/knowledge`,
      );
      const data = res.data as unknown;
      const r = isRecord(data) ? data : {};
      const list = Array.isArray(r.results) ? r.results : [];
      const adapted: KnowledgeResult[] = list.map((it) => {
        const x = isRecord(it) ? it : {};
        return {
          // data-services get_all returns Document schema: page_content + metadata + provider + children
          content:
            typeof x.page_content === "string" ? x.page_content : undefined,
          metadata: isRecord(x.metadata)
            ? (x.metadata as UnknownRecord)
            : undefined,
          score: typeof x.score === "number" ? x.score : undefined,
        };
      });
      setResults(adapted);
    } catch (e) {
      console.error("load knowledge failed", e);
      toast.error("加载知识分片失败");
    } finally {
      setIsLoadingKnowledge(false);
    }
  };

  useEffect(() => {
    if (tab === "knowledge") {
      void loadKnowledge();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, namespace, name]);

  return (
    <div className="p-8 space-y-6">
      {/* Header Section Group */}
      <div className="space-y-4">
        {/* Breadcrumb & Actions */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.back()}
              className="-ml-2 h-8 px-2 text-slate-500 hover:text-slate-900"
            >
              <ArrowLeft className="w-4 h-4 mr-1" />
              返回
            </Button>
            <nav
              className="flex items-center text-sm text-slate-500 min-w-0"
              aria-label="Breadcrumb"
            >
              <LinkItem href="/datasources" label="数据管理" />
              <ChevronRight className="w-4 h-4 mx-2 text-slate-400 shrink-0" />
              <span className="font-mono text-slate-500 shrink-0">
                {namespace}
              </span>
              <ChevronRight className="w-4 h-4 mx-2 text-slate-400 shrink-0" />
              <span className="font-medium text-slate-900 truncate">
                {name}
              </span>
            </nav>
          </div>
        </div>

        {/* Title & Meta */}
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
              <Badge variant="outline" className="font-mono text-xs bg-white">
                {dd?.descriptor_type || "unknown"}
              </Badge>
              {(() => {
                const { badge, dot } = getStatusColor(dd?.overall_phase);
                return (
                  <div
                    className={cn(
                      "flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-xs font-medium",
                      badge,
                    )}
                  >
                    <div className={cn("w-1.5 h-1.5 rounded-full", dot)} />
                    {dd?.overall_phase || "Unknown"}
                  </div>
                );
              })()}
            </div>
            {updatedAtText && (
              <div className="text-sm text-slate-500">
                更新于 <span className="font-mono">{updatedAtText}</span>
              </div>
            )}
          </div>
          <Button
            variant="outline"
            onClick={() => void (load(), loadSignature(), loadSemanticDomain())}
            disabled={isLoading}
            className="bg-white hover:bg-slate-50"
          >
            <RefreshCw
              className={cn("w-4 h-4 mr-2", isLoading && "animate-spin")}
            />
            刷新
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-slate-200">
        <div className="flex gap-6">
          {[
            { key: "overview", label: "概览" },
            { key: "structure", label: "数据结构" },
            { key: "knowledge", label: "知识分片" },
            { key: "graph", label: "知识图谱" },
            { key: "lineage", label: "血缘关系" },
          ].map((t) => {
            const active = tab === (t.key as any);
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key as any)}
                className={cn(
                  "pb-3 text-sm font-medium border-b-2 transition-colors",
                  active
                    ? "border-blue-600 text-slate-900"
                    : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300",
                )}
              >
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Main Content */}
      <div>
        {isLoading && !dd ? (
          <div className="flex flex-col items-center justify-center py-20 text-slate-500">
            <Loader2 className="w-8 h-8 animate-spin mb-4 text-blue-600" />
            <p>正在加载数据源详情...</p>
          </div>
        ) : !dd ? (
          <div className="rounded-lg border border-dashed border-slate-300 p-12 text-center">
            <Database className="mx-auto h-12 w-12 text-slate-300" />
            <h3 className="mt-2 text-sm font-semibold text-slate-900">
              未找到数据源
            </h3>
            <p className="mt-1 text-sm text-slate-500">
              该数据源不存在或已被删除。
            </p>
            <div className="mt-6">
              <Button variant="outline" onClick={() => router.back()}>
                返回列表
              </Button>
            </div>
          </div>
        ) : tab === "overview" ? (
          <div className="space-y-8 pt-2">
            {/* 基础信息 Section */}
            <section className="space-y-3">
              <h3 className="text-base font-semibold text-slate-900 flex items-center gap-2">
                <Info className="w-4 h-4 text-slate-500" />
                基础信息
              </h3>
              <div className="bg-white rounded-lg border border-slate-200 p-5 shadow-sm space-y-5">
                {/* Row 1: Connection Info */}
                <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
                  <InfoItem label="主机" value={kv(connectionInfo.host)} />
                  <InfoItem label="端口" value={kv(connectionInfo.port)} />
                  <InfoItem
                    label="数据库"
                    value={kv(connectionInfo.database)}
                  />
                  <InfoItem
                    label="用户名"
                    value={kv(connectionInfo.username)}
                  />

                  {/* Row 2: Prompts Config, Code Repo */}
                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-slate-500">
                      提示词配置
                    </div>
                    {sourceConfig?.promptsConfig ? (
                      <div className="flex items-center gap-2">
                        <HoverHint
                          text={sourceConfig.promptsConfig}
                          enableCopy
                          copyText={sourceConfig.promptsConfig}
                          className="flex-1"
                        >
                          <div
                            className={cn(
                              "flex items-center px-3 py-2 rounded-md border text-sm transition-colors bg-white border-slate-200 text-slate-700 font-medium shadow-sm",
                              "min-w-0",
                            )}
                          >
                            <span className="truncate block w-full font-mono">
                              {sourceConfig.promptsConfig}
                            </span>
                          </div>
                        </HoverHint>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-9 bg-white"
                          onClick={() => void openPromptsDetail()}
                        >
                          查看
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center px-3 py-2 rounded-md border border-slate-200 bg-slate-50 text-sm text-slate-400">
                        未配置
                      </div>
                    )}
                  </div>

                  {/* Table Count */}
                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-slate-500">
                      数据表数量
                    </div>
                    <div className="flex items-center px-3 py-2 rounded-md border border-slate-200 bg-slate-50 text-sm font-medium text-slate-700">
                      {typeof tableCount === "number" ? tableCount : 0}
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-slate-500">
                      代码仓库
                    </div>
                    {sourceConfig?.codeRepo ? (
                      <HoverHint
                        text={`${sourceConfig.codeRepo.path}${sourceConfig.codeRepo.branch ? `#${sourceConfig.codeRepo.branch}` : ""}`}
                        enableCopy
                        copyText={`${sourceConfig.codeRepo.path}${sourceConfig.codeRepo.branch ? `#${sourceConfig.codeRepo.branch}` : ""}`}
                        className="min-w-0"
                      >
                        <div
                          className="flex items-center gap-3 px-3 py-2 rounded-md border bg-white border-slate-200 text-sm text-slate-700 font-medium shadow-sm min-w-0 w-full h-9"
                          title={`${sourceConfig.codeRepo.path}${sourceConfig.codeRepo.branch ? `#${sourceConfig.codeRepo.branch}` : ""}`}
                        >
                          <div className="shrink-0 w-6 h-6 flex items-center justify-center">
                            <BrandIcon slug={toRepoBrandSlug(sourceConfig.codeRepo.type)} size={14} />
                          </div>
                          <span className="truncate block w-full font-mono">
                            {`${sourceConfig.codeRepo.path}${sourceConfig.codeRepo.branch ? `#${sourceConfig.codeRepo.branch}` : ""}`}
                          </span>
                        </div>
                      </HoverHint>
                    ) : (
                      <div className="flex items-center px-3 py-2 rounded-md border border-slate-200 bg-slate-50 text-sm text-slate-400">
                        未配置
                      </div>
                    )}
                  </div>
                </div>

                {/* Row 3 removed, merged into Row 2 */}
              </div>
            </section>

            {/* 业务领域 Section */}
            <section className="space-y-4">
              <h3 className="text-base font-semibold text-slate-900 flex items-center gap-2">
                <Briefcase className="w-4 h-4 text-slate-500" />
                业务领域
              </h3>
              <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm space-y-6">
                <div className="space-y-2">
                  {semanticDomainText ? (
                    <div className="text-sm text-slate-700 leading-relaxed">
                      <Markdown>{semanticDomainText}</Markdown>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-400 text-center italic">
                      未配置业务领域描述
                    </div>
                  )}
                </div>
              </div>
            </section>
          </div>
        ) : tab === "structure" ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-medium text-slate-900 flex items-center gap-2">
                <TableIcon className="w-4 h-4 text-slate-500" />
                数据表结构
              </h3>
              <div className="flex items-center gap-3">
                <Badge
                  variant="secondary"
                  className="bg-white border-slate-200 text-slate-600"
                >
                  {typeof tableCount === "number"
                    ? `${tableCount} Tables`
                    : "Unknown"}
                </Badge>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
              <div className="p-0">
                {!signatureMeta ? (
                  <EmptyState icon={TableIcon} message="暂无表结构信息" />
                ) : (
                  <div className="flex flex-col">
                    {/* Table List (Main Content) */}
                    <div className="flex-1 p-0 overflow-x-auto">
                      <Table>
                        <TableHeader className="sticky top-0 bg-slate-50 z-10 shadow-sm">
                          <TableRow>
                            <TableHead className="w-[60px]"></TableHead>
                            <TableHead className="w-[250px] min-w-[200px]">
                              表名
                            </TableHead>
                            <TableHead className="w-[200px] min-w-[150px]">
                              业务对象
                            </TableHead>
                            <TableHead className="min-w-[400px]">
                              描述
                            </TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {tableList.length > 0 ? (
                            tableList.map((row, i) => {
                              const isExpanded =
                                selectedTable?.tableName === row.tableName;
                              return (
                                <React.Fragment key={i}>
                                  <TableRow
                                    className={cn(
                                      "cursor-pointer transition-colors group",
                                      isExpanded
                                        ? "bg-blue-50/30 border-b-0"
                                        : "hover:bg-slate-50/50",
                                    )}
                                    onClick={() =>
                                      setSelectedTable(isExpanded ? null : row)
                                    }
                                  >
                                    <TableCell className="text-center py-4 pl-4 pr-2">
                                      <div
                                        className={cn(
                                          "w-6 h-6 rounded-md flex items-center justify-center transition-all duration-200",
                                          isExpanded
                                            ? "bg-blue-100 text-blue-600"
                                            : "text-slate-400 group-hover:bg-slate-100 group-hover:text-slate-600",
                                        )}
                                      >
                                        {isExpanded ? (
                                          <ChevronDown className="h-4 w-4" />
                                        ) : (
                                          <ChevronRight className="h-4 w-4" />
                                        )}
                                      </div>
                                    </TableCell>
                                    <TableCell className="font-mono text-sm font-medium text-blue-600 py-4">
                                      {row.tableName}
                                    </TableCell>
                                    <TableCell className="text-sm text-slate-700 py-4">
                                      {row.entity || "-"}
                                    </TableCell>
                                    <TableCell className="text-sm text-slate-500 py-4">
                                      <div title={row.desc}>
                                        {row.desc || "-"}
                                      </div>
                                    </TableCell>
                                  </TableRow>
                                  {isExpanded && (
                                    <TableRow className="bg-blue-50/30 hover:bg-blue-50/30 border-t-0">
                                      <TableCell
                                        colSpan={4}
                                        className="p-0 border-t-0"
                                      >
                                        <div className="px-16 pb-8 pt-0 animate-in slide-in-from-top-1 duration-200">
                                          <div className="p-0 overflow-x-auto">
                                            <Markdown
                                              components={{
                                                ...defaultMarkdownComponents,
                                                table: (props) => (
                                                  <div className="w-full overflow-y-auto border rounded-md border-slate-200 bg-white">
                                                    <table
                                                      className="w-full text-sm text-left border-collapse"
                                                      {...props}
                                                    />
                                                  </div>
                                                ),
                                                thead: (props) => (
                                                  <thead
                                                    className="bg-slate-50 text-slate-700 font-medium"
                                                    {...props}
                                                  />
                                                ),
                                                tbody: (props) => (
                                                  <tbody
                                                    className="divide-y divide-slate-100 bg-white"
                                                    {...props}
                                                  />
                                                ),
                                                tr: (props) => (
                                                  <tr
                                                    className="transition-colors hover:bg-slate-50/50"
                                                    {...props}
                                                  />
                                                ),
                                                th: (props) => (
                                                  <th
                                                    className="py-3 px-4 font-semibold text-slate-700 border-b border-slate-200 whitespace-nowrap"
                                                    {...props}
                                                  />
                                                ),
                                                td: (props) => (
                                                  <td
                                                    className="py-3 px-4 text-slate-600 align-top border-b border-slate-100"
                                                    {...props}
                                                  />
                                                ),
                                                code: (props) => (
                                                  <code
                                                    className="bg-slate-100 rounded px-1 py-0.5 font-mono text-[12px] text-blue-600"
                                                    {...props}
                                                  />
                                                ),
                                              }}
                                            >
                                              {/* Remove the redundant '## Table: ...' title line from the markdown content */}
                                              {row.md
                                                .replace(
                                                  /^\s*## Table:.*$/m,
                                                  "",
                                                )
                                                .trim()}
                                            </Markdown>
                                          </div>
                                        </div>
                                      </TableCell>
                                    </TableRow>
                                  )}
                                </React.Fragment>
                              );
                            })
                          ) : (
                            <TableRow>
                              <TableCell
                                colSpan={4}
                                className="h-24 text-center text-slate-500"
                              >
                                暂无表结构数据
                              </TableCell>
                            </TableRow>
                          )}
                        </TableBody>
                      </Table>
                    </div>

                    {/* Raw JSON Toggle (Bottom Left, Optional) */}
                    {/* We can move this elsewhere or keep it hidden for now as user prefers the list view */}
                  </div>
                )}
              </div>

              {/* Slide-over Panel for Table Details */}
              {/* Removed SidePanel as we are using accordion style now */}
            </div>
          </div>
        ) : tab === "knowledge" ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-medium text-slate-900 flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-slate-500" />
                知识分片
              </h3>
              <div className="flex items-center gap-3">
                <Badge
                  variant="secondary"
                  className="bg-white border-slate-200 text-slate-600"
                >
                  {results.length} Fragments
                </Badge>
              </div>
            </div>

            <div className="space-y-4">
              {isLoadingKnowledge ? (
                <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-20 flex flex-col items-center justify-center text-slate-500">
                  <Loader2 className="w-8 h-8 animate-spin mb-4 text-blue-600" />
                  <p>正在加载知识分片...</p>
                </div>
              ) : results.length === 0 ? (
                <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                  <EmptyState icon={BookOpen} message="暂无知识分片" />
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                  {results.map((r, idx) => {
                    const moduleName =
                      (r.metadata?.module_name as string) || "";
                    const summary =
                      (r.metadata?.summary as string) ||
                      (r.content
                        ? r.content.length > 150
                          ? r.content.slice(0, 150) + "..."
                          : r.content
                        : "No summary available");
                    const sourceType =
                      (r.metadata?.source_type as string) || "";
                    const { preview: summaryPreview, fileCount } =
                      getSummaryPreview(summary);

                    return (
                      <Card
                        key={idx}
                        onClick={() => setSelectedKnowledge(r)}
                        className="hover:shadow-lg hover:-translate-y-1 transition-all duration-300 cursor-pointer group flex flex-col h-[280px] relative overflow-hidden"
                      >
                        {/* Decorative Background Pattern */}
                        <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
                          <Layers className="w-24 h-24 text-blue-600" />
                        </div>

                        {/* Header */}
                        <div className="px-6 pt-6 pb-2 relative z-10">
                          <div className="flex items-center justify-between mb-2">
                            {sourceType ? (
                              <Badge
                                variant="outline"
                                className={cn(
                                  "px-2 py-0.5 text-xs font-medium max-w-[9rem] truncate",
                                  sourceBadgeClass(sourceType),
                                )}
                              >
                                {sourceType}
                              </Badge>
                            ) : (
                              <span />
                            )}
                            <div className="flex items-center gap-2">
                              {fileCount > 0 ? (
                                <span className="text-[11px] text-slate-400 bg-white/70 border border-slate-200 rounded px-2 py-0.5">
                                  {fileCount} files
                                </span>
                              ) : null}
                              <Maximize2 className="w-4 h-4 text-slate-300 group-hover:text-blue-500 transition-colors" />
                            </div>
                          </div>
                          <CardTitle className="text-lg line-clamp-2 leading-tight group-hover:text-blue-600 transition-colors">
                            {moduleName ? moduleName : `分片 #${idx + 1}`}
                          </CardTitle>
                        </div>

                        {/* Body: Summary */}
                        <CardContent className="flex-1 relative z-10 pt-2">
                          <p className="text-sm text-slate-500 leading-relaxed line-clamp-5">
                            {summaryPreview}
                          </p>
                        </CardContent>

                        {/* Footer */}
                        <CardFooter className="mt-auto border-t border-slate-100 flex items-center gap-2 text-xs text-slate-400 relative z-10 bg-white/60 backdrop-blur px-6 py-3">
                          <div className="flex items-center gap-1.5">
                            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400"></div>
                            <span>Ready</span>
                          </div>
                          <div className="flex-1"></div>
                          <span className="font-mono opacity-50">
                            #{idx + 1}
                          </span>
                        </CardFooter>
                      </Card>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Knowledge Detail Dialog */}
            <Dialog
              open={!!selectedKnowledge}
              onOpenChange={(open) => !open && setSelectedKnowledge(null)}
            >
              <DialogContent className="w-[min(96vw,72rem)] max-w-none max-h-[90vh] flex flex-col p-0 overflow-hidden">
                <DialogHeader className="px-6 py-5 border-b border-slate-100 bg-slate-50/50 flex-shrink-0 relative">
                  <div className="flex items-center gap-3 mb-2">
                    {typeof selectedKnowledge?.metadata?.source_type ===
                      "string" &&
                    String(selectedKnowledge.metadata.source_type).trim() ? (
                      <Badge
                        variant="outline"
                        className="bg-blue-50 text-blue-700 border-blue-100"
                      >
                        {String(selectedKnowledge.metadata.source_type).trim()}
                      </Badge>
                    ) : null}
                    <span className="text-xs text-slate-400 font-mono">
                      #{results.indexOf(selectedKnowledge!) + 1}
                    </span>
                  </div>
                  <DialogTitle className="text-xl text-slate-900 pr-8">
                    {typeof selectedKnowledge?.metadata?.module_name ===
                      "string" &&
                    String(selectedKnowledge.metadata.module_name).trim()
                      ? String(selectedKnowledge.metadata.module_name).trim()
                      : `分片 #${results.indexOf(selectedKnowledge!) + 1}`}
                  </DialogTitle>
                  <button
                    className="absolute right-4 top-4 p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-full transition-colors"
                    onClick={() => setSelectedKnowledge(null)}
                  >
                    <X className="w-5 h-5" />
                  </button>
                </DialogHeader>

                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                  {/* Summary Section */}
                  <div className="space-y-3">
                    <h4 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                      <FileText className="w-4 h-4 text-blue-500" />
                      Summary
                    </h4>
                    <div className="text-sm text-slate-700 leading-7 bg-slate-50 p-4 rounded-lg border border-slate-100">
                      <StructuredSummary
                        text={
                          (selectedKnowledge?.metadata?.summary as string) ||
                          (selectedKnowledge?.content
                            ? "未找到 summary，以下为原文内容。"
                            : "暂无内容。")
                        }
                      />
                    </div>
                  </div>

                  {/* Content Section (page_content) */}
                  {selectedKnowledge?.content ? (
                    <div className="space-y-3 pt-4 border-t border-slate-100">
                      <h4 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                        <FileText className="w-4 h-4 text-slate-500" />
                        Detail
                      </h4>
                      <div className="bg-white p-4 rounded-lg border border-slate-200 prose prose-sm max-w-none prose-slate">
                        <Markdown
                          components={{
                            ...defaultMarkdownComponents,
                            a: (props) => (
                              <a className="text-blue-600 hover:underline" target="_blank" rel="noreferrer" {...props} />
                            ),
                          }}
                        >
                          {selectedKnowledge.content}
                        </Markdown>
                      </div>
                    </div>
                  ) : null}

                  {/* Detail Section (if provided by backend metadata) */}
                  {(() => {
                    const md = selectedKnowledge?.metadata as UnknownRecord | undefined
                    const detail =
                      (typeof md?.detail === "string" ? (md.detail as string) : "") ||
                      (typeof md?.details === "string" ? (md.details as string) : "") ||
                      (typeof md?.detail_content === "string" ? (md.detail_content as string) : "")
                    const txt = String(detail || "").trim()
                    if (!txt) return null
                    return (
                      <div className="space-y-3 pt-4 border-t border-slate-100">
                        <h4 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                          <FileText className="w-4 h-4 text-slate-500" />
                          Notes
                        </h4>
                        <div className="text-sm text-slate-700 leading-7 bg-white p-4 rounded-lg border border-slate-200">
                          <StructuredSummary text={txt} />
                        </div>
                      </div>
                    )
                  })()}

                  {/* Metadata Section */}
                  {selectedKnowledge?.metadata && (
                    <div className="space-y-3 pt-4 border-t border-slate-100">
                      <h4 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                        <Info className="w-4 h-4 text-slate-500" />
                        Metadata
                      </h4>
                      <div className="grid grid-cols-2 gap-4 bg-slate-50 rounded-lg p-4 border border-slate-100">
                        {Object.entries(selectedKnowledge.metadata)
                          .filter(
                            ([k]) =>
                              k !== "module_name" &&
                              k !== "summary" &&
                              k !== "source_type",
                          )
                          .map(([k, v]) => (
                            <div key={k} className="space-y-1">
                              <div className="text-xs font-medium text-slate-500 uppercase tracking-wider">
                                {k}
                              </div>
                              <div
                                className="text-sm text-slate-700 font-mono truncate"
                                title={String(v)}
                              >
                                {String(v)}
                              </div>
                            </div>
                          ))}
                      </div>
                    </div>
                  )}
                </div>
              </DialogContent>
            </Dialog>
          </div>
        ) : tab === "graph" ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-medium text-slate-900 flex items-center gap-2">
                <Network className="w-4 h-4 text-slate-500" />
                知识图谱
              </h3>
            </div>
            <KnowledgeGraphView source={knowledgeGraphSource} />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-medium text-slate-900 flex items-center gap-2">
                <Network className="w-4 h-4 text-slate-500" />
                血缘关系
              </h3>
            </div>

            <div className="bg-white rounded-xl border border-slate-200 shadow-sm min-h-[500px] flex items-center justify-center">
              {lineageConsumers.length > 0 ? (
                <div className="w-full h-full p-8 flex flex-col items-center justify-center space-y-8">
                  {/* Visual representation of lineage */}
                  <div className="relative flex flex-col items-center">
                    {/* Current Node (Source) */}
                    <div className="relative z-10 bg-white border border-blue-200 rounded-xl shadow-sm p-4 w-64 text-center">
                      <div className="flex items-center justify-center w-9 h-9 bg-blue-50 text-blue-600 rounded-full mx-auto mb-2">
                        <Database className="w-5 h-5" />
                      </div>
                      <div className="font-semibold text-slate-900 text-sm truncate">
                        {dd.name}
                      </div>
                      <div className="text-xs text-slate-500 mt-1 uppercase tracking-wider">
                        Data Source
                      </div>
                    </div>

                    {/* Connecting Line */}
                    <div className="h-16 w-0.5 bg-slate-300 my-2"></div>

                    {/* Consumers Container */}
                    <div className="flex flex-wrap gap-6 justify-center">
                      {lineageConsumers.map((consumer, idx) => (
                        <div
                          key={`${consumer.kind}/${consumer.namespace}/${consumer.name}/${idx}`}
                          className="relative z-10 bg-white border border-slate-200 rounded-xl shadow-sm p-4 w-64 text-center hover:border-blue-200 hover:shadow-md transition-all cursor-pointer"
                          onClick={() => {
                            if (consumer.kind === "agent") {
                              router.push(
                                `/agents/${encodeURIComponent(consumer.namespace)}/${encodeURIComponent(consumer.name)}`,
                              );
                            }
                          }}
                          title={
                            consumer.kind === "agent" ? "查看智能体" : undefined
                          }
                        >
                          {/* Arrow Pointing to this node */}
                          <div className="absolute -top-4 left-1/2 -translate-x-1/2 w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-b-[8px] border-b-slate-300"></div>

                          <div className="flex items-center justify-center w-9 h-9 bg-purple-50 text-purple-600 rounded-full mx-auto mb-2">
                            <GitBranch className="w-4 h-4" />
                          </div>
                          <div
                            className="font-medium text-slate-800 text-sm truncate"
                            title={consumer.name || "Unknown"}
                          >
                            {consumer.name || "Unknown"}
                          </div>
                          <div className="text-xs text-slate-500 mt-1 flex items-center justify-center gap-1">
                            <span className="bg-slate-100 px-1.5 py-0.5 rounded text-[10px]">
                              {consumer.kind === "agent" ? "Agent" : "Consumer"}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
                <EmptyState
                  icon={Network}
                  message="暂无血缘关系"
                  subMessage="当前数据源暂未被任何 Agent 或服务消费"
                />
              )}
            </div>
          </div>
        )}
      </div>

      {/* Prompts Config Dialog */}
      <Dialog open={isPromptsDialogOpen} onOpenChange={setIsPromptsDialogOpen}>
        <DialogContent className="sm:max-w-[720px] max-h-[90vh] flex flex-col p-0 gap-0 overflow-hidden">
          <DialogHeader className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
            <div className="flex items-center justify-between gap-3">
              <div className="space-y-1">
                <DialogTitle>提示词配置详情</DialogTitle>
                <DialogDescription className="flex items-center gap-2">
                  {sourceConfig?.promptsConfig ? (
                    <>
                      <span className="text-slate-500">ConfigMap：</span>
                      <HoverHint
                        text={sourceConfig.promptsConfig}
                        enableCopy
                        copyText={sourceConfig.promptsConfig}
                      >
                        <span className="font-mono text-slate-800">
                          {sourceConfig.promptsConfig}
                        </span>
                      </HoverHint>
                    </>
                  ) : (
                    <span className="text-slate-500">未配置</span>
                  )}
                </DialogDescription>
              </div>

              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-slate-500 hover:text-slate-900"
                onClick={() => setIsPromptsDialogOpen(false)}
                aria-label="关闭"
                title="关闭"
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
          </DialogHeader>

          <div className="space-y-4 flex-1 min-h-0 overflow-y-auto px-6 py-6">
            {isLoadingPromptsDetail ? (
              <div className="py-14 flex items-center justify-center text-slate-500">
                <Loader2 className="w-6 h-6 animate-spin mr-2 text-blue-600" />
                加载中...
              </div>
            ) : promptsDetailError ? (
              <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {promptsDetailError}
              </div>
            ) : !promptsDetail ? (
              <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                无详情数据
              </div>
            ) : (
              <>
                <div className="text-sm text-slate-600">
                  <span className="text-slate-500">Namespace：</span>
                  <span className="font-mono">
                    {typeof promptsDetail.namespace === "string"
                      ? promptsDetail.namespace
                      : namespace}
                  </span>
                  {typeof promptsDetail.created_at === "string" ? (
                    <>
                      <span className="mx-2 text-slate-300">|</span>
                      <span className="text-slate-500">Created：</span>
                      <span className="font-mono">
                        {promptsDetail.created_at
                          .replace("T", " ")
                          .replace("Z", "")}
                      </span>
                    </>
                  ) : null}
                </div>

                {(() => {
                  const data = promptsDetail.data;
                  const d = isRecord(data)
                    ? (data as Record<string, unknown>)
                    : {};
                  const fewshots =
                    typeof d["fewshots.json"] === "string"
                      ? (d["fewshots.json"] as string)
                      : "";
                  const background =
                    typeof d["background_knowledge.json"] === "string"
                      ? (d["background_knowledge.json"] as string)
                      : "";

                  const prettyJSON = (raw: string) => {
                    const t = (raw || "").trim();
                    if (!t) return "";
                    try {
                      return JSON.stringify(JSON.parse(t), null, 2);
                    } catch {
                      return raw;
                    }
                  };

                  return (
                    <div className="space-y-4">
                      <div className="space-y-1.5">
                        <div className="text-xs font-medium text-slate-500">
                          fewshots.json
                        </div>
                        <pre className="rounded-lg border border-slate-200 bg-slate-50/50 p-4 text-xs font-mono whitespace-pre-wrap break-words max-h-[320px] overflow-auto">
                          {fewshots ? prettyJSON(fewshots) : "（空）"}
                        </pre>
                      </div>

                      <div className="space-y-1.5">
                        <div className="text-xs font-medium text-slate-500">
                          background_knowledge.json
                        </div>
                        <pre className="rounded-lg border border-slate-200 bg-slate-50/50 p-4 text-xs font-mono whitespace-pre-wrap break-words max-h-[320px] overflow-auto">
                          {background ? prettyJSON(background) : "（空）"}
                        </pre>
                      </div>
                    </div>
                  );
                })()}
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function LinkItem({ href, label }: { href: string; label: string }) {
  const router = useRouter();
  return (
    <button
      onClick={() => router.push(href)}
      className="flex items-center hover:text-blue-600 transition-colors"
    >
      {label}
    </button>
  );
}

function StructuredSummary({ text }: { text: string }) {
  const raw = (text || "").trim();
  if (!raw) return <span className="text-slate-500">（空）</span>;

  const re = /===\s*文件:\s*([^=]+?)\s*===/g;
  const matches: Array<{ idx: number; file: string; end: number }> = [];
  for (;;) {
    const m = re.exec(raw);
    if (!m) break;
    matches.push({
      idx: m.index,
      file: (m[1] || "").trim(),
      end: re.lastIndex,
    });
  }

  const normalizeIntro = (s: string) => {
    // Make common patterns easier to read without being too opinionated.
    return s
      .replace(/模块名称[:：]\s*/g, "**模块名称：** ")
      .replace(/模块业务描述[:：]\s*/g, "\n\n**模块业务描述：** ")
      .trim();
  };

  const normalizeBody = (s: string) => {
    return s
      .replace(/^文件摘要[:：]\s*/g, "")
      .replace(/^\s+/, "")
      .trim();
  };

  // No structured markers -> keep original markdown rendering.
  if (matches.length === 0) {
    return <Markdown>{raw}</Markdown>;
  }

  const intro = normalizeIntro(raw.slice(0, matches[0].idx).trim());
  const files = matches.map((m, i) => {
    const start = m.end;
    const end = i + 1 < matches.length ? matches[i + 1].idx : raw.length;
    const body = normalizeBody(raw.slice(start, end));
    return {
      file: m.file || `文件 #${i + 1}`,
      body,
    };
  });

  return (
    <div className="space-y-3">
      {intro ? (
        <div className="prose prose-sm max-w-none prose-slate">
          <Markdown>{intro}</Markdown>
        </div>
      ) : null}

      <div className="space-y-3">
        {files.map((f, idx) => (
          <div
            key={`${f.file}-${idx}`}
            className="rounded-lg border border-slate-200 bg-white overflow-hidden"
          >
            <div className="px-4 py-2.5 border-b border-slate-100 text-xs font-mono text-slate-700 bg-slate-50/50">
              {f.file}
            </div>
            <div className="px-4 py-3 prose prose-sm max-w-none prose-slate">
              <Markdown>{f.body || "（空）"}</Markdown>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function getSummaryPreview(text: string): {
  preview: string;
  fileCount: number;
} {
  const raw = (text || "").trim();
  if (!raw) return { preview: "（空）", fileCount: 0 };

  const re = /===\s*文件:\s*([^=]+?)\s*===/g;
  const matches: Array<{ idx: number; end: number }> = [];
  for (;;) {
    const m = re.exec(raw);
    if (!m) break;
    matches.push({ idx: m.index, end: re.lastIndex });
  }

  const intro = (matches.length > 0 ? raw.slice(0, matches[0].idx) : raw)
    .replace(/模块名称[:：]\s*/g, "")
    .replace(/模块业务描述[:：]\s*/g, "")
    .replace(/\s+/g, " ")
    .trim();

  // Prefer intro if present; otherwise fallback to first file block's first line.
  let preview = intro;
  if (!preview && matches.length > 0) {
    const start = matches[0].end;
    const end = matches.length > 1 ? matches[1].idx : raw.length;
    preview = raw
      .slice(start, end)
      .replace(/^文件摘要[:：]\s*/gm, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  preview = preview || raw.replace(/\s+/g, " ").trim();
  return { preview, fileCount: matches.length };
}

function InfoItem({
  label,
  value,
  fullWidth = false,
  highlight = false,
}: {
  label: string;
  value: string;
  fullWidth?: boolean;
  highlight?: boolean;
}) {
  const isEmpty = !value || value === "-" || (value === "0" && !highlight); // Keep 0 highlighted if it's a stat

  return (
    <div className={cn("space-y-1.5", fullWidth ? "md:col-span-2" : "")}>
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div
        className={cn(
          "flex items-center px-3 py-2 rounded-md border text-sm transition-colors",
          highlight
            ? "bg-blue-50/50 border-blue-100 text-blue-700 font-semibold shadow-sm"
            : isEmpty
              ? "bg-slate-50 border-slate-200 text-slate-400 font-normal"
              : "bg-white border-slate-200 text-slate-700 font-medium shadow-sm",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function EmptyState({
  icon: Icon,
  message,
  subMessage,
}: {
  icon: any;
  message: string;
  subMessage?: string;
}) {
  return (
    <div className="py-20 flex flex-col items-center justify-center text-slate-400">
      <div className="w-16 h-16 rounded-full bg-slate-50 flex items-center justify-center mb-4">
        <Icon className="w-8 h-8 text-slate-300" />
      </div>
      <p className="text-base font-medium text-slate-600">{message}</p>
      {subMessage && <p className="text-sm mt-1 opacity-70">{subMessage}</p>}
    </div>
  );
}
