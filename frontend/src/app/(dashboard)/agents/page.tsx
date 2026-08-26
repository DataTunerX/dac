"use client";

import dynamic from "next/dynamic";
import {
  memo,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";
import { listAllAgentContainers } from "@/lib/agents-api";
import { apiFetcherWithParams, apiFetcher } from "@/lib/swr";
import { AGENTS_LIST_KEY } from "@/lib/swr-keys";
import { filterListByQuery } from "@/lib/filter-list-by-query";
import { RbacButton, RbacWrapper } from "@/components/rbac";
import { StatusBadge } from "@/components/status-badge";
import { ListPageSearch } from "@/components/list-page-search";
import {
  ListViewModeToggle,
  type ListViewMode,
} from "@/components/list-view-mode-toggle";
import { Button } from "@/components/ui/button";
import { PaginationBar } from "@/components/pagination-bar";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
  Plus,
  Trash2,
  Loader2,
  RefreshCw,
  Database,
  Bot,
  Layers,
  Eye,
} from "lucide-react";
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
import type { CreateAgentPayload } from "@/components/agent-forms";

const CreateAgentDialog = dynamic(
  () =>
    import("@/components/agent-forms").then((m) => ({
      default: m.CreateAgentDialog,
    })),
  { ssr: false },
);
import { toast } from "sonner";
import { ListSkeleton } from "@/components/ui/skeleton";

type UnknownRecord = Record<string, unknown>;

const AGENTS_LIST_COLUMNS = [
  { id: "name", size: 220 },
  { id: "namespace", size: 140 },
  { id: "type", size: 100 },
  { id: "status", size: 110 },
  { id: "binding", size: 220 },
  { id: "created", size: 160 },
  { id: "actions", size: 120 },
] as const

function isRecord(v: unknown): v is UnknownRecord {
  return typeof v === "object" && v !== null;
}

