"use client";

import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import axios from "axios";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useDataSourceDetail } from "@/hooks/use-data-source-detail";
import { DataSourceStructureTab } from "@/components/data-source-detail/structure-tab";
import { formatGpuEnabledLabel, getPdfLoaderLabel } from "@/lib/pdf-loader";
import { getConfigMap } from "@/lib/configmaps-api";
import type { DataSourceResponse, DataDescriptorResponse, ObjectReferenceResponse } from "@/lib/api-types";
import {
  detachDataDescriptorFromSemanticGroups,
  getDataDescriptorDependencyKindLabel,
  listDataDescriptorDependencies,
  type DataDescriptorDependency,
} from "@/lib/data-descriptor-dependencies";
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
  Table as TableIcon,
  Network,
  FileText,
  ChevronRight,
  Home,
  GitBranch,
  ChevronDown,
  Info,
  Briefcase,
  Trash2,
  X,
} from "lucide-react";
import { Markdown, defaultMarkdownComponents } from "@/components/markdown";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { TableWrapper } from "@/components/ui/table-wrapper";
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
import { KnowledgeShardsPanel } from "@/components/knowledge-shards-panel";
import {
  getDataSourceKindLabel,
  isStructuredDataSourceKind,
  normalizeDataSourceKind,
  type DataSourceKind,
} from "@/lib/data-source-kind";

type UnknownRecord = Record<string, unknown>;

const DATA_SOURCE_TABS = [
  { key: "overview", label: "概览" },
  { key: "structure", label: "数据结构" },
  { key: "knowledge", label: "知识分片" },
  { key: "graph", label: "知识图谱" },
  { key: "lineage", label: "血缘关系" },
] as const;
type DataSourceTabKey = (typeof DATA_SOURCE_TABS)[number]["key"];


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
  gpuEnabled?: "yes" | "no";
  pdfLoader?: "auto" | "ocr" | "text";
  overall_phase?: string;
  sources?: DataSourceResponse[];
  source_statuses?: unknown[];
  created_at?: string;
  updated_at?: string;
  consumed_by?: unknown[];
};

type Signature = UnknownRecord;
type SemanticDomain = UnknownRecord;


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

function getCodeRepoFromSource(
  source: DataSourceResponse | null | undefined
): { type: string; path: string; branch?: string } | null {
  const cr = source?.codeRepo;
  const meta = source?.metadata ?? {};
  const type = (
    typeof cr?.codeRepoType === "string" ? cr.codeRepoType :
    typeof meta.codeRepoType === "string" ? meta.codeRepoType :
    typeof source?.type === "string" ? source.type :
    ""
  ).trim();
  const path = (
    typeof cr?.codeRepoPath === "string" ? cr.codeRepoPath :
    typeof meta.codeRepoPath === "string" ? meta.codeRepoPath :
    ""
  ).trim();
  const branch = (
    typeof cr?.codeRepoBranch === "string" ? cr.codeRepoBranch :
    typeof meta.codeRepoBranch === "string" ? meta.codeRepoBranch :
    ""
  ).trim();
  if (!path) return null;
  return { type, path, branch: branch || undefined };
}

function getPrimarySource(dd: DataDescriptor | null): DataSourceResponse | null {
  return Array.isArray(dd?.sources) && dd.sources.length > 0 ? dd.sources[0] : null;
}

function getExtractFileCount(source: DataSourceResponse | null) {
  const files = source?.extract?.files;
  if (!Array.isArray(files)) return null;
  return files
    .map((file) => (typeof file === "string" ? file.trim() : ""))
    .filter(Boolean).length;
}

function getSafeConfigSummary(source: DataSourceResponse | null) {
  const meta = source?.metadata ?? {};
  const safeEntries = Object.entries(meta).filter(
    ([key, value]) => value && !/(password|secret|token|key)/i.test(key),
  );
  if (safeEntries.length === 0) return "-";
  return safeEntries.map(([key, value]) => `${key}: ${value}`).join(" / ");
}

type OverviewConnectionInfo = {
  host: unknown;
  port: unknown;
  database: unknown;
  username: unknown;
};

type OverviewField = {
  label: string;
  value: string;
  highlight?: boolean;
  copyText?: string;
};

