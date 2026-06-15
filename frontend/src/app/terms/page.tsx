import Link from "next/link"
import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "服务条款",
}

export default function TermsPage() {
  return (
    <main className="min-h-dvh bg-surface-muted px-6 py-12">
      <article className="mx-auto max-w-2xl rounded-xl border border-line bg-surface p-8 shadow-sm">
        <h1 className="text-2xl font-semibold text-content tracking-[-0.02em]">服务条款</h1>
        <p className="mt-4 text-sm text-content-muted leading-relaxed">
          使用 DAC Platform 即表示你同意遵守组织内部的使用规范。平台提供的 AI 生成内容仅供参考，关键业务决策应经过人工核实。
        </p>
        <p className="mt-3 text-sm text-content-muted leading-relaxed">
          禁止利用本平台进行未授权的数据访问、恶意代码执行或任何违反法律法规的行为。
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