function asString(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

function formatCreatedAt(input?: string): string {
  if (!input) return "-";
  const date = new Date(input);
  if (!Number.isFinite(date.getTime())) return "-";
  return date.toLocaleString("zh-CN", { hour12: false });
}

function getItemField(
  item: UnknownRecord,
  key: string,
  legacyKey: string,
): unknown {
  return (item[key] as unknown) ?? (item[legacyKey] as unknown);
}

export interface Agent {
  id: string;
  name: string;
  namespace: string;
  description: string;
  dataSource: string;
  /** UI type key: descriptor | semantic-group | skill */
  dataSourceType: "descriptor" | "semantic-group" | "skill" | string;
  semanticGroupID?: string;
  plannerLLM?: string;
  expertLLM?: string;
  createdAt?: string;
  status: "AVAILABLE" | "CREATING" | "UNKNOWN";
  raw: unknown;
}

function agentTypeLabel(dataSourceType: string): string {
  if (dataSourceType === "skill") return "通用智能体";
  if (dataSourceType === "semantic-group") return "业务智能体";
  return "数据智能体";
}

function deriveAgentStatus(agent: UnknownRecord): Agent["status"] {
  const conds = agent.conditions;
  if (Array.isArray(conds)) {
    const available = conds.find(
      (c) => isRecord(c) && asString(c.type) === "Available",
    );
    if (
      available &&
      isRecord(available) &&
      asString(available.status) === "True"
    )
      return "AVAILABLE";
    const creating = conds.find(
      (c) => isRecord(c) && asString(c.type) === "Creating",
    );
    if (creating && isRecord(creating) && asString(creating.status) === "True")
      return "CREATING";
  }
  return "UNKNOWN";
}

function mapRawToAgent(
  item: UnknownRecord,
  getItemField: (item: UnknownRecord, key: string, legacyKey: string) => unknown,
): Agent | null {
  const name = asString(item.name) ?? "";
  const namespace = asString(item.namespace) ?? "default";
  const agentCardRaw = getItemField(item, "agentCard", "agent_card");
  const agentCard = isRecord(agentCardRaw) ? agentCardRaw : undefined;
  const displayName = asString(agentCard?.name) ?? name;
  const description = asString(agentCard?.description) ?? "";
  const dataPolicyRaw = getItemField(item, "dataPolicy", "data_policy");
  const dataPolicy = isRecord(dataPolicyRaw) ? dataPolicyRaw : undefined;
  const selectorRaw = dataPolicy?.sourceNameSelector;
  const selector = Array.isArray(selectorRaw)
    ? selectorRaw.filter((s): s is string => typeof s === "string")
    : [];
  const semanticGroupID =
    asString((dataPolicy as UnknownRecord | undefined)?.semanticGroupID) ||
    asString((dataPolicy as UnknownRecord | undefined)?.semantic_group_id);
  const dataSourceTypeRaw =
    asString((dataPolicy as UnknownRecord | undefined)?.dataSourceType) ||
    asString((dataPolicy as UnknownRecord | undefined)?.data_source_type);
  const dacType =
    (asString(item.dacType) || asString(item.dac_type) || "").toLowerCase();
  const skillPolicyRaw = getItemField(item, "skillPolicy", "skill_policy");
  const skillPolicy = isRecord(skillPolicyRaw) ? skillPolicyRaw : undefined;
  const skillRefsRaw = skillPolicy?.skills;
  const skillNames = Array.isArray(skillRefsRaw)
    ? skillRefsRaw
        .map((s) => (isRecord(s) ? asString(s.name) : undefined))
        .filter((n): n is string => Boolean(n))
    : [];
  // Prefer dacType=skill so empty dataPolicy does not fall through as "descriptor"
  const dsType =
    dacType === "skill"
      ? "skill"
      : dataSourceTypeRaw === "SemanticGroup" || Boolean(semanticGroupID)
        ? "semantic-group"
        : "descriptor";
  const modelRaw = item.model;
  const model = isRecord(modelRaw) ? modelRaw : undefined;
  const plannerLLM =
    asString((model as UnknownRecord | undefined)?.plannerLLM) ||
    asString((model as UnknownRecord | undefined)?.planner_llm);
  const expertLLM =
    asString((model as UnknownRecord | undefined)?.expertLLM) ||
    asString((model as UnknownRecord | undefined)?.expert_llm);
  if (!name) return null;
  return {
    id: name,
    name: displayName,
    namespace,
    description,
    dataSource:
      dsType === "skill"
        ? skillNames.length > 0
          ? skillNames.join(", ")
          : "-"
        : selector.length > 0
          ? selector.join(", ")
          : "-",
    dataSourceType: dsType,
    semanticGroupID,
    plannerLLM,
    expertLLM,
    createdAt:
      asString(item.createdAt) ??
      asString(item.created_at) ??
      asString(item.creationTimestamp) ??
      asString(item.creation_timestamp),
    status: deriveAgentStatus(item),
    raw: item,
  };
}

function agentSearchText(
  a: Agent,
  sgNameById: Record<string, string>,
): string {
  const sg =
    a.dataSourceType === "semantic-group"
      ? sgNameById[a.semanticGroupID || ""] || a.semanticGroupID || ""
      : a.dataSource;
  return [
    a.name,
    a.id,
    a.namespace,
    a.description,
    sg,
    a.plannerLLM,
    a.expertLLM,
    agentTypeLabel(a.dataSourceType),
  ]
    .filter(Boolean)
    .join(" ");
}

type AgentCardProps = {
  agent: Agent;
  sgNameById: Record<string, string>;
  isLoadingSg: boolean;
  onOpen: (agent: Agent) => void;
  onDelete: (id: string, ns: string) => void;
};

const AgentCard = memo(function AgentCard({
  agent: a,
  sgNameById,
  isLoadingSg,
  onOpen,
  onDelete,
}: AgentCardProps) {
  return (
    <Card
      className="group relative cursor-pointer gap-0 overflow-hidden py-0 transition-all duration-200 hover:border-line-hover hover:shadow-md [content-visibility:auto]"
      onClick={() => onOpen(a)}
    >
      <CardHeader className="bg-surface-muted/50 p-4 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[#c7d2fe] bg-[#e0e7ff] text-[#4f46e5]">
              <Bot className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <CardTitle
                className="line-clamp-1 break-all pr-1 text-sm font-semibold"
                title={a.name}
              >
                {a.name}
              </CardTitle>
              <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                <span className="font-mono text-content-muted">{a.namespace}</span>
                <span className="text-content-muted">·</span>
                <span className="truncate font-mono text-content-muted" title={a.id}>
                  {a.id}
                </span>
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <StatusBadge status={a.status} />
            <RbacWrapper requiredPermission="agent:delete">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-content-muted hover:bg-red-50 hover:text-red-600"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(a.id, a.namespace);
                }}
                title="删除"
                aria-label="删除"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </RbacWrapper>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 px-4 pb-4 pt-3">
        <p className="min-h-[32px] line-clamp-2 text-xs leading-relaxed text-content">
          {a.description || "暂无描述"}
        </p>
        <div
          className="flex items-center gap-2"
          title={
            a.dataSourceType === "semantic-group"
              ? sgNameById[a.semanticGroupID || ""] ||
                a.semanticGroupID ||
                "-"
              : a.dataSource
          }
        >
          {a.dataSourceType === "semantic-group" ? (
            <Layers className="h-3.5 w-3.5 shrink-0 text-content-muted" />
          ) : a.dataSourceType === "skill" ? (
            <Bot className="h-3.5 w-3.5 shrink-0 text-content-muted" />
          ) : (
            <Database className="h-3.5 w-3.5 shrink-0 text-content-muted" />
          )}
          <span className="truncate text-xs text-content">
            {a.dataSourceType === "semantic-group"
              ? sgNameById[a.semanticGroupID || ""] ||
                (a.semanticGroupID ? (isLoadingSg ? "加载中…" : "-") : "-")
              : a.dataSource || "-"}
          </span>
        </div>
        <div
          className="truncate font-mono text-[11px] text-content-muted"
          title={
            a.dataSourceType === "skill"
              ? a.expertLLM || a.plannerLLM || "-"
              : [a.plannerLLM, a.expertLLM].filter(Boolean).join(" / ")
          }
        >
          {a.dataSourceType === "skill"
            ? a.expertLLM || a.plannerLLM || "-"
            : `${a.plannerLLM || "-"}${
                a.expertLLM && a.expertLLM !== a.plannerLLM ? ` / ${a.expertLLM}` : ""
              }`}
        </div>
        <div className="absolute bottom-3 right-3">
          {a.dataSourceType === "semantic-group" ? (
            <Badge
              variant="secondary"
              className="h-5 border-indigo-100 bg-indigo-50 px-2 text-[10px] font-normal text-indigo-700"
            >
              业务智能体
            </Badge>
          ) : a.dataSourceType === "skill" ? (
            <Badge
              variant="secondary"
              className="h-5 border-emerald-100 bg-emerald-50 px-2 text-[10px] font-normal text-emerald-700"
            >
              通用智能体
            </Badge>
          ) : (
            <Badge
              variant="secondary"
              className="h-5 border-line bg-surface-muted px-2 text-[10px] font-normal text-content"
            >
              数据智能体
            </Badge>
          )}
        </div>
      </CardContent>
    </Card>
  );
});