function overviewField(
  label: string,
  value: unknown,
  options: { highlight?: boolean; copy?: boolean } = {},
): OverviewField {
  const text = kv(value);
  return {
    label,
    value: text,
    highlight: options.highlight,
    copyText: options.copy && text !== "-" ? text : undefined,
  };
}

function buildOverviewFields({
  kind,
  source,
  connectionInfo,
  tableCount,
  gpuEnabled,
  pdfLoader,
}: {
  kind: DataSourceKind;
  source: DataSourceResponse | null;
  connectionInfo: OverviewConnectionInfo;
  tableCount: number | null;
  gpuEnabled?: "yes" | "no";
  pdfLoader?: "auto" | "ocr" | "text";
}): OverviewField[] {
  const meta = source?.metadata ?? {};
  const fileCount = getExtractFileCount(source);
  const processingFields: OverviewField[] =
    kind === "minio" || kind === "fileserver"
      ? [
          { label: "GPU 加速", value: formatGpuEnabledLabel(gpuEnabled) },
          { label: "PDF 处理", value: getPdfLoaderLabel(pdfLoader) },
        ]
      : [];

  if (kind === "mysql" || kind === "postgres") {
    return [
      overviewField("主机", connectionInfo.host, { copy: true }),
      overviewField("端口", connectionInfo.port, { copy: true }),
      overviewField("数据库", connectionInfo.database, { copy: true }),
      overviewField("用户名", connectionInfo.username, { copy: true }),
      {
        label: "数据表数量",
        value: typeof tableCount === "number" ? String(tableCount) : "-",
        highlight: typeof tableCount === "number",
      },
    ];
  }

  if (kind === "minio") {
    const hostRaw = String(meta.host ?? "")
    const colonIdx = hostRaw.lastIndexOf(":")
    // MinIO stores host:port combined in metadata; split for display when
    // no separate port field exists (backward compat with pre-separation CRDs).
    const displayHost = colonIdx > 0 && !meta.port ? hostRaw.slice(0, colonIdx) : hostRaw
    const displayPort = meta.port ?? (colonIdx > 0 ? hostRaw.slice(colonIdx + 1) : "")
    return [
      overviewField("主机", displayHost, { copy: true }),
      overviewField("端口", displayPort, { copy: true }),
      overviewField("Bucket", meta.bucket, { copy: true }),
      overviewField("Access Key", meta.access_key ?? meta.accessKey, { copy: true }),
      {
        label: "对象范围",
        value: fileCount && fileCount > 0 ? `${fileCount} 个对象` : "整个 Bucket",
      },
      ...processingFields,
    ];
  }

  if (kind === "fileserver") {
    return [
      overviewField("主机", meta.host, { copy: true }),
      overviewField("端口", meta.port, { copy: true }),
      overviewField("根路径", meta.path, { copy: true }),
      {
        label: "文件清单数量",
        value: typeof fileCount === "number" ? String(fileCount) : "-",
        highlight: typeof fileCount === "number",
      },
      ...processingFields,
    ];
  }

  if (kind === "coderepo") {
    const repo = getCodeRepoFromSource(source);
    return [
      overviewField("仓库类型", repo?.type || source?.type, { copy: true }),
      overviewField("仓库地址", repo?.path, { copy: true }),
      overviewField("分支", repo?.branch, { copy: true }),
    ];
  }

  return [
    { label: "来源类型", value: getDataSourceKindLabel(kind) },
    overviewField("主机", meta.host, { copy: true }),
    overviewField("端口", meta.port, { copy: true }),
    { label: "配置摘要", value: getSafeConfigSummary(source) },
  ];
}

