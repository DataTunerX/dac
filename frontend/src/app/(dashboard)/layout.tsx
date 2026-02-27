"use client"

import { useEffect } from "react"
import { usePathname } from "next/navigation"
import Cookies from "js-cookie"
import { Sidebar } from "@/components/sidebar"
import { Topbar } from "@/components/topbar"

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  useEffect(() => {
    const token = Cookies.get("dac_token")
    if (token) return

    const search = typeof window !== "undefined" ? window.location.search || "" : ""
    const hash = typeof window !== "undefined" ? window.location.hash || "" : ""
    const next = `${pathname || "/"}${search}${hash}`
    window.location.href = `/login?next=${encodeURIComponent(next)}`
  }, [pathname])

  return (
    <div className="h-screen w-full flex flex-col">
      <Topbar />
      <div className="flex flex-1 min-h-0">
        <Sidebar />
        <main className="flex-1 flex flex-col h-full overflow-hidden">
          <div className="flex-1 overflow-auto bg-slate-50">
            {children}
          </div>
        </main>
      </div>
    </div>
  )
}

