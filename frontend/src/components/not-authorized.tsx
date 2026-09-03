"use client"

import Link from "next/link"
import { ShieldX } from "lucide-react"

export function NotAuthorized() {
  return (
    <div className="min-h-[420px] flex flex-col items-center justify-center p-6">
      <div className="w-12 h-12 rounded-lg border border-line bg-surface flex items-center justify-center mb-5">
        <ShieldX className="w-5 h-5 text-content-muted" />
      </div>
      <h2 className="text-base font-semibold text-content mb-2">无权访问</h2>
      <p className="text-sm text-content-muted mb-6 max-w-sm text-center leading-relaxed">
        你的账号不具备访问此页面的权限，请联系管理员为你分配对应的角色。
      </p>
      <Link
        href="/"
        className="px-4 py-2 rounded-lg bg-surface border border-line text-content font-medium hover:bg-surface-active transition-colors"
      >
        返回首页
      </Link>
    </div>
  )
}