"use client"

import { Suspense } from "react"
import { Sidebar } from "@/components/sidebar"
import { Topbar } from "@/components/topbar"
import { ErrorBoundary } from "@/components/error-boundary"
import { TenantProvider } from "@/components/tenant-provider"
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <TenantProvider>
      <div className="h-screen w-full flex flex-col">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-cta focus:px-3 focus:py-2 focus:text-content-inverse focus:outline-none focus:ring-2 focus:ring-cta cursor-pointer"
        >
          跳过主内容
        </a>
        <Topbar />
        <div className="flex flex-1 min-h-0">
          <Suspense fallback={<div className="w-64 shrink-0 hidden lg:block" />}>
            <Sidebar />
          </Suspense>
          <main id="main" className="flex-1 flex flex-col h-full overflow-hidden pl-14 lg:pl-0">
            <div className="flex-1 overflow-auto bg-surface-muted min-w-0">
              <ErrorBoundary>
                {children}
              </ErrorBoundary>
            </div>
          </main>
        </div>
      </div>
    </TenantProvider>
  )
}