export default function AgentsPage() {
  const router = useRouter();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleteNamespace, setDeleteNamespace] = useState<string>("default");
  const [isDeleting, setIsDeleting] = useState(false);
  const [pageSize, setPageSize] = useState(20);
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<ListViewMode>("list");
  const [typeFilter, setTypeFilter] = useState<
    "all" | "descriptor" | "semantic-group" | "skill"
  >("semantic-group");
  const [namespaceFilter, setNamespaceFilter] = useState<string>("all");

  const deferredSearch = useDeferredValue(searchQuery);

  const {
    data: rawAgentsList,
    error: agentsError,
    isLoading,
    mutate: mutateAgents,
  } = useSWR(AGENTS_LIST_KEY, () => listAllAgentContainers());

  const sgKey = useMemo(
    () => ["/semantic-groups", { offset: 0, limit: 2000 }] as const,
    [],
  );

  const { data: sgData, isLoading: isLoadingSg } = useSWR<{ items?: unknown[] }>(
    sgKey,
    apiFetcherWithParams,
  );

  const { data: nsData } = useSWR<{ items?: unknown[] }>(
    "/namespaces",
    apiFetcher,
  );

  const namespaces = useMemo(() => {
    const items = nsData?.items ?? [];
    return items
      .map((it) => (isRecord(it) ? asString(it.name) : undefined))
      .filter((n): n is string => Boolean(n));
  }, [nsData]);

  const sgNameById = useMemo(() => {
    const r = sgData as unknown;
    const raw = isRecord(r) ? r : {};
    const items = Array.isArray(raw.items) ? raw.items : [];
    const next: Record<string, string> = {};
    for (const x0 of items) {
      const x = isRecord(x0) ? x0 : {};
      const id = asString(x.id) || "";
      const name = asString(x.group_name) || "";
      if (id) next[id] = name || id;
    }
    return next;
  }, [sgData]);

  const agents = useMemo(() => {
    const list = rawAgentsList ?? [];
    return list
      .map((item) =>
        mapRawToAgent(item as unknown as UnknownRecord, getItemField),
      )
      .filter((a): a is Agent => a !== null);
  }, [rawAgentsList]);

  useEffect(() => {
    if (agentsError) toast.error("获取智能体列表失败");
  }, [agentsError]);

  const { filtered, paged, totalCount, totalPages } = useMemo(() => {
    const searched = filterListByQuery(agents, deferredSearch, (a) =>
      agentSearchText(a, sgNameById),
    );
    const byType =
      typeFilter === "all"
        ? searched
        : searched.filter((a) => a.dataSourceType === typeFilter);
    const nextFiltered =
      namespaceFilter === "all"
        ? byType
        : byType.filter((a) => a.namespace === namespaceFilter);
    const count = nextFiltered.length;
    const pages = Math.max(1, Math.ceil(count / pageSize));
    const safePage = Math.min(page, pages);
    const start = (safePage - 1) * pageSize;
    return {
      filtered: nextFiltered,
      paged: nextFiltered.slice(start, start + pageSize),
      totalCount: count,
      totalPages: pages,
    };
  }, [agents, deferredSearch, typeFilter, namespaceFilter, sgNameById, page, pageSize]);

  useEffect(() => {
    setPage(1);
  }, [deferredSearch, typeFilter, namespaceFilter]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const fetchData = () => mutateAgents();

  const handleCreate = async (data: CreateAgentPayload) => {
    try {
      const skills = (data.skills || [])
        .map((s) => {
          const id = (s.id || "").trim() || (s.name || "").trim();
          const name = (s.name || "").trim() || id;
          const description = (s.description || "").trim();
          const tags = (s.tags || "")
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean);
          const examples = (s.examples || "")
            .split("\n")
            .map((t) => t.trim())
            .filter(Boolean);
          return { id, name, description, tags, examples };
        })
        .filter((s) => s.id && s.name);

      // skill 分支：dacType=skill，dataPolicy 置空，绑定写入 skillPolicy
      if (data.dataSourceType === "skill") {
        // 运行时使用 expertLLM；plannerLLM 同步同值以满足 CRD 必填
        const llm = data.expertModel || data.plannerModel;
        const payload = {
          name: data.name.toLowerCase().replace(/\s+/g, "-"),
          namespace: data.namespace,
          dacType: "skill",
          agentCard: {
            name: data.name,
            description: data.description,
            skills,
          },
          dataPolicy: {
            dataSourceType: "",
            semanticGroupID: "",
            sourceNameSelector: [],
          },
          skillPolicy: data.skillPolicy ?? { skills: [] },
          model: {
            plannerLLM: llm,
            expertLLM: llm,
            embedding: "embedding-config",
          },
          expertAgentMaxSteps: data.expertAgentMaxSteps || "10",
          orchestratorAgentMaxLoops: data.orchestratorAgentMaxLoops || "2",
        };
        await api.post(`/namespaces/${data.namespace}/agents`, payload);
        toast.success("智能体创建成功");
        fetchData();
        return;
      }

      const isSemanticGroup = data.dataSourceType === "semantic-group";
      const dacType = isSemanticGroup ? "normal" : "ds";
      const dataSourceType = isSemanticGroup ? "SemanticGroup" : "SemanticDomain";

      const payload = {
        name: data.name.toLowerCase().replace(/\s+/g, "-"),
        namespace: data.namespace,
        dacType,
        agentCard: {
          name: data.name,
          description: data.description,
          skills,
        },
        dataPolicy: {
          dataSourceType,
          semanticGroupID: isSemanticGroup ? data.dataSourceId : undefined,
          sourceNameSelector: !isSemanticGroup ? [data.dataSourceId] : undefined,
        },
        ...(isSemanticGroup
          ? { skillPolicy: data.skillPolicy ?? { skills: [] } }
          : {}),
        model: {
          plannerLLM: data.plannerModel,
          expertLLM: data.expertModel,
          embedding: "embedding-config",
        },
        expertAgentMaxSteps:
          data.expertAgentMaxSteps || (isSemanticGroup ? "1" : "2"),
        orchestratorAgentMaxLoops:
          data.orchestratorAgentMaxLoops || (isSemanticGroup ? "1" : "0"),
      };

      await api.post(`/namespaces/${data.namespace}/agents`, payload);
      toast.success("智能体创建成功");
      fetchData();
    } catch (err: unknown) {
      console.error("Create agent failed", err);
      const e = err as { response?: { data?: { message?: string } } };
      toast.error(e.response?.data?.message || "创建失败，请检查配置");
    }
  };

  const handleDelete = async () => {
    if (!deleteId || isDeleting) return;
    setIsDeleting(true);
    try {
      await api.delete(`/namespaces/${deleteNamespace}/agents/${deleteId}`);
      toast.success("智能体已删除");
      setDeleteId(null);
      const remaining = Math.max(0, totalCount - 1);
      const nextTotalPages = Math.max(1, Math.ceil(remaining / pageSize));
      if (page > nextTotalPages) setPage(nextTotalPages);
      await fetchData();
    } catch (err: unknown) {
      console.error("Delete failed", err);
      const e = err as { response?: { data?: { message?: string } } };
      toast.error(e.response?.data?.message || "删除失败");
    } finally {
      setIsDeleting(false);
    }
  };

  const openDelete = useCallback((id: string, ns: string) => {
    setDeleteId(id);
    setDeleteNamespace(ns);
  }, []);

  const openDetail = useCallback(
    (agent: Agent) => {
      router.push(
        `/agents/${encodeURIComponent(agent.namespace)}/${encodeURIComponent(agent.id)}`,
      );
    },
    [router],
  );

  const clearFilters = () => {
    setSearchQuery("");
    setTypeFilter("semantic-group");
    setNamespaceFilter("all");
  };

  const hasActiveFilters =
    searchQuery.trim() !== "" || typeFilter !== "semantic-group" || namespaceFilter !== "all";

  const showEmpty = !isLoading && agents.length === 0;
  const showNoMatch = !isLoading && agents.length > 0 && filtered.length === 0;

  return (
    <div className="space-y-6 p-4 sm:space-y-8 sm:p-6 lg:p-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm font-medium text-content">
          <span className="font-semibold text-content">智能体</span>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <ListPageSearch
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="搜索名称、命名空间、描述…"
          />
          <Select
            value={namespaceFilter}
            onValueChange={setNamespaceFilter}
          >
            <SelectTrigger className="h-9 w-[min(10rem,40vw)] bg-surface">
              <SelectValue placeholder="命名空间" />
            </SelectTrigger>
            <SelectContent align="end">
              <SelectItem value="all">全部命名空间</SelectItem>
              {namespaces.map((ns) => (
                <SelectItem key={ns} value={ns}>
                  {ns}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <ListViewModeToggle value={viewMode} onChange={setViewMode} />
          <Select
            value={typeFilter}
            onValueChange={(v) =>
              setTypeFilter(v as "all" | "descriptor" | "semantic-group" | "skill")
            }
          >
            <SelectTrigger className="h-9 w-[min(10rem,40vw)] bg-surface">
              <SelectValue placeholder="类型" />
            </SelectTrigger>
            <SelectContent align="end">
              <SelectItem value="semantic-group">业务智能体</SelectItem>
              <SelectItem value="descriptor">数据智能体</SelectItem>
              <SelectItem value="skill">通用智能体</SelectItem>
              <SelectItem value="all">全部类型</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon"
            onClick={fetchData}
            disabled={isLoading}
            aria-label="刷新"
          >
            <RefreshCw
              className={`h-4 w-4 ${isLoading ? "animate-spin" : ""}`}
            />
          </Button>
          <RbacButton
            className="flex items-center gap-2"
            onClick={() => setIsCreateOpen(true)}
            requiredPermission="agent:create"
          >
            <Plus className="h-4 w-4" />
            新建智能体
          </RbacButton>
        </div>
      </div>

      {isLoading && agents.length === 0 ? (
        <ListSkeleton items={viewMode === "grid" ? 6 : 8} />
      ) : showEmpty ? (
        <div className="flex h-[400px] items-center justify-center rounded-md border border-dashed border-line-hover bg-surface-muted">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Bot className="h-10 w-10 opacity-20" />
            <p>暂无智能体</p>
            <RbacWrapper requiredPermission="agent:create">
              <Button
                variant="link"
                className="text-content-muted underline underline-offset-4 hover:text-content"
                onClick={() => setIsCreateOpen(true)}
              >
                创建一个?
              </Button>
            </RbacWrapper>
          </div>
        </div>
      ) : showNoMatch ? (
        <div className="flex h-[400px] items-center justify-center rounded-md border border-dashed border-line-hover bg-surface-muted">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Layers className="h-10 w-10 opacity-20" />
            <p>暂无匹配的智能体</p>
            {hasActiveFilters ? (
              <Button
                variant="link"
                className="text-content-muted underline underline-offset-4 hover:text-content"
                onClick={clearFilters}
              >
                清除搜索与筛选
              </Button>
            ) : null}
          </div>
        </div>
      ) : viewMode === "list" ? (
        <TableWrapper>
          <Table storageKey="agents-list" columns={[...AGENTS_LIST_COLUMNS]}>
            <TableHeader>
              <TableRow className="bg-surface-muted">
                <TableHead columnId="name">名称</TableHead>
                <TableHead columnId="namespace" className="whitespace-nowrap">命名空间</TableHead>
                <TableHead columnId="type" className="whitespace-nowrap">类型</TableHead>
                <TableHead columnId="status" className="whitespace-nowrap">状态</TableHead>
                <TableHead columnId="binding">
                  {typeFilter === "descriptor"
                    ? "关联数据源"
                    : typeFilter === "skill"
                      ? "关联技能"
                      : typeFilter === "all"
                        ? "关联对象"
                        : "关联语义组"}
                </TableHead>
                <TableHead columnId="created" className="whitespace-nowrap">创建时间</TableHead>
                <TableHead columnId="actions" className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paged.map((a) => {
                const binding =
                  a.dataSourceType === "semantic-group"
                    ? sgNameById[a.semanticGroupID || ""] ||
                      a.semanticGroupID ||
                      "-"
                    : a.dataSource || "-";
                return (
                  <TableRow
                    key={`${a.namespace}/${a.id}`}
                    className="cursor-pointer hover:bg-surface-muted/60 [content-visibility:auto]"
                    onClick={() => openDetail(a)}
                  >
                    <TableCell columnId="name" className="max-w-[14rem] font-medium">
                      <div className="flex min-w-0 items-center gap-2">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-[#c7d2fe] bg-[#e0e7ff] text-[#4f46e5]">
                          <Bot className="h-4 w-4" />
                        </div>
                        <span className="truncate" title={a.name}>
                          {a.name}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell columnId="namespace" className="font-mono text-sm text-content-muted">
                      {a.namespace}
                    </TableCell>
                    <TableCell columnId="type">
                      {a.dataSourceType === "semantic-group" ? (
                        <Badge
                          variant="secondary"
                          className="border-indigo-100 bg-indigo-50 font-normal text-indigo-700"
                        >
                          业务
                        </Badge>
                      ) : a.dataSourceType === "skill" ? (
                        <Badge
                          variant="secondary"
                          className="border-emerald-100 bg-emerald-50 font-normal text-emerald-700"
                        >
                          通用
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="font-normal">
                          数据
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell columnId="status">
                      <StatusBadge status={a.status} />
                    </TableCell>
                    <TableCell columnId="binding" className="max-w-[16rem] truncate text-sm text-content" title={binding}>
                      {binding}
                    </TableCell>
                    <TableCell
                      columnId="created"
                      className="whitespace-nowrap tabular-nums text-sm text-content-muted"
                    >
                      {formatCreatedAt(a.createdAt)}
                    </TableCell>
                    <TableCell columnId="actions" className="text-right">
                      <div
                        className="inline-flex items-center gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => openDetail(a)}
                          title="查看"
                          aria-label="查看"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        <RbacWrapper requiredPermission="agent:delete">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="text-red-600 hover:text-red-700"
                            onClick={() => openDelete(a.id, a.namespace)}
                            title="删除"
                            aria-label="删除"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </RbacWrapper>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableWrapper>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {paged.map((a) => (
            <AgentCard
              key={`${a.namespace}/${a.id}`}
              agent={a}
              sgNameById={sgNameById}
              isLoadingSg={isLoadingSg}
              onOpen={openDetail}
              onDelete={openDelete}
            />
          ))}
        </div>
      )}

      <PaginationBar
        total={totalCount}
        page={page}
        pageSize={pageSize}
        isLoading={isLoading}
        onPageChange={setPage}
        onPageSizeChange={setPageSize}
      />

      <CreateAgentDialog
        open={isCreateOpen}
        onOpenChange={setIsCreateOpen}
        onSubmit={handleCreate}
      />

      <AlertDialog
        open={!!deleteId}
        onOpenChange={(open) => !open && setDeleteId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除？</AlertDialogTitle>
            <AlertDialogDescription>
              删除后将无法恢复。该操作只删除智能体，不影响底层数据源与配置。
              {deleteId ? (
                <span className="mt-2 block font-mono text-xs text-content">
                  {deleteNamespace}/{deleteId}
                </span>
              ) : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={isDeleting}
              className="bg-red-600 hover:bg-red-700"
            >
              {isDeleting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
