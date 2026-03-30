"use client"

import { useEffect } from "react"
import { Button } from "@/components/ui/button"

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error("Dashboard segment error:", error)
  }, [error])

  return (
    <div className="flex flex-col items-center justify-center min-h-[280px] p-6 text-center">
      <p className="text-content font-medium mb-2">页面加载出错</p>
      <p className="text-sm text-content-muted mb-4 max-w-md">
        {error.message}
      </p>
      <Button type="button" variant="outline" onClick={reset}>
        重试
      </Button>
    </div>
  )
}
