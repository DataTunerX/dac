import Link from "next/link"
import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "隐私政策",
}

export default function PrivacyPage() {
  return (
    <main className="min-h-dvh bg-surface-muted px-6 py-12">
      <article className="mx-auto max-w-2xl rounded-xl border border-line bg-surface p-8 shadow-sm">
        <h1 className="text-2xl font-semibold text-content tracking-[-0.02em]">隐私政策</h1>
        <p className="mt-4 text-sm text-content-muted leading-relaxed">
          DAC Platform 尊重并保护用户隐私。我们仅收集运行平台所必需的信息，包括账户凭证、会话记录与操作日志，用于身份验证、服务交付与安全审计。
        </p>
        <p className="mt-3 text-sm text-content-muted leading-relaxed">
          我们不会向第三方出售你的个人数据。如需删除账户或导出数据，请联系平台管理员。
        </p>
        <Link
          href="/"
          className="mt-8 inline-flex items-center text-sm font-medium text-brand hover:text-brand-hover transition-colors"
        >
          返回首页
        </Link>
      </article>
    </main>
  )
}
