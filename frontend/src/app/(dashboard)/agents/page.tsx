"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { getUserRole } from "@/lib/auth"; // Import auth helper
import { RbacButton, RbacWrapper } from "@/components/rbac";
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
import { toast } from "sonner";

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
  const [agents, setAgents] = useState<Agent[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleteNamespace, setDeleteNamespace] = useState<string>("default");
  const [isDeleting, setIsDeleting] = useState(false);
  const [pageSize, setPageSize] = useState(20);
  const [page, setPage] = useState(1);
  const [typeFilter, setTypeFilter] = useState<
    "all" | "descriptor" | "semantic-group"
  >("all");
  const [sgNameById, setSgNameById] = useState<Record<string, string>>({});
  const [isLoadingSg, setIsLoadingSg] = useState(false);

  const getItemField = (item: UnknownRecord, key: string, legacyKey: string) =>
    (item[key] as unknown) ?? (item[legacyKey] as unknown);

  const loadSemanticGroups = async () => {
    if (isLoadingSg) return;
    setIsLoadingSg(true);
    try {
      // Best-effort: load semantic groups and build id -> group_name map.
      const res = await api.get("/semantic-groups", {
        params: { offset: 0, limit: 2000 },
      });
      const data = (res.data?.data ?? res.data) as unknown;
      const r = isRecord(data) ? data : {};
      const items = Array.isArray((r as UnknownRecord).items)
        ? ((r as UnknownRecord).items as unknown[])
        : [];
      const next: Record<string, string> = {};
      for (const x0 of items) {
        const x = isRecord(x0) ? x0 : {};
        const id = asString(x.id) || "";
        const name = asString(x.group_name) || "";
        if (id) next[id] = name || id;
      }
      setSgNameById((prev) => ({ ...prev, ...next }));
    } catch {
      // ignore (UI will fallback)
    } finally {
      setIsLoadingSg(false);
    }
  };

  const fetchData = async () => {
    setIsLoading(true);
    try {
      const offset = (page - 1) * pageSize;
      const res = await api.get(`/agents`, {
        params: { offset, limit: pageSize },
      });
      const data = res.data?.data ?? res.data;
      const items = (data?.items || []) as unknown;
      const total = Number(data?.totalCount ?? data?.total ?? 0);
      const list = Array.isArray(items) ? items : [];

      const adapted: Agent[] = list
        .filter((x): x is UnknownRecord => isRecord(x))
        .map((item) => {
          const name = asString(item.name) ?? "";
          const namespace = asString(item.namespace) ?? "default";

          const agentCardRaw = getItemField(item, "agentCard", "agent_card");
          const agentCard = isRecord(agentCardRaw) ? agentCardRaw : undefined;
          const displayName = asString(agentCard?.name) ?? name;
          const description = asString(agentCard?.description) ?? "";

          const dataPolicyRaw = getItemField(item, "dataPolicy", "data_policy");
          const dataPolicy = isRecord(dataPolicyRaw)
            ? dataPolicyRaw
            : undefined;
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
      setAgents(adapted);
      setTotalCount(
        Number.isFinite(total) && total >= 0 ? total : adapted.length,
      );
    } catch (err) {
      console.error("Fetch agents failed", err);
      toast.error("获取智能体列表失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    // Prefetch SG names to avoid showing SG id flash.
    loadSemanticGroups();
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize]);

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalPages]);

  const ordered = useMemo(() => agents || [], [agents]);
  const filtered = useMemo(() => {
    if (typeFilter === "all") return ordered;
    return ordered.filter((a) => a.dataSourceType === typeFilter);
  }, [ordered, typeFilter]);

  useEffect(() => {
    // If there are SG agents but we still don't have names, retry once (best-effort).
    const hasSg =
      (agents || []).some(
        (a) => a.dataSourceType === "semantic-group" && (a.semanticGroupID || "").trim(),
      ) && Object.keys(sgNameById || {}).length === 0;
    if (!hasSg) return;
    if (isLoadingSg) return;
    void loadSemanticGroups();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents, sgNameById, isLoadingSg]);

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

  const statusBadge = (s: Agent["status"]) => {
    if (s === "AVAILABLE") {
      return (
        <Badge
          variant="outline"
          className="bg-green-50 text-green-700 border-green-200"
        >
          AVAILABLE
        </Badge>
      );
    }
    if (s === "CREATING") {
      return (
        <Badge
          variant="outline"
          className="bg-blue-50 text-blue-700 border-blue-200"
        >
          CREATING
        </Badge>
      );
    }
    return (
      <Badge
        variant="outline"
        className="bg-slate-50 text-slate-600 border-slate-200"
      >
        UNKNOWN
      </Badge>
    );
  };

  const openDetail = (agent: Agent) => {
    router.push(
      `/agents/${encodeURIComponent(agent.namespace)}/${encodeURIComponent(agent.id)}`,
    );
  };

  return (
    <div className="p-8 space-y-8">
      {/* Breadcrumb + actions (in-content, no extra bar) */}
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-slate-600">
          <span className="text-slate-900 font-semibold">智能体</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden sm:block">
            <Select
              value={typeFilter}
              onValueChange={(v) =>
                setTypeFilter(v as "all" | "descriptor" | "semantic-group")
              }
            >
              <SelectTrigger className="w-[200px] bg-white">
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

      <div className="sm:hidden">
        <Select
          value={typeFilter}
          onValueChange={(v) =>
            setTypeFilter(v as "all" | "descriptor" | "semantic-group")
          }
        >
          <SelectTrigger className="w-full bg-white">
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
        <div className="flex h-[400px] items-center justify-center">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Loader2 className="w-8 h-8 animate-spin" />
            <p>加载中...</p>
          </div>
        </div>
      ) : ordered.length === 0 ? (
        <div className="flex h-[400px] items-center justify-center rounded-md border border-dashed border-slate-300 bg-slate-50">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Bot className="w-10 h-10 opacity-20" />
            <p>暂无智能体</p>
            <RbacWrapper requiredRole="admin">
              <Button
                variant="link"
                className="text-slate-500 underline underline-offset-4 hover:text-slate-900"
                onClick={() => setIsCreateOpen(true)}
              >
                创建一个?
              </Button>
            </RbacWrapper>
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex h-[400px] items-center justify-center rounded-md border border-dashed border-slate-300 bg-slate-50">
          <div className="flex flex-col items-center gap-2 text-muted-foreground">
            <Layers className="w-10 h-10 opacity-20" />
            <p>暂无匹配的智能体</p>
            <Button
              variant="link"
              className="text-slate-500 underline underline-offset-4 hover:text-slate-900"
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
              className="group relative cursor-pointer overflow-hidden hover:border-slate-300 hover:shadow-md transition-all duration-200 py-0 gap-0"
              onClick={() => openDetail(a)}
            >
              <CardHeader className="p-4 pb-3 bg-slate-50/50">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <div className="w-9 h-9 rounded-xl bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
                      <Bot className="w-4.5 h-4.5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <CardTitle
                        className="text-sm font-semibold line-clamp-1 break-all pr-1"
                        title={a.name}
                      >
                        {a.name}
                      </CardTitle>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-muted-foreground">
                        <span className="font-mono text-slate-500">
                          {a.namespace}
                        </span>
                        <span className="text-slate-300">·</span>
                        <span
                          className="font-mono text-slate-500 truncate"
                          title={a.id}
                        >
                          {a.id}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="shrink-0 flex items-center gap-2">
                    {statusBadge(a.status)}
                    <RbacWrapper requiredRole="admin">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-slate-400 hover:text-red-600 hover:bg-red-50"
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
                <p className="text-xs text-slate-600 line-clamp-2 min-h-[32px] leading-relaxed">
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
                    <Layers className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                  ) : (
                    <Database className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                  )}
                  <span className="text-xs text-slate-600 truncate">
                    {a.dataSourceType === "semantic-group"
                      ? sgNameById[a.semanticGroupID || ""] ||
                        (a.semanticGroupID ? (isLoadingSg ? "加载中..." : "-") : "-")
                      : a.dataSource || "-"}
                  </span>
                </div>

                <div
                  className="text-[11px] text-slate-500 font-mono truncate"
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
                    <Badge variant="secondary" className="text-[10px] h-5 bg-slate-50 text-slate-600 border-slate-100 font-normal px-2">
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
                <span className="block mt-2 font-mono text-xs text-slate-600">
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
