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
  Layers
} from "lucide-react"
import { Suspense, useEffect, useMemo, useState } from "react"
import { api } from "@/lib/api"
import { format, startOfDay, subDays } from "date-fns"
import { REFRESH_CHAT_LIST_EVENT, NewChatEventDetail } from "@/lib/events"

const sidebarItems = [
  { icon: Bot, label: "智能体", href: "/agents" },
  { icon: Database, label: "数据管理", href: "/datasources" },
  { icon: Layers, label: "语义组", href: "/semantic-groups" },
  { icon: Network, label: "资产探测", href: "/infra" },
  { icon: Settings2, label: "配置管理", href: "/configmaps" },
]

interface Conversation {
  id: string
  title: string
  created_at: string
}

type ConversationWithDate = Conversation & { createdAt: Date }

function isValidDate(d: Date) {
  return Number.isFinite(d.getTime())
}

function groupConversationsByTime(conversations: Conversation[]) {
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

function ConversationList() {
  const searchParams = useSearchParams()
  const currentRunId = searchParams.get("run_id")
  const [conversations, setConversations] = useState<Conversation[]>([])
  const groupedConversations = useMemo(() => groupConversationsByTime(conversations), [conversations])

  useEffect(() => {
    const fetchConversations = async () => {
      try {
        const res = await api.get('/chat/conversations')
        if (res.data.items) {
          setConversations(prev => {
            const newItems = res.data.items as Conversation[]
            return newItems.map(newItem => {
              if (!newItem.title) {
                const existing = prev.find(p => p.id === newItem.id)
                if (existing && existing.title) {
                  return { ...newItem, title: existing.title }
                }
                const storedTitle = localStorage.getItem(`dac_title_${newItem.id}`)
                if (storedTitle) {
                  return { ...newItem, title: storedTitle }
                }
              }
              return newItem
            })
          })
        }
      } catch (error) {
        console.error("Failed to fetch conversations", error)
      }
    }
    fetchConversations()

    const handleRefresh = (e: Event) => {
      if (e instanceof CustomEvent && e.detail) {
        const detail = e.detail as NewChatEventDetail
        setConversations(prev => {
          let next = prev
          if (detail.replace_id) {
            next = next.filter(c => c.id !== detail.replace_id)
          }
          if (next.some(c => c.id === detail.id)) return next
          return [{
            id: detail.id,
            title: detail.title,
            created_at: detail.created_at
          }, ...next]
        })
        return
      }
      fetchConversations()
    }

    window.addEventListener(REFRESH_CHAT_LIST_EVENT, handleRefresh)
    return () => {
      window.removeEventListener(REFRESH_CHAT_LIST_EVENT, handleRefresh)
    }
  }, [])

  if (conversations.length === 0) {
    return (
      <div className="px-3 py-2 text-xs text-slate-400">
        暂无历史记录
      </div>
    )
  }

  return (
    <>
      {groupedConversations.map((group, groupIdx) => (
        <div key={group.key} className={groupIdx === 0 ? "" : "mt-4"}>
          <div className="px-3 mb-1 text-xs font-medium text-slate-400">
            {group.label}
          </div>
           <div className="space-y-1">
             {group.items.map((conv) => {
               const isActive = conv.id === currentRunId
               return (
                 <Link
                   key={conv.id}
                   href={`/?run_id=${conv.id}`}
                   className={cn(
                     "w-full text-left flex items-center gap-2 px-3 py-2 text-sm rounded-md truncate transition-colors outline-none",
                     isActive 
                       ? "bg-blue-50 text-blue-600 font-medium" 
                       : "text-slate-600 hover:bg-slate-100"
                   )}
                 >
                   <MessageSquare className={cn("w-4 h-4 shrink-0", isActive ? "text-blue-500" : "text-slate-400")} />
                   <span className="truncate">
                     {conv.title || format(conv.createdAt, "MM-dd HH:mm")}
                   </span>
                 </Link>
               )
             })}
           </div>
        </div>
      ))}
    </>
  )
}

export function Sidebar() {
  const pathname = usePathname()

  return (
    <div className="w-64 bg-slate-50 h-full flex flex-col border-r border-slate-200">
      <div className="p-4 pb-0">
          <Link 
            href="/" 
            className="flex items-center gap-2 px-4 py-2.5 bg-white border border-slate-200 shadow-sm text-slate-700 rounded-full hover:bg-slate-50 hover:text-blue-600 hover:border-blue-200 transition-all font-medium text-sm group justify-center outline-none"
          >
          <Plus className="w-4 h-4 text-slate-500 group-hover:text-blue-600 transition-colors" />
          开启新对话
        </Link>
      </div>

      <div className="flex-1 py-4 px-3 flex flex-col min-h-0">
        <div className="space-y-1">
          {sidebarItems.map((item) => (
            (() => {
              const active = pathname === item.href || pathname.startsWith(item.href + "/")
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md transition-colors outline-none border",
                    active
                      ? "bg-white text-blue-600 shadow-sm border-slate-100"
                      : "bg-slate-50 text-slate-600 border-transparent hover:bg-slate-100 hover:text-slate-900"
                  )}
                >
                  <item.icon className="w-4 h-4" />
                  {item.label}
                </Link>
              )
            })()
          ))}
        </div>

        <div className="mt-6 flex-1 min-h-0 overflow-y-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
          <Suspense fallback={<div className="px-3 py-2 text-xs text-slate-400">加载历史记录...</div>}>
            <ConversationList />
          </Suspense>
        </div>
      </div>
    </div>
  )
}
