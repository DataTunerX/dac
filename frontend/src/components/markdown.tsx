import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { prepareMarkdown } from "@/lib/prepare-markdown"
import { isExternalMarkdownHref, sanitizeMarkdownHref } from "@/lib/markdown-url"

export { prepareMarkdown } from "@/lib/prepare-markdown"

type Components = Parameters<typeof ReactMarkdown>[0]["components"]

export const defaultMarkdownComponents: Components = {
  p: (props) => <p className="text-sm text-content leading-6 mb-2 last:mb-0" {...props} />,
  a: ({ href, children, ...props }) => {
    const safeHref = sanitizeMarkdownHref(href)
    if (!safeHref) {
      return <span className="text-content">{children}</span>
    }
    const external = isExternalMarkdownHref(safeHref)
    return (
      <a
        {...props}
        href={safeHref}
        className="text-cta hover:underline cursor-pointer"
        target={external ? "_blank" : undefined}
        rel={external ? "noopener noreferrer" : undefined}
      >
        {children}
      </a>
    )
  },
  code: (props) => (
    <code className="bg-surface-muted rounded px-1 py-0.5 font-mono text-[12px] text-content" {...props} />
  ),
  ul: (props) => <ul className="text-sm text-content leading-6 list-disc pl-5 space-y-1 my-2" {...props} />,
  ol: (props) => <ol className="text-sm text-content leading-6 list-decimal pl-5 space-y-1 my-2" {...props} />,
  li: (props) => <li className="pl-1 marker:text-content-muted" {...props} />,
  strong: (props) => <strong className="font-semibold text-content" {...props} />,
  em: (props) => <em className="italic text-content" {...props} />,
  del: (props) => <del className="line-through text-content-muted" {...props} />,
  blockquote: (props) => (
    <blockquote
      className="border-l-4 border-line pl-4 py-2 my-3 italic text-sm text-content bg-surface-muted rounded-r"
      {...props}
    />
  ),
  hr: (props) => <hr className="my-6 border-line" {...props} />,
  table: (props) => (
    <div className="my-4 w-full overflow-x-auto rounded-lg border border-line bg-surface shadow-sm">
      <table className="w-full min-w-full text-sm text-left border-collapse" {...props} />
    </div>
  ),
  thead: (props) => <thead className="bg-surface-muted text-content font-medium" {...props} />,
  tbody: (props) => (
    <tbody className="bg-surface [&>tr]:border-b [&>tr]:border-line last:[&>tr]:border-b-0" {...props} />
  ),
  tr: (props) => <tr className="transition-colors hover:bg-surface-muted/50" {...props} />,
  th: (props) => (
    <th className="py-3 px-4 font-semibold text-content border-b border-line whitespace-nowrap" {...props} />
  ),
  td: (props) => <td className="py-3 px-4 text-content align-top border-b border-line" {...props} />,
  h1: (props) => <h1 className="text-xl font-semibold text-content mt-6 mb-3" {...props} />,
  h2: (props) => <h2 className="text-lg font-semibold text-content mt-5 mb-2.5" {...props} />,
  h3: (props) => <h3 className="text-base font-semibold text-content mt-4 mb-2" {...props} />,
  h4: (props) => <h4 className="text-sm font-semibold text-content mt-3 mb-2" {...props} />,
  h5: (props) => <h5 className="text-sm font-semibold text-content mt-3 mb-2" {...props} />,
  h6: (props) => <h6 className="text-sm font-semibold text-content mt-3 mb-2" {...props} />,
}

export function Markdown({
  children,
  normalize = true,
  normalizeTables,
  components,
}: {
  children: string
  normalize?: boolean
  /** @deprecated alias for `normalize` */
  normalizeTables?: boolean
  components?: Components
}) {
  const shouldNormalize = normalizeTables ?? normalize
  const content = shouldNormalize ? prepareMarkdown(children) : children
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={(url) => sanitizeMarkdownHref(url) ?? ""}
      components={components || defaultMarkdownComponents}
    >
      {content}
    </ReactMarkdown>
  )
}
