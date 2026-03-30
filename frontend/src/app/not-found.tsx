import Link from "next/link"

export default function NotFound() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-surface-muted">
      <h1 className="text-2xl font-semibold text-content mb-2">页面不存在</h1>
      <p className="text-sm text-content-muted mb-6">请检查地址或返回首页</p>
      <Link
        href="/"
        className="px-4 py-2 rounded-lg bg-surface border border-line text-content font-medium hover:bg-surface-active transition-colors"
      >
        返回首页
      </Link>
    </div>
  )
}
