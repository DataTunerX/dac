export default function DashboardLoading() {
  return (
    <div className="flex items-center justify-center min-h-[320px] p-8">
      <div className="flex flex-col items-center gap-4">
        <div
          className="w-10 h-10 rounded-full border-2 border-line border-t-cta animate-spin"
          aria-hidden
        />
        <p className="text-sm text-content-muted">加载中…</p>
      </div>
    </div>
  )
}
