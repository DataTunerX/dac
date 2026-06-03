"use client"

import Link from "next/link"
import { usePathname, useSearchParams } from "next/navigation"
import { cn } from "@/lib/utils"
import { 
  MessageSquare, 
  Database, 
  Bot, 
  Settings2,
  Plus,
  Network,
  Layers,
  Globe,
  ChevronRight,
  X,
  Menu
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import React, { memo, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react"
import useSWR from "swr"
import { listConversations } from "@/lib/chat-api"
import type { ConversationResponse } from "@/lib/api-types"
import { format, startOfDay, subDays } from "date-fns"
import { REFRESH_CHAT_LIST_EVENT, NewChatEventDetail } from "@/lib/events"

type SidebarLinkItem = {
  type: "link"
  icon: LucideIcon
  label: string
  href: string
}

type SidebarGroupItem = {
  type: "group"
  icon: LucideIcon
  label: string
  /** Paths that keep this group expanded / in-section (supports multiple route roots). */
  sectionPaths: string[]
  children: { label: string; href: string; icon?: LucideIcon }[]
}

const sidebarNav: Array<SidebarLinkItem | SidebarGroupItem> = [
  { type: "link", icon: Bot, label: "智能体", href: "/agents" },
  { type: "link", icon: Database, label: "数据管理", href: "/datasources" },
  { type: "link", icon: Layers, label: "语义组", href: "/semantic-groups" },
  { type: "link", icon: Network, label: "资产探测", href: "/infra" },
  { type: "link", icon: Settings2, label: "配置管理", href: "/configmaps" },
  {
    type: "group",
    icon: Globe,
    label: "全局管理",
    sectionPaths: ["/system-config", "/observability"],
    children: [
      { label: "注册中心", href: "/observability/registry" },
      { label: "模版中心", href: "/system-config/templates" },
    ],
  },
]

/** Shared base and selected styles for sidebar nav + history so they stay in sync (white raised). */
const sidebarLinkBase =
  "flex items-center gap-3 px-3 py-2.5 text-sm font-medium rounded-lg transition-colors duration-150 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-surface [-webkit-tap-highlight-color:transparent]"
const sidebarLinkSelected =
  "bg-surface text-brand border border-line"
const sidebarLinkDefault =
  "text-content-muted hover:bg-surface-active hover:text-content border border-transparent"

type ConversationWithDate = ConversationResponse & { createdAt: Date }

const CONVERSATION_WINDOW_DAYS = 10
const CONVERSATIONS_SWR_KEY = ["/chat/conversations", CONVERSATION_WINDOW_DAYS] as const

function isValidDate(d: Date) {
  return Number.isFinite(d.getTime())
}

function readStoredTitles(ids: readonly string[]): Map<string, string> {
  const m = new Map<string, string>()
  if (typeof window === "undefined") return m
  for (const id of ids) {
    const t = localStorage.getItem(`dac_title_${id}`)
    if (t) m.set(id, t)
  }
  return m
}

function mergeConversationTitles(
  items: ConversationResponse[],
  prevById: Map<string, ConversationResponse>
): ConversationResponse[] {
  const stored = readStoredTitles(items.map((i) => i.id))
  return items.map((newItem) => {
    if (newItem.title?.trim()) return newItem
    const existing = prevById.get(newItem.id)
    if (existing?.title) return { ...newItem, title: existing.title }
    const storedTitle = stored.get(newItem.id)
    if (storedTitle) return { ...newItem, title: storedTitle }
    return newItem
  })
}

const ConversationLink = memo(function ConversationLink({
  conv,
  isActive,
}: {
  conv: ConversationWithDate
  isActive: boolean
}) {
  const label = conv.title || format(conv.createdAt, "MM-dd HH:mm")
  return (
    <Link
      href={`/?run_id=${conv.id}`}
      prefetch={false}
      className={cn(
        sidebarLinkBase,
        "w-full text-left truncate [content-visibility:auto]",
        isActive ? sidebarLinkSelected : sidebarLinkDefault
      )}
    >
      <MessageSquare className={cn("w-4 h-4 shrink-0", isActive && "text-brand")} />
      <span className="truncate">{label}</span>
    </Link>
  )
})

function groupConversationsByTime(conversations: ConversationResponse[]) {
  const now = new Date()
  const todayStart = startOfDay(now)
  const sevenDaysAgoStart = startOfDay(subDays(now, 7))

  const sorted: ConversationWithDate[] = conversations
    .map((c) => ({ ...c, createdAt: new Date(c.created_at) }))
    .filter((c) => isValidDate(c.createdAt))
    .sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime())

  // Recent: group by day (today, then specific dates within last 7 days).
  const recentByDay = new Map<string, ConversationWithDate[]>()
  for (const c of sorted) {
    if (c.createdAt.getTime() < sevenDaysAgoStart.getTime()) continue
    const k = format(c.createdAt, "yyyy-MM-dd")
    const arr = recentByDay.get(k) || []
    arr.push(c)
    recentByDay.set(k, arr)
  }

  const older = sorted.filter((c) => c.createdAt.getTime() < sevenDaysAgoStart.getTime())

  const byMonth = new Map<string, ConversationWithDate[]>()
  for (const c of older) {
    const key = format(c.createdAt, "yyyy-MM")
    const arr = byMonth.get(key) || []
    arr.push(c)
    byMonth.set(key, arr)
  }

  const monthKeys = Array.from(byMonth.keys()).sort((a, b) => (a < b ? 1 : a > b ? -1 : 0))

  const groups: Array<{ key: string; label: string; items: ConversationWithDate[] }> = []

  const recentDayKeys = Array.from(recentByDay.keys()).sort((a, b) => (a < b ? 1 : a > b ? -1 : 0))
  for (const k of recentDayKeys) {
    const d = new Date(`${k}T00:00:00`)
    const label = isValidDate(d) && startOfDay(d).getTime() === todayStart.getTime() ? "今天" : format(d, "MM-dd")
    groups.push({ key: `day-${k}`, label, items: recentByDay.get(k) || [] })
  }

  for (const k of monthKeys) {
    // k is yyyy-MM
    const label = (() => {
      const d = new Date(`${k}-01T00:00:00`)
      return isValidDate(d) ? format(d, "yyyy年MM月") : k
    })()
    groups.push({ key: `month-${k}`, label, items: byMonth.get(k) || [] })
  }

  return groups
}

function SidebarNavGroup({
  item,
  pathname,
  onNavigate,
}: {
  item: SidebarGroupItem
  pathname: string
  onNavigate: () => void
}) {
  const inSection = item.sectionPaths.some(
    (p) => pathname === p || pathname.startsWith(p + "/")
  )
  const hasActiveChild = item.children.some(
    (child) => pathname === child.href || pathname.startsWith(child.href + "/")
  )
  const [open, setOpen] = useState(inSection)

  useEffect(() => {
    if (inSection) setOpen(true)
  }, [inSection])

  // 子项选中时父级仅展开，不占用选中态（避免双高亮）
  const parentSelected = inSection && !hasActiveChild

  return (
    <div className="space-y-0.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          sidebarLinkBase,
          "w-full",
          parentSelected ? sidebarLinkSelected : sidebarLinkDefault,
          hasActiveChild && "text-content"
        )}
      >
        <item.icon
          className={cn(
            "w-4 h-4 shrink-0",
            parentSelected && "text-brand",
            hasActiveChild && "text-content-muted"
          )}
        />
        <span className="flex-1 min-w-0 text-left truncate">{item.label}</span>
        <ChevronRight
          aria-hidden
          className={cn(
            "w-4 h-4 shrink-0 text-content-muted/70 transition-transform duration-150",
            open && "rotate-90",
            parentSelected && "text-brand"
          )}
        />
      </button>
      {open ? (
        <div className="space-y-0.5 pt-0.5">
          {item.children.map((child) => {
            const childActive =
              pathname === child.href || pathname.startsWith(child.href + "/")
            return (
              <Link
                key={child.href}
                href={child.href}
                prefetch={true}
                onClick={onNavigate}
                className={cn(
                  sidebarLinkBase,
                  "pl-10",
                  childActive ? sidebarLinkSelected : sidebarLinkDefault
                )}
              >
                <span className="flex-1 min-w-0 truncate">{child.label}</span>
              </Link>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

function ConversationList() {
  const searchParams = useSearchParams()
  const currentRunId = searchParams.get("run_id")
  const [conversations, setConversations] = useState<ConversationResponse[]>([])

  const { data, error, isLoading, mutate } = useSWR(
    CONVERSATIONS_SWR_KEY,
    () => listConversations({ days: CONVERSATION_WINDOW_DAYS }),
    { revalidateOnFocus: false, dedupingInterval: 30_000 }
  )

  useEffect(() => {
    if (!data) return
    const items = data.items ?? []
    setConversations((prev) => {
      const prevById = new Map(prev.map((p) => [p.id, p]))
      return mergeConversationTitles(items, prevById)
    })
  }, [data])

  useEffect(() => {
    if (error) console.error("Failed to fetch conversations", error)
  }, [error])

  const applyOptimistic = useCallback((detail: NewChatEventDetail) => {
    setConversations((prev) => {
      let next = prev
      if (detail.replace_id) {
        next = next.filter((c) => c.id !== detail.replace_id)
      }
      if (next.some((c) => c.id === detail.id)) return next
      return [
        {
          id: detail.id,
          title: detail.title,
          created_at: detail.created_at,
          updated_at: detail.created_at,
        },
        ...next,
      ]
    })
  }, [])

  useEffect(() => {
    const handleRefresh = (e: Event) => {
      if (e instanceof CustomEvent && e.detail) {
        applyOptimistic(e.detail as NewChatEventDetail)
        return
      }
      void mutate()
    }

    window.addEventListener(REFRESH_CHAT_LIST_EVENT, handleRefresh)
    return () => {
      window.removeEventListener(REFRESH_CHAT_LIST_EVENT, handleRefresh)
    }
  }, [applyOptimistic, mutate])

  const groupedConversations = useMemo(
    () => groupConversationsByTime(conversations),
    [conversations]
  )

  if (isLoading && conversations.length === 0) {
    return (
      <div className="px-3 py-2 text-xs text-content-muted">加载历史记录…</div>
    )
  }

  if (conversations.length === 0) {
    return (
      <div className="px-3 py-2 text-xs text-content-muted">
        暂无历史记录
      </div>
    )
  }

  return (
    <>
      {groupedConversations.map((group, groupIdx) => (
        <div key={group.key} className={groupIdx === 0 ? "" : "mt-4"}>
          <div className="px-3 mb-1 text-xs font-medium text-content-muted">
            {group.label}
          </div>
          <div className="space-y-1">
            {group.items.map((conv) => (
              <ConversationLink
                key={conv.id}
                conv={conv}
                isActive={conv.id === currentRunId}
              />
            ))}
          </div>
        </div>
      ))}
    </>
  )
}

export function Sidebar() {
  const pathname = usePathname()
  const [isMobileOpen, setIsMobileOpen] = useState(false)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  // Close mobile drawer on route change
  useEffect(() => {
    setIsMobileOpen(false)
  }, [pathname])

  // Lock body scroll when mobile drawer is open
  useEffect(() => {
    if (isMobileOpen) {
      document.body.style.overflow = "hidden"
    } else {
      document.body.style.overflow = ""
    }
    return () => {
      document.body.style.overflow = ""
    }
  }, [isMobileOpen])

  // Close on Escape; focus close button when drawer opens (a11y)
  useEffect(() => {
    if (!isMobileOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsMobileOpen(false)
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    closeButtonRef.current?.focus()
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [isMobileOpen])

  const sidebarContent = (
    <div className="h-full flex flex-col" data-sidebar-nav>
      <div className="p-4 pb-0">
        <Link
          href="/"
          prefetch={true}
          onClick={() => setIsMobileOpen(false)}
          className={cn(
            "flex items-center justify-center gap-3 px-3 py-2.5 text-sm font-medium rounded-lg transition-colors duration-150 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-surface [-webkit-tap-highlight-color:transparent]",
            "bg-surface-muted text-content border border-line shadow-sm hover:bg-surface-active"
          )}
        >
          <Plus className="w-4 h-4 shrink-0" />
          开启新对话
        </Link>
      </div>

      <div className="flex-1 py-5 px-3 flex flex-col min-h-0">
        <div className="space-y-1">
          {sidebarNav.map((item) => {
            if (item.type === "link") {
              const active = pathname === item.href || pathname.startsWith(item.href + "/")
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch={true}
                  onClick={() => setIsMobileOpen(false)}
                  className={cn(sidebarLinkBase, active ? sidebarLinkSelected : sidebarLinkDefault)}
                >
                  <item.icon className={cn("w-4 h-4 shrink-0", active && "text-brand")} />
                  {item.label}
                </Link>
              )
            }

            return (
              <SidebarNavGroup
                key={item.sectionPaths.join("|")}
                item={item}
                pathname={pathname}
                onNavigate={() => setIsMobileOpen(false)}
              />
            )
          })}
        </div>

        <div className="mt-6 flex-1 min-h-0 overflow-y-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
          <Suspense fallback={<div className="px-3 py-2 text-xs text-content-muted">加载历史记录…</div>}>
            <ConversationList />
          </Suspense>
        </div>
      </div>
    </div>
  )

  return (
    <div className="h-full w-0 shrink-0 lg:w-64">
      {/* Mobile menu button - visible only on small screens */}
      <button
        type="button"
        onClick={() => setIsMobileOpen(true)}
        className="lg:hidden fixed top-16 left-4 z-40 min-w-[44px] min-h-[44px] p-2 rounded-lg bg-surface border border-line shadow-sm text-content-muted hover:text-content hover:bg-surface-muted transition-colors cursor-pointer inline-flex items-center justify-center"
        aria-label="打开菜单"
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Desktop sidebar - hidden on mobile */}
      <div className="hidden lg:block w-64 bg-surface h-full flex flex-col border-r border-line shadow-sm z-10 shrink-0">
        {sidebarContent}
      </div>

      {/* Mobile drawer overlay */}
      {isMobileOpen && (
        <div 
          className="lg:hidden fixed inset-0 z-50 bg-black/50 backdrop-blur-sm [animation:sidebar-overlay-in_0.2s_ease-out]"
          onClick={() => setIsMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Mobile drawer: dialog semantics and keyboard close */}
      <div 
        role="dialog"
        aria-modal="true"
        aria-labelledby="sidebar-drawer-title"
        className={cn(
          "lg:hidden fixed top-0 left-0 h-full w-72 bg-surface border-r border-line shadow-xl z-50 transform transition-transform duration-300 ease-out",
          isMobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="h-14 flex items-center justify-between px-4 border-b border-line shrink-0">
          <span id="sidebar-drawer-title" className="font-bold text-content">导航</span>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={() => setIsMobileOpen(false)}
            className="min-w-[44px] min-h-[44px] p-2 rounded-lg text-content-muted hover:text-content hover:bg-surface-muted transition-colors cursor-pointer inline-flex items-center justify-center"
            aria-label="关闭菜单"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">
          {sidebarContent}
        </div>
      </div>
    </div>
  )
}
