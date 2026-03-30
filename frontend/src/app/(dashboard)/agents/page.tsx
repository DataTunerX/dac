"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";
import { apiFetcherWithParams } from "@/lib/swr";
import { getUserRole } from "@/lib/auth"; // Import auth helper
import { RbacButton, RbacWrapper } from "@/components/rbac";
import { StatusBadge } from "@/components/status-badge";
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
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Plus, Trash2, Loader2, RefreshCw, Database, Bot, Layers } from "lucide-react";
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
import {
  CreateAgentDialog,
  CreateAgentPayload,
} from "@/components/agent-forms";
import { toast } from "sonner"
import { ListSkeleton } from "@/components/ui/skeleton";

type UnknownRecord = Record<string, unknown>;

function isRecord(v: unknown): v is UnknownRecord {
  return typeof v === "object" && v !== null;
}

function asString(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

interface Agent {
  id: string; // name
  name: string;
  namespace: string;
  description: string;
  dataSource: string;
  dataSourceType: string;
  semanticGroupID?: string;
  plannerLLM?: string;
  expertLLM?: string;
  status: "AVAILABLE" | "CREATING" | "UNKNOWN";
  raw: unknown;
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

export default function AgentsPage() {
  const router = useRouter();
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleteNamespace, setDeleteNamespace] = useState<string>("default");
  const [isDeleting, setIsDeleting] = useState(false);
  const [pageSize, setPageSize] = useState(20);
  const [page, setPage] = useState(1);
  const [typeFilter, setTypeFilter] = useState<
    "all" | "descriptor" | "semantic-group"
  >("all");

  const getItemField = (item: UnknownRecord, key: string, legacyKey: string) =>
    (item[key] as unknown) ?? (item[legacyKey] as unknown);

  const agentsKey = useMemo(
    () => ["/agents", { offset: (page - 1) * pageSize, limit: pageSize }] as const,
    [page, pageSize]
  );
  const sgKey = useMemo(
    () => ["/semantic-groups", { offset: 0, limit: 2000 }] as const,
    []
  );

  const { data: agentsData, error: agentsError, isLoading, mutate: mutateAgents } = useSWR<
    { items?: unknown[]; totalCount?: number; total?: number; data?: { items?: unknown[]; totalCount?: number; total?: number } }
  >(agentsKey, apiFetcherWithParams);

  const { data: sgData, isLoading: isLoadingSg } = useSWR<{ items?: unknown[] }>(sgKey, apiFetcherWithParams);

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

  const { agents: rawAgentsList, totalCount: rawTotal } = useMemo(() => {
    const data = agentsData?.data ?? agentsData;
    const items = (data?.items ?? []) as unknown;
    const list = Array.isArray(items) ? items : [];
    const total = Number(data?.totalCount ?? data?.total ?? 0);
    return { agents: list, totalCount: total };
  }, [agentsData]);

  const agents = useMemo(() => {
    const list = rawAgentsList ?? [];
    return list
      .filter((x): x is UnknownRecord => isRecord(x))
      .map((item) => {
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
        const dsType =
          dataSourceTypeRaw === "SemanticGroup" || Boolean(semanticGroupID)
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
        return {
          id: name,
          name: displayName,
          namespace,
          description,
          dataSource: selector.length > 0 ? selector.join(", ") : "-",
          dataSourceType: dsType,
          semanticGroupID,
          plannerLLM,
          expertLLM,
          status: deriveAgentStatus(item),
          raw: item,
        };
      })
      .filter((a) => a.id && a.name);
  }, [rawAgentsList]);

  const totalCount = useMemo(
    () =>
      Number.isFinite(rawTotal) && rawTotal >= 0 ? rawTotal : agents.length,
    [rawTotal, agents.length]
  );

  useEffect(() => {
    if (agentsError) {
      toast.error("获取智能体列表失败");
    }
  }, [agentsError]);

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const ordered = useMemo(() => agents || [], [agents]);
  const filtered = useMemo(() => {
    if (typeFilter === "all") return ordered;
    return ordered.filter((a) => a.dataSourceType === typeFilter);
  }, [ordered, typeFilter]);

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

      // Map frontend selection to DAC types
      // descriptor -> dacType="ds", dataSourceType="SemanticDomain"
      // semantic-group -> dacType="normal", dataSourceType="SemanticGroup"
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
          // If semantic group, set semanticGroupID, otherwise sourceNameSelector
          semanticGroupID: isSemanticGroup ? data.dataSourceId : undefined,
          sourceNameSelector: !isSemanticGroup ? [data.dataSourceId] : undefined,
        },
        model: {
          plannerLLM: data.plannerModel,
          expertLLM: data.expertModel,
          embedding: "embedding-config",
        },
        expertAgentMaxSteps: data.expertAgentMaxSteps || "1",
        orchestratorAgentMaxLoops: data.orchestratorAgentMaxLoops || "1",
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
      // If we deleted the last item on the page, go back one page.
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

  const openDelete = (id: string, ns: string) => {
    setDeleteId(id);
    setDeleteNamespace(ns);
  };

  const openDetail = (agent: Agent) => {
    router.push(
      `/agents/${encodeURIComponent(agent.namespace)}/${encodeURIComponent(agent.id)}`,
    );
  };

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6 sm:space-y-8">
      {/* Breadcrumb + actions (in-content, no extra bar) */}
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-content">
          <span className="text-content font-semibold">智能体</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden md:block">
            <Select
              value={typeFilter}
              onValueChange={(v) =>
                setTypeFilter(v as "all" | "descriptor" | "semantic-group")
              }
            >
              <SelectTrigger className="w-[200px] bg-surface">
                <SelectValue placeholder="筛选类型" />
              </SelectTrigger>
              <SelectContent align="end">
                <SelectItem value="all">全部</SelectItem>
                <SelectItem value="descriptor">数据智能体</SelectItem>
                <SelectItem value="semantic-group">业务智能体</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button
            variant="outline"
            size="icon"
            onClick={fetchData}
            disabled={isLoading}
            aria-label="刷新"
          >
            <RefreshCw
              className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`}
            />
          </Button>
          <RbacButton
            className="flex items-center gap-2"
            onClick={() => setIsCreateOpen(true)}
            requiredRole="admin"
            fallbackTitle="无权限：仅管理员可创建"
          >
            <Plus className="w-4 h-4" />
            新建智能体
          </RbacButton>
        </div>
      </div>

      <div className="md:hidden">
        <Select
          value={typeFilter}
          onValueChange={(v) =>
            setTypeFilter(v as "all" | "descriptor" | "semantic-group")
          }
        >
          <SelectTrigger className="w-full bg-surface">
            <SelectValue placeholder="筛选类型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部</SelectItem>
            <SelectItem value="descriptor">数据智能体</SelectItem>
            <SelectItem value="semantic-group">业务智能体</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading && ordered.length === 0 ? (
        <ListSkeleton items={6} />
      ) : ordered.length === 0 ? (
        <div className="flex h-[400px] items-center justify-center rounded-md border border-dashed border-line-hover bg-surface-muted">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Bot className="w-10 h-10 opacity-20" />
            <p>暂无智能体</p>
            <RbacWrapper requiredRole="admin">
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
      ) : filtered.length === 0 ? (
        <div className="flex h-[400px] items-center justify-center rounded-md border border-dashed border-line-hover bg-surface-muted">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Layers className="w-10 h-10 opacity-20" />
            <p>暂无匹配的智能体</p>
            <Button
              variant="link"
              className="text-content-muted underline underline-offset-4 hover:text-content"
              onClick={() => setTypeFilter("all")}
            >
              清除筛选
            </Button>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filtered.map((a) => (
            <Card
              key={`${a.namespace}/${a.id}`}
              className="group relative cursor-pointer overflow-hidden hover:border-line-hover hover:shadow-md transition-all duration-200 py-0 gap-0"
              onClick={() => openDetail(a)}
            >
              <CardHeader className="p-4 pb-3 bg-surface-muted/50">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <div className="w-10 h-10 rounded-xl bg-[#e0e7ff] flex items-center justify-center text-[#4f46e5] shrink-0 border border-[#c7d2fe]">
                      <Bot className="w-5 h-5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <CardTitle
                        className="text-sm font-semibold line-clamp-1 break-all pr-1"
                        title={a.name}
                      >
                        {a.name}
                      </CardTitle>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-muted-foreground">
                        <span className="font-mono text-content-muted">
                          {a.namespace}
                        </span>
                        <span className="text-content-muted">·</span>
                        <span
                          className="font-mono text-content-muted truncate"
                          title={a.id}
                        >
                          {a.id}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="shrink-0 flex items-center gap-2">
                    <StatusBadge status={a.status} />
                    <RbacWrapper requiredRole="admin">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-content-muted hover:text-red-600 hover:bg-red-50"
                        onClick={(e) => {
                          e.stopPropagation();
                          openDelete(a.id, a.namespace);
                        }}
                        title="删除"
                        aria-label="删除"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </RbacWrapper>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="px-4 pb-4 pt-3 space-y-3">
                <p className="text-xs text-content line-clamp-2 min-h-[32px] leading-relaxed">
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
                    <Layers className="w-3.5 h-3.5 text-content-muted shrink-0" />
                  ) : (
                    <Database className="w-3.5 h-3.5 text-content-muted shrink-0" />
                  )}
                  <span className="text-xs text-content truncate">
                    {a.dataSourceType === "semantic-group"
                      ? sgNameById[a.semanticGroupID || ""] ||
                        (a.semanticGroupID ? (isLoadingSg ? "加载中…" : "-") : "-")
                      : a.dataSource || "-"}
                  </span>
                </div>

                <div
                  className="text-[11px] text-content-muted font-mono truncate"
                  title={[a.plannerLLM, a.expertLLM]
                    .filter(Boolean)
                    .join(" / ")}
                >
                  {a.plannerLLM || "-"}
                  {a.expertLLM && a.expertLLM !== a.plannerLLM
                    ? ` / ${a.expertLLM}`
                    : ""}
                </div>

                {/* Type Marker */}
                <div className="absolute bottom-3 right-3">
                  {a.dataSourceType === "semantic-group" ? (
                    <Badge variant="secondary" className="text-[10px] h-5 bg-indigo-50 text-indigo-700 border-indigo-100 font-normal px-2">
                      业务智能体
                    </Badge>
                  ) : (
                    <Badge variant="secondary" className="text-[10px] h-5 bg-surface-muted text-content border-line font-normal px-2">
                      数据智能体
                    </Badge>
                  )}
                </div>
              </CardContent>
            </Card>
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

      {/* 删除确认弹窗 */}
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
                <span className="block mt-2 font-mono text-xs text-content">
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
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : null}
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