const DATASOURCE_DEPENDENT_COLUMNS = [
  { id: "resource", size: 240 },
  { id: "namespace", size: 112 },
  { id: "actions", size: 176 },
] as const

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

  const [tab, setTab] = useState<DataSourceTabKey>("overview");

  const {
    dd: ddRaw,
    signature,
    semanticDomain,
    lineageConsumers,
    descriptorError,
    isLoading,
    isNotFound,
    isLoadError,
    refreshAll,
  } = useDataSourceDetail(namespace, name, {
    includeAgentLineage: tab === "lineage",
  });

  const dd = useMemo(() => {
    if (!ddRaw) return null;
    return {
      name: ddRaw.name,
      namespace: ddRaw.namespace ?? namespace,
      descriptor_type: ddRaw.descriptor_type,
      gpuEnabled: ddRaw.gpuEnabled,
      pdfLoader: ddRaw.pdfLoader,
      overall_phase: ddRaw.overall_phase,
      sources: ddRaw.sources,
      source_statuses: ddRaw.source_statuses,
      created_at: ddRaw.created_at,
      updated_at: ddRaw.updated_at,
      consumed_by: ddRaw.consumed_by,
    } as DataDescriptor;
  }, [ddRaw, namespace]);

  const [dependentResources, setDependentResources] = useState<DataDescriptorDependency[]>([]);
  const [showDependencyDialog, setShowDependencyDialog] = useState(false);
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const [checkingDependency, setCheckingDependency] = useState(false);
  const [detachingGroupId, setDetachingGroupId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const [selectedTable, setSelectedTable] = useState<{
    tableName: string;
    md: string;
    entity: string;
    desc: string;
  } | null>(null);


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
  const primarySource = useMemo(() => getPrimarySource(dd), [dd]);
  const dataSourceKind = useMemo(
    () => normalizeDataSourceKind(dd?.descriptor_type, primarySource?.type),
    [dd?.descriptor_type, primarySource?.type],
  );
  const isStructuredSource = isStructuredDataSourceKind(dataSourceKind);

  const connectionInfo = useMemo(() => {
    // 1. Try to get connection info from dd.sources[0].metadata
    if (primarySource) {
      const meta = primarySource.metadata;
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
  }, [primarySource, signature]);

  const signatureMeta = useMemo(() => {
    if (!isRecord(signature)) return null;
    const v = signature.metadata_content;
    return isRecord(v) ? (v as UnknownRecord) : null;
  }, [signature]);

  const sourceConfig = useMemo(() => {
    const s = primarySource;
    if (!s) return null;
    return {
      promptsConfig: s?.prompts?.configMapName,
      codeRepo: getCodeRepoFromSource(s ?? null),
    };
  }, [primarySource]);

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

  const overviewFields = useMemo(
    () =>
      buildOverviewFields({
        kind: dataSourceKind,
        source: primarySource,
        connectionInfo,
        tableCount,
        gpuEnabled: dd?.gpuEnabled,
        pdfLoader: dd?.pdfLoader,
      }),
    [connectionInfo, dataSourceKind, dd?.gpuEnabled, dd?.pdfLoader, primarySource, tableCount],
  );
  const structureTitle = isStructuredSource ? "数据表结构" : "结构化 Schema";
  const structureCountLabel = isStructuredSource
    ? typeof tableCount === "number"
      ? `${tableCount} Tables`
      : "Unknown"
    : "N/A";
  const structureEmptyMessage = isStructuredSource
    ? "暂无表结构信息"
    : "暂无结构化 schema 信息";
  const structureEmptyRowMessage = isStructuredSource
    ? "暂无表结构数据"
    : "暂无结构化 schema 数据";

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

  useEffect(() => {
    if (!descriptorError) return
    if (axios.isAxiosError(descriptorError) && descriptorError.response?.status === 404) return
    toast.error("加载数据源详情失败")
  }, [descriptorError])

  const checkDependencies = async () => {
    setCheckingDependency(true);
    try {
      return await listDataDescriptorDependencies(namespace, name);
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

  const refreshDeleteDependencies = async () => {
    const deps = await checkDependencies();
    setDependentResources(deps);
    if (deps.length === 0) {
      setShowDependencyDialog(false);
      setIsDeleteOpen(true);
    }
    return deps;
  };

  const handleDetachFromGroup = async (groupId: string) => {
    if (!name || detachingGroupId) return;
    setDetachingGroupId(groupId);
    try {
      const count = await detachDataDescriptorFromSemanticGroups(namespace, name, { groupIds: [groupId] });
      if (count === 0) {
        toast.error("未找到可移除的语义组关联");
        return;
      }
      toast.success("已从语义组移除");
      await refreshDeleteDependencies();
    } catch (err) {
      console.error("detach from semantic group failed", err);
      const e = err as { response?: { data?: { message?: string } } };
      toast.error(e.response?.data?.message || "从语义组移除失败");
    } finally {
      setDetachingGroupId(null);
    }
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
        ) : isLoadError ? (
          <div className="rounded-lg border border-dashed border-line-hover p-12 text-center">
            <Database className="mx-auto h-12 w-12 text-content-muted" />
            <h3 className="mt-2 text-sm font-semibold text-content">
              加载失败
            </h3>
            <p className="mt-1 text-sm text-content-muted">
              无法获取数据源详情，请检查网络或稍后重试。
            </p>
            <div className="mt-6 flex items-center justify-center gap-3">
              <Button variant="outline" onClick={() => void refreshAll()}>
                重试
              </Button>
              <Button variant="outline" onClick={() => router.back()}>
                返回列表
              </Button>
            </div>
          </div>
        ) : isNotFound || !dd ? (
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
                <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
                  {overviewFields.map((field) => (
                    <InfoItem
                      key={field.label}
                      label={field.label}
                      value={field.value}
                      highlight={field.highlight}
                      copyText={field.copyText}
                    />
                  ))}

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
                </div>
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
          <DataSourceStructureTab
            isStructuredSource={isStructuredSource}
            structureTitle={structureTitle}
            structureCountLabel={structureCountLabel}
            structureEmptyMessage={structureEmptyMessage}
            structureEmptyRowMessage={structureEmptyRowMessage}
            hasSignatureMeta={Boolean(signatureMeta)}
            tableList={tableList}
            selectedTableName={selectedTable?.tableName ?? null}
            onSelectTable={(row) => setSelectedTable(row)}
            markdownComponents={structureSchemaMarkdownComponents}
          />
        ) : tab === "knowledge" ? (
          <KnowledgeShardsPanel namespace={namespace} name={name} />
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
              该数据源正在被以下 {dependentResources.length} 个资源使用，无法删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="mt-4 space-y-3 px-6">
            <TableWrapper className="max-h-[320px] overflow-auto rounded-md">
              <Table storageKey="datasource-dependent-resources" columns={[...DATASOURCE_DEPENDENT_COLUMNS]}>
                <TableHeader>
                  <TableRow className="bg-surface-muted">
                    <TableHead columnId="resource">资源</TableHead>
                    <TableHead columnId="namespace">命名空间</TableHead>
                    <TableHead columnId="actions" className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dependentResources.map((resource, idx) => (
                    <TableRow key={`${resource.kind}/${resource.id ?? resource.namespace}/${resource.name}/${idx}`}>
                      <TableCell columnId="resource" className="font-medium whitespace-normal break-all">
                        {getDataDescriptorDependencyKindLabel(resource.kind)} / {resource.name}
                      </TableCell>
                      <TableCell columnId="namespace" className="text-content-muted">{resource.namespace}</TableCell>
                      <TableCell columnId="actions" className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          {resource.kind === "group" && resource.id ? (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={Boolean(detachingGroupId)}
                              onClick={() => void handleDetachFromGroup(resource.id!)}
                              className="text-red-600 hover:text-red-700 whitespace-nowrap cursor-pointer"
                            >
                              {detachingGroupId === resource.id ? "移除中…" : "从语义组移除"}
                            </Button>
                          ) : null}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setShowDependencyDialog(false);
                              if (resource.kind === "agent") {
                                router.push(`/agents/${encodeURIComponent(resource.namespace)}/${encodeURIComponent(resource.name)}`);
                              } else if (resource.kind === "group") {
                                router.push(`/semantic-groups/${encodeURIComponent(resource.id ?? resource.name)}`);
                              } else if (resource.kind === "dac") {
                                router.push(`/agents/${encodeURIComponent(resource.namespace)}/${encodeURIComponent(resource.name)}`);
                              }
                            }}
                            className="text-cta hover:text-cta/90 whitespace-nowrap cursor-pointer"
                          >
                            查看详情 →
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableWrapper>
            <div className="text-sm text-content">
              若仅被语义组引用，可先「从语义组移除」再删除；若还被智能体引用，请先处理智能体依赖。
            </div>
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


function InfoItem({
  label,
  value,
  fullWidth = false,
  highlight = false,
  copyText,
}: {
  label: string;
  value: string;
  fullWidth?: boolean;
  highlight?: boolean;
  copyText?: string;
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
        {copyText ? (
          <HoverHint text={value} copyText={copyText} enableCopy className="w-full">
            <span className="truncate block w-full">{value}</span>
          </HoverHint>
        ) : (
          value
        )}
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
