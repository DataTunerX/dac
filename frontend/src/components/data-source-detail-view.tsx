"use client";

import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import axios from "axios";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { getDescriptor } from "@/lib/descriptors-api";
import { listAgentsAll } from "@/lib/agents-api";
import { getConfigMap } from "@/lib/configmaps-api";
import type { DataSourceResponse, DataDescriptorResponse, ObjectReferenceResponse } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { RbacWrapper } from "@/components/rbac";
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
  Trash2,
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
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { HoverHint } from "@/components/hover-hint";
import { KnowledgeGraphView } from "@/components/knowledge-graph-view";

type UnknownRecord = Record<string, unknown>;

const DATA_SOURCE_TABS = [
  { key: "overview", label: "概览" },
  { key: "structure", label: "数据结构" },
  { key: "knowledge", label: "知识分片" },
  { key: "graph", label: "知识图谱" },
  { key: "lineage", label: "血缘关系" },
] as const;
type DataSourceTabKey = (typeof DATA_SOURCE_TABS)[number]["key"];

function sourceBadgeClass(sourceType: string) {
  const t = (sourceType || "").toLowerCase();
  if (t.includes("gitee")) return "bg-red-50 text-red-700 border-red-100";
  if (t.includes("github"))
    return "bg-surface-muted text-content border-line";
  if (t.includes("gitlab"))
    return "bg-orange-50 text-orange-700 border-orange-100";
  if (t.includes("mysql")) return "bg-sky-50 text-sky-700 border-sky-100";
  if (t.includes("postgres"))
    return "bg-indigo-50 text-indigo-700 border-indigo-100";
  if (t.includes("clickhouse"))
    return "bg-amber-50 text-amber-700 border-amber-100";
  return "bg-cta/10 text-cta border-cta/20";
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
    badge: "bg-surface-muted border-line text-content",
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

type DependentResource = {
  kind: "agent" | "dac";
  name: string;
  namespace: string;
};

function kv(v: unknown): string {
  if (v === null || v === undefined) return "-";
  if (typeof v === "string") return v.trim() || "-";
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return "-";
}

function getCodeRepoFromSource(
  source: DataSourceResponse | null | undefined
): { type: string; path: string; branch?: string } | null {
  const cr = source?.codeRepo;
  const type = (typeof cr?.codeRepoType === "string" ? cr.codeRepoType : "").trim();
  const path = (typeof cr?.codeRepoPath === "string" ? cr.codeRepoPath : "").trim();
  const branch = (typeof cr?.codeRepoBranch === "string" ? cr.codeRepoBranch : "").trim();
  if (!path) return null;
  return { type, path, branch: branch || undefined };
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
  const [dependentResources, setDependentResources] = useState<DependentResource[]>([]);
  const [showDependencyDialog, setShowDependencyDialog] = useState(false);
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const [checkingDependency, setCheckingDependency] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const [tab, setTab] = useState<DataSourceTabKey>("overview");
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
      const s = dd.sources[0] as DataSourceResponse | undefined;
      const meta = s?.metadata;
      if (meta && typeof meta === "object" && !Array.isArray(meta)) {
        return {
          host: (meta as Record<string, unknown>).host,
          port: (meta as Record<string, unknown>).port,
          database: (meta as Record<string, unknown>).database,
          username: (meta as Record<string, unknown>).user,
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
    const s = dd.sources[0] as DataSourceResponse | undefined;
    return {
      promptsConfig: s?.prompts?.configMapName,
      codeRepo: getCodeRepoFromSource(s ?? null),
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
      const data = await getConfigMap(namespace, cmName);
      setPromptsDetail((data?.data ?? {}) as UnknownRecord);
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
      return typeof obj === "object" && obj !== null ? (obj as UnknownRecord) : null;
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

  type TableSchemaItem = string | { table_name?: string; table_schema?: string };
  const tableList = useMemo(() => {
    if (!Array.isArray(signatureMeta?.tables_schema_md_list)) return [];
    return signatureMeta.tables_schema_md_list.map((item: TableSchemaItem) => {
      const tableName = typeof item === "string" ? "" : (item?.table_name ?? "");
      const md = typeof item === "string" ? item : (item?.table_schema ?? "");
      const detail = tablesDetailMap[tableName] || {};
      return {
        tableName,
        md,
        entity: detail.entity || "-",
        desc: detail.desc || "-",
      };
    });
  }, [signatureMeta?.tables_schema_md_list, tablesDetailMap]);

  const structureSchemaMarkdownComponents = useMemo(
    () => ({
      ...defaultMarkdownComponents,
      table: (props: React.ComponentProps<"table">) => (
        <div className="w-full overflow-x-auto overflow-y-auto rounded-lg border border-line bg-surface shadow-sm">
          <table className="w-full text-sm text-left border-collapse" {...props} />
        </div>
      ),
      thead: (props: React.ComponentProps<"thead">) => (
        <thead className="bg-surface-muted text-content font-medium" {...props} />
      ),
      tbody: (props: React.ComponentProps<"tbody">) => (
        <tbody className="bg-surface [&>tr]:border-b [&>tr]:border-line last:[&>tr]:border-b-0" {...props} />
      ),
      tr: (props: React.ComponentProps<"tr">) => (
        <tr className="transition-colors hover:bg-surface-active/80" {...props} />
      ),
      th: (props: React.ComponentProps<"th">) => (
        <th className="py-3 px-4 font-semibold text-content border-b border-line whitespace-nowrap" {...props} />
      ),
      td: (props: React.ComponentProps<"td">) => (
        <td className="py-3 px-4 text-content align-top border-b border-line" {...props} />
      ),
      code: (props: React.ComponentProps<"code">) => (
        <code className="bg-surface-muted rounded px-1 py-0.5 font-mono text-[12px] text-content" {...props} />
      ),
    }),
    [],
  );

  const knowledgeDetailMarkdownComponents = useMemo(
    () => ({
      ...defaultMarkdownComponents,
      a: (props: React.ComponentProps<"a">) => (
        <a className="text-cta hover:underline cursor-pointer" target="_blank" rel="noreferrer" {...props} />
      ),
    }),
    [],
  );

  const load = async () => {
    if (!name) return;
    setIsLoading(true);
    try {
      setDD(null);
      setSignature(null);
      setSemanticDomain(null);
      setAgentConsumers([]);
      const desc = await getDescriptor(namespace, name);
      setDD({
        name: desc.name,
        namespace: desc.namespace ?? namespace,
        descriptor_type: desc.descriptor_type,
        overall_phase: desc.overall_phase,
        sources: desc.sources,
        source_statuses: desc.source_statuses,
        created_at: desc.created_at,
        updated_at: desc.updated_at,
        consumed_by: desc.consumed_by,
      });

      try {
        const { items } = await listAgentsAll();
        const deps: LineageConsumer[] = [];
        for (const a of items) {
          const an = a.name ?? "";
          const ans = a.namespace ?? "default";
          if (!an) continue;
          let hit = false;
          const sel = a.dataPolicy?.sourceNameSelector ?? [];
          if (sel.some((x) => x === name)) hit = true;
          const ads = a.activeDataDescriptors ?? [];
          if (ads.some((x) => x.name === name && (x.namespace ?? "default") === namespace)) hit = true;
          if (hit) deps.push({ kind: "agent", name: an, namespace: ans });
        }
        const uniq = new Map<string, LineageConsumer>();
        for (const d of deps) {
          const k = `${d.kind}/${d.namespace}/${d.name}`;
          if (!uniq.has(k)) uniq.set(k, d);
        }
        setAgentConsumers(Array.from(uniq.values()));
      } catch (e) {
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
      ? (dd.consumed_by as ObjectReferenceResponse[])
          .map((c: ObjectReferenceResponse) => {
            const nm = c.name ?? "";
            if (!nm) return null;
            return {
              kind: "unknown",
              name: nm,
              namespace: c.namespace ?? "default",
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

  const refreshAll = async () => {
    await Promise.all([load(), loadSignature(), loadSemanticDomain()]);
  };

  const checkDependencies = async () => {
    setCheckingDependency(true);
    try {
      const deps: DependentResource[] = [];

      try {
        const desc = await getDescriptor(namespace, name);
        const consumed = desc.consumed_by ?? [];
        for (const c of consumed) {
          const depName = c.name;
          if (!depName) continue;
          deps.push({
            kind: "dac",
            name: depName,
            namespace: c.namespace ?? "default",
          });
        }
      } catch {
        // Ignore consumed_by lookup failures and continue with agent scan.
      }

      try {
        const { items } = await listAgentsAll();
        for (const agent of items) {
          const agentName = agent.name ?? "";
          const agentNamespace = agent.namespace ?? "default";
          if (!agentName) continue;

          let hit = false;
          const selectedSources = agent.dataPolicy?.sourceNameSelector ?? [];
          if (selectedSources.some((source) => source === name)) hit = true;

          const activeDescriptors = agent.activeDataDescriptors ?? [];
          if (activeDescriptors.some((item) => item.name === name && (item.namespace ?? "default") === namespace)) {
            hit = true;
          }

          if (hit) {
            deps.push({ kind: "agent", name: agentName, namespace: agentNamespace });
          }
        }
      } catch {
        // Ignore agents lookup failures and keep best-effort consumed_by result.
      }

      const uniqueDependencies = new Map<string, DependentResource>();
      for (const dep of deps) {
        const key = `${dep.kind}/${dep.namespace}/${dep.name}`;
        if (!uniqueDependencies.has(key)) {
          uniqueDependencies.set(key, dep);
        }
      }

      return Array.from(uniqueDependencies.values());
    } catch (err) {
      console.error("check dd dependencies failed", err);
      toast.error("检查依赖关系失败");
      return [];
    } finally {
      setCheckingDependency(false);
    }
  };

  const openDeleteDialog = async () => {
    if (!name || checkingDependency) return;
    const deps = await checkDependencies();
    if (deps.length > 0) {
      setDependentResources(deps);
      setShowDependencyDialog(true);
      return;
    }
    setIsDeleteOpen(true);
  };

  const handleDelete = async () => {
    if (!name || isDeleting) return;
    setIsDeleting(true);
    try {
      await api.delete(`/namespaces/${encodeURIComponent(namespace)}/descriptors/${encodeURIComponent(name)}`);
      toast.success("数据源已删除");
      router.push("/datasources");
    } catch (err) {
      console.error("delete datasource failed", err);
      const e = err as { response?: { data?: { message?: string } } };
      toast.error(e.response?.data?.message || "删除失败");
    } finally {
      setIsDeleting(false);
      setIsDeleteOpen(false);
    }
  };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6">
      {/* Header Section Group */}
      <div className="space-y-4">
        {/* Breadcrumb & Actions */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => router.back()}
              className="-ml-2 h-8 px-2 text-content-muted hover:text-content"
            >
              <ArrowLeft className="w-4 h-4 mr-1" />
              返回
            </Button>
            <nav
              className="flex items-center text-sm text-content-muted min-w-0"
              aria-label="Breadcrumb"
            >
              <LinkItem href="/datasources" label="数据管理" />
              <ChevronRight className="w-4 h-4 mx-2 text-content-muted shrink-0" />
              <span className="font-mono text-content-muted shrink-0">
                {namespace}
              </span>
              <ChevronRight className="w-4 h-4 mx-2 text-content-muted shrink-0" />
              <span className="font-medium text-content truncate">
                {name}
              </span>
            </nav>
          </div>
        </div>

        {/* Title & Meta */}
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-content">{title}</h1>
              <Badge variant="outline" className="font-mono text-xs bg-surface">
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
              <div className="text-sm text-content-muted">
                更新于 <span className="font-mono">{updatedAtText}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              onClick={() => void refreshAll()}
              disabled={isLoading}
              aria-label="刷新"
            >
              <RefreshCw className={cn("w-4 h-4", isLoading && "animate-spin")} />
            </Button>
            <RbacWrapper requiredRole="admin">
              <Button
                variant="outline"
                onClick={() => void openDeleteDialog()}
                disabled={isLoading || checkingDependency || isDeleting}
                className="bg-surface hover:bg-red-50 hover:text-red-600 hover:border-red-200"
              >
                {checkingDependency || isDeleting ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <Trash2 className="w-4 h-4 mr-2" />
                )}
                删除
              </Button>
            </RbacWrapper>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-line">
        <div className="flex gap-6">
          {DATA_SOURCE_TABS.map((t) => {
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={cn(
                  "pb-3 text-sm font-medium border-b-2 transition-colors cursor-pointer",
                  active
                    ? "border-cta text-content"
                    : "border-transparent text-content-muted hover:text-content hover:border-line-hover",
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
          <div className="flex flex-col items-center justify-center py-20 text-content-muted">
            <Loader2 className="w-8 h-8 animate-spin mb-4 text-cta" />
            <p>正在加载数据源详情…</p>
          </div>
        ) : !dd ? (
          <div className="rounded-lg border border-dashed border-line-hover p-12 text-center">
            <Database className="mx-auto h-12 w-12 text-content-muted" />
            <h3 className="mt-2 text-sm font-semibold text-content">
              未找到数据源
            </h3>
            <p className="mt-1 text-sm text-content-muted">
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
              <h3 className="text-base font-semibold text-content flex items-center gap-2">
                <Info className="w-4 h-4 text-content-muted" />
                基础信息
              </h3>
              <div className="bg-surface rounded-lg border border-line p-5 shadow-sm space-y-5">
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
                    <div className="text-xs font-medium text-content-muted">
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
                              "flex items-center px-3 py-2 rounded-md border text-sm transition-colors bg-surface border-line text-content font-medium shadow-sm",
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
                          className="h-9 bg-surface"
                          onClick={() => void openPromptsDetail()}
                        >
                          查看
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center px-3 py-2 rounded-md border border-line bg-surface-muted text-sm text-content-muted">
                        未配置
                      </div>
                    )}
                  </div>

                  {/* Table Count */}
                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-content-muted">
                      数据表数量
                    </div>
                    <div className="flex items-center px-3 py-2 rounded-md border border-line bg-surface-muted text-sm font-medium text-content">
                      {typeof tableCount === "number" ? tableCount : 0}
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <div className="text-xs font-medium text-content-muted">
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
                          className="flex items-center gap-3 px-3 py-2 rounded-md border bg-surface border-line text-sm text-content font-medium shadow-sm min-w-0 w-full h-9"
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
                      <div className="flex items-center px-3 py-2 rounded-md border border-line bg-surface-muted text-sm text-content-muted">
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
              <h3 className="text-base font-semibold text-content flex items-center gap-2">
                <Briefcase className="w-4 h-4 text-content-muted" />
                业务领域
              </h3>
              <div className="bg-surface rounded-xl border border-line p-6 shadow-sm space-y-6">
                <div className="space-y-2">
                  {semanticDomainText ? (
                    <div className="text-sm text-content leading-relaxed">
                      <Markdown>{semanticDomainText}</Markdown>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-dashed border-line bg-surface-muted p-4 text-sm text-content-muted text-center italic">
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
              <h3 className="text-base font-medium text-content flex items-center gap-2">
                <TableIcon className="w-4 h-4 text-content-muted" />
                数据表结构
              </h3>
              <div className="flex items-center gap-3">
                <Badge
                  variant="secondary"
                  className="bg-surface border-line text-content"
                >
                  {typeof tableCount === "number"
                    ? `${tableCount} Tables`
                    : "Unknown"}
                </Badge>
              </div>
            </div>

            <div className="bg-surface rounded-xl border border-line shadow-sm overflow-hidden">
              <div className="p-0">
                {!signatureMeta ? (
                  <EmptyState icon={TableIcon} message="暂无表结构信息" />
                ) : (
                  <div className="flex flex-col">
                    {/* Table List (Main Content) */}
                    <div className="flex-1 p-0 overflow-x-auto">
                      <Table>
                        <TableHeader className="sticky top-0 bg-surface-muted z-10 shadow-sm">
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
                                        ? "bg-surface-muted border-b-0"
                                        : "hover:bg-surface-muted/50",
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
                                            ? "bg-surface-active text-content"
                                            : "text-content-muted group-hover:bg-surface-muted group-hover:text-content",
                                        )}
                                      >
                                        {isExpanded ? (
                                          <ChevronDown className="h-4 w-4" />
                                        ) : (
                                          <ChevronRight className="h-4 w-4" />
                                        )}
                                      </div>
                                    </TableCell>
                                    <TableCell className="font-mono text-sm font-medium text-content py-4">
                                      {row.tableName}
                                    </TableCell>
                                    <TableCell className="text-sm text-content py-4">
                                      {row.entity || "-"}
                                    </TableCell>
                                    <TableCell className="text-sm text-content-muted py-4">
                                      <div title={row.desc}>
                                        {row.desc || "-"}
                                      </div>
                                    </TableCell>
                                  </TableRow>
                                  {isExpanded && (
                                    <TableRow className="bg-surface-muted hover:bg-surface-muted border-t-0 border-b border-line">
                                      <TableCell
                                        colSpan={4}
                                        className="p-0 border-t-0 bg-surface-muted"
                                      >
                                        <div className="px-16 pb-8 pt-0 animate-in slide-in-from-top-1 duration-200 bg-surface-muted">
                                          <div className="p-0 overflow-x-auto">
                                            <Markdown
                                              components={structureSchemaMarkdownComponents}
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
                                className="h-24 text-center text-content-muted"
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
              <h3 className="text-base font-medium text-content flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-content-muted" />
                知识分片
              </h3>
              <div className="flex items-center gap-3">
                <Badge
                  variant="secondary"
                  className="bg-surface border-line text-content"
                >
                  {results.length} Fragments
                </Badge>
              </div>
            </div>

            <div className="space-y-4">
              {isLoadingKnowledge ? (
                <div className="bg-surface rounded-xl border border-line shadow-sm p-20 flex flex-col items-center justify-center text-content-muted">
                  <Loader2 className="w-8 h-8 animate-spin mb-4 text-cta" />
                  <p>正在加载知识分片…</p>
                </div>
              ) : results.length === 0 ? (
                <div className="bg-surface rounded-xl border border-line shadow-sm overflow-hidden">
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
                          <Layers className="w-24 h-24 text-cta" />
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
                                <span className="text-[11px] text-content-muted bg-surface/70 border border-line rounded px-2 py-0.5">
                                  {fileCount} files
                                </span>
                              ) : null}
                              <Maximize2 className="w-4 h-4 text-content-muted group-hover:text-cta transition-colors" />
                            </div>
                          </div>
                          <CardTitle className="text-lg line-clamp-2 leading-tight group-hover:text-cta transition-colors">
                            {moduleName ? moduleName : `分片 #${idx + 1}`}
                          </CardTitle>
                        </div>

                        {/* Body: Summary */}
                        <CardContent className="flex-1 relative z-10 pt-2">
                          <p className="text-sm text-content-muted leading-relaxed line-clamp-5">
                            {summaryPreview}
                          </p>
                        </CardContent>

                        {/* Footer */}
                        <CardFooter className="mt-auto border-t border-line flex items-center gap-2 text-xs text-content-muted relative z-10 bg-surface/60 backdrop-blur px-6 py-3">
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
                <DialogHeader className="px-6 py-5 border-b border-line bg-surface-muted/50 flex-shrink-0 relative">
                  <div className="flex items-center gap-3 mb-2">
                    {typeof selectedKnowledge?.metadata?.source_type ===
                      "string" &&
                    String(selectedKnowledge.metadata.source_type).trim() ? (
                      <Badge
                        variant="outline"
                        className="bg-cta/10 text-cta border-cta/20"
                      >
                        {String(selectedKnowledge.metadata.source_type).trim()}
                      </Badge>
                    ) : null}
                    <span className="text-xs text-content-muted font-mono">
                      #{results.indexOf(selectedKnowledge!) + 1}
                    </span>
                  </div>
                  <DialogTitle className="text-xl text-content pr-8">
                    {typeof selectedKnowledge?.metadata?.module_name ===
                      "string" &&
                    String(selectedKnowledge.metadata.module_name).trim()
                      ? String(selectedKnowledge.metadata.module_name).trim()
                      : `分片 #${results.indexOf(selectedKnowledge!) + 1}`}
                  </DialogTitle>
                  <button
                    type="button"
                    className="absolute right-4 top-4 p-2 text-content-muted hover:text-content hover:bg-surface-muted rounded-full transition-colors cursor-pointer"
                    onClick={() => setSelectedKnowledge(null)}
                    aria-label="关闭"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </DialogHeader>

                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                  {/* Summary Section */}
                  <div className="space-y-3">
                    <h4 className="text-sm font-semibold text-content flex items-center gap-2">
                      <FileText className="w-4 h-4 text-cta" />
                      Summary
                    </h4>
                    <div className="text-sm text-content leading-7 bg-surface-muted p-4 rounded-lg border border-line">
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
                    <div className="space-y-3 pt-4 border-t border-line">
                      <h4 className="text-sm font-semibold text-content flex items-center gap-2">
                        <FileText className="w-4 h-4 text-content-muted" />
                        Detail
                      </h4>
                      <div className="bg-surface p-4 rounded-lg border border-line prose prose-sm max-w-none prose-slate">
                        <Markdown
                          components={knowledgeDetailMarkdownComponents}
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
                      <div className="space-y-3 pt-4 border-t border-line">
                        <h4 className="text-sm font-semibold text-content flex items-center gap-2">
                          <FileText className="w-4 h-4 text-content-muted" />
                          Notes
                        </h4>
                        <div className="text-sm text-content leading-7 bg-surface p-4 rounded-lg border border-line">
                          <StructuredSummary text={txt} />
                        </div>
                      </div>
                    )
                  })()}

                  {/* Metadata Section */}
                  {selectedKnowledge?.metadata && (
                    <div className="space-y-3 pt-4 border-t border-line">
                      <h4 className="text-sm font-semibold text-content flex items-center gap-2">
                        <Info className="w-4 h-4 text-content-muted" />
                        Metadata
                      </h4>
                      <div className="grid grid-cols-2 gap-4 bg-surface-muted rounded-lg p-4 border border-line">
                        {Object.entries(selectedKnowledge.metadata)
                          .filter(
                            ([k]) =>
                              k !== "module_name" &&
                              k !== "summary" &&
                              k !== "source_type",
                          )
                          .map(([k, v]) => (
                            <div key={k} className="space-y-1">
                              <div className="text-xs font-medium text-content-muted uppercase tracking-wider">
                                {k}
                              </div>
                              <div
                                className="text-sm text-content font-mono truncate"
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
              <h3 className="text-base font-medium text-content flex items-center gap-2">
                <Network className="w-4 h-4 text-content-muted" />
                知识图谱
              </h3>
            </div>
            <KnowledgeGraphView source={knowledgeGraphSource} />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-medium text-content flex items-center gap-2">
                <Network className="w-4 h-4 text-content-muted" />
                血缘关系
              </h3>
            </div>

            <div className="bg-surface rounded-xl border border-line shadow-sm min-h-[500px] flex items-center justify-center">
              {lineageConsumers.length > 0 ? (
                <div className="w-full h-full p-8 flex flex-col items-center justify-center space-y-8">
                  {/* Visual representation of lineage */}
                  <div className="relative flex flex-col items-center">
                    {/* Current Node (Source) */}
                    <div className="relative z-10 bg-surface border border-cta/30 rounded-xl shadow-sm p-4 w-64 text-center">
                      <div className="flex items-center justify-center w-9 h-9 bg-cta/10 text-cta rounded-full mx-auto mb-2">
                        <Database className="w-5 h-5" />
                      </div>
                      <div className="font-semibold text-content text-sm truncate">
                        {dd.name}
                      </div>
                      <div className="text-xs text-content-muted mt-1 uppercase tracking-wider">
                        Data Source
                      </div>
                    </div>

                    {/* Connecting Line */}
                    <div className="h-16 w-0.5 bg-surface-active my-2"></div>

                    {/* Consumers Container */}
                    <div className="flex flex-wrap gap-6 justify-center">
                      {lineageConsumers.map((consumer, idx) => (
                        <div
                          key={`${consumer.kind}/${consumer.namespace}/${consumer.name}/${idx}`}
                          className="relative z-10 bg-surface border border-line rounded-xl shadow-sm p-4 w-64 text-center hover:border-cta/30 hover:shadow-md transition-all cursor-pointer"
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

                          <div className="flex items-center justify-center w-9 h-9 bg-sky-50 text-sky-600 rounded-full mx-auto mb-2">
                            <GitBranch className="w-4 h-4" />
                          </div>
                          <div
                            className="font-medium text-content text-sm truncate"
                            title={consumer.name || "Unknown"}
                          >
                            {consumer.name || "Unknown"}
                          </div>
                          <div className="text-xs text-content-muted mt-1 flex items-center justify-center gap-1">
                            <span className="bg-surface-muted px-1.5 py-0.5 rounded text-[10px]">
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
          <DialogHeader className="px-6 py-4 border-b border-line bg-surface-muted/50">
            <div className="flex items-center justify-between gap-3">
              <div className="space-y-1">
                <DialogTitle>提示词配置详情</DialogTitle>
                <DialogDescription className="flex items-center gap-2">
                  {sourceConfig?.promptsConfig ? (
                    <>
                      <span className="text-content-muted">ConfigMap：</span>
                      <HoverHint
                        text={sourceConfig.promptsConfig}
                        enableCopy
                        copyText={sourceConfig.promptsConfig}
                      >
                        <span className="font-mono text-content">
                          {sourceConfig.promptsConfig}
                        </span>
                      </HoverHint>
                    </>
                  ) : (
                    <span className="text-content-muted">未配置</span>
                  )}
                </DialogDescription>
              </div>

              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-content-muted hover:text-content"
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
              <div className="py-14 flex items-center justify-center text-content-muted">
                <Loader2 className="w-6 h-6 animate-spin mr-2 text-cta" />
                加载中…
              </div>
            ) : promptsDetailError ? (
              <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                {promptsDetailError}
              </div>
            ) : !promptsDetail ? (
              <div className="rounded-md border border-line bg-surface-muted p-4 text-sm text-content-muted">
                无详情数据
              </div>
            ) : (
              <>
                <div className="text-sm text-content">
                  <span className="text-content-muted">Namespace：</span>
                  <span className="font-mono">
                    {typeof promptsDetail.namespace === "string"
                      ? promptsDetail.namespace
                      : namespace}
                  </span>
                  {typeof promptsDetail.created_at === "string" ? (
                    <>
                      <span className="mx-2 text-content-muted">|</span>
                      <span className="text-content-muted">Created：</span>
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
                        <div className="text-xs font-medium text-content-muted">
                          fewshots.json
                        </div>
                        <pre className="rounded-lg border border-line bg-surface-muted/50 p-4 text-xs font-mono whitespace-pre-wrap break-words max-h-[320px] overflow-auto">
                          {fewshots ? prettyJSON(fewshots) : "（空）"}
                        </pre>
                      </div>

                      <div className="space-y-1.5">
                        <div className="text-xs font-medium text-content-muted">
                          background_knowledge.json
                        </div>
                        <pre className="rounded-lg border border-line bg-surface-muted/50 p-4 text-xs font-mono whitespace-pre-wrap break-words max-h-[320px] overflow-auto">
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

      <AlertDialog open={showDependencyDialog} onOpenChange={setShowDependencyDialog}>
        <AlertDialogContent className="w-[min(96vw,56rem)] max-w-4xl">
          <AlertDialogHeader>
            <AlertDialogTitle>无法删除 - 存在依赖关系</AlertDialogTitle>
            <AlertDialogDescription>
              该数据源正在被以下 {dependentResources.length} 个 DAC 资源使用，无法删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="mt-4 space-y-3 px-6">
            <div className="max-h-[320px] w-full overflow-auto rounded-md border border-line">
              <Table className="w-full table-fixed">
                <TableHeader>
                  <TableRow className="bg-surface-muted">
                    <TableHead className="w-auto">资源</TableHead>
                    <TableHead className="w-28">命名空间</TableHead>
                    <TableHead className="w-28 text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dependentResources.map((resource, idx) => (
                    <TableRow key={`${resource.kind}/${resource.namespace}/${resource.name}/${idx}`}>
                      <TableCell className="font-medium whitespace-normal break-all">
                        {resource.kind} / {resource.name}
                      </TableCell>
                      <TableCell className="text-content-muted">{resource.namespace}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setShowDependencyDialog(false);
                            if (resource.kind === "agent") {
                              router.push(`/agents/${encodeURIComponent(resource.namespace)}/${encodeURIComponent(resource.name)}`);
                            } else {
                              router.push(`/datasources/${encodeURIComponent(resource.namespace)}/${encodeURIComponent(resource.name)}`);
                            }
                          }}
                          className="text-cta hover:text-cta/90 whitespace-nowrap cursor-pointer"
                        >
                          查看详情 →
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="text-sm text-content">请先解除这些资源对该数据源的依赖，然后再删除。</div>
          </div>
          <AlertDialogFooter>
            <AlertDialogAction onClick={() => setShowDependencyDialog(false)}>知道了</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={isDeleteOpen} onOpenChange={setIsDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除数据源？</AlertDialogTitle>
            <AlertDialogDescription>
              此操作将永久删除该数据源（{namespace}/{name}）。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete} className="bg-red-600 hover:bg-red-700" disabled={isDeleting}>
              {isDeleting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

    </div>
  );
}

function LinkItem({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="flex items-center hover:text-cta transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cta focus-visible:ring-offset-2 rounded cursor-pointer"
    >
      {label}
    </Link>
  );
}

function StructuredSummary({ text }: { text: string }) {
  const raw = (text || "").trim();
  if (!raw) return <span className="text-content-muted">（空）</span>;

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
            className="rounded-lg border border-line bg-surface overflow-hidden"
          >
            <div className="px-4 py-2.5 border-b border-line text-xs font-mono text-content bg-surface-muted/50">
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
      <div className="text-xs font-medium text-content-muted">{label}</div>
      <div
        className={cn(
          "flex items-center px-3 py-2 rounded-md border text-sm transition-colors",
          highlight
            ? "bg-cta/10 border-cta/20 text-cta font-semibold shadow-sm"
            : isEmpty
              ? "bg-surface-muted border-line text-content-muted font-normal"
              : "bg-surface border-line text-content font-medium shadow-sm",
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
  icon: React.ComponentType<{ className?: string }>;
  message: string;
  subMessage?: string;
}) {
  return (
    <div className="py-20 flex flex-col items-center justify-center text-content-muted">
      <div className="w-16 h-16 rounded-full bg-surface-muted flex items-center justify-center mb-4">
        <Icon className="w-8 h-8 text-content-muted" />
      </div>
      <p className="text-base font-medium text-content">{message}</p>
      {subMessage ? <p className="text-sm mt-1 opacity-70">{subMessage}</p> : null}
    </div>
  );
}
