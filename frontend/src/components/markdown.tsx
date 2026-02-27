import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

type Components = Parameters<typeof ReactMarkdown>[0]["components"]

function normalizeModelTablesListToGfmTable(input: string) {
  // Some model outputs describe "Tables:" as a numbered list instead of a GFM table, e.g.:
  //   Tables:
  //   1. table name: customers(客户), table description: ...
  // Convert that block into a readable markdown table.
  // Never touch fenced code blocks.
  const text = input || ""
  const lines = text.split("\n")
  const out: string[] = []
  let inFence = false

  const isFence = (line: string) => /^\s*```/.test(line)
  const hasTablesToken = (line: string) => /Tables\s*[:：]/i.test(line)
  const isNumbered = (line: string) => /^\s*\d+\.\s+/.test(line)

  const parseRow = (line: string) => {
    const body = line.replace(/^\s*\d+\.\s+/, "").trim()
    const m = body.match(
      /table name:\s*([^(,，]+?)(?:\(([^)]+)\))?[,，]?\s*table description:\s*(.*)/i
    )
    if (!m) return null
    const name = (m[1] || "").trim()
    const entity = (m[2] || "").trim()
    const desc = (m[3] || "").trim()
    if (!name && !desc) return null
    return { name, entity, desc }
  }

  const escCell = (v: string) => (v || "").replaceAll("|", "\\|").trim()

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (isFence(line)) inFence = !inFence

    if (!inFence && hasTablesToken(line)) {
      // Collect subsequent numbered lines as candidate rows.
      const rows: Array<{ name: string; entity: string; desc: string }> = []
      let j = i + 1
      while (j < lines.length && isNumbered(lines[j])) {
        const r = parseRow(lines[j])
        if (r) rows.push(r)
        j++
      }

      if (rows.length > 0) {
        const idx = line.search(/Tables\s*[:：]/i)
        const before = idx > 0 ? line.slice(0, idx).trimEnd() : ""

        if (before) out.push(before)
        // Keep the label compact; avoid large headings.
        out.push("")
        out.push("**Tables**")
        out.push("")
        out.push("| Table | Description |")
        out.push("| :--- | :--- |")
        for (const r of rows) {
          const tableLabel = r.entity ? `${r.name} (${r.entity})` : r.name
          out.push(`| ${escCell(tableLabel)} | ${escCell(r.desc)} |`)
        }
        out.push("")

        // Skip the consumed numbered rows.
        i = j - 1
        continue
      }
    }

    out.push(line)
  }

  return out.join("\n")
}

function normalizeGfmTables(input: string) {
  // GFM tables may fail to parse if they directly follow a non-empty line.
  // Insert a blank line before the table header when needed (never touch fenced code blocks).
  const lines = input.split("\n")
  const out: string[] = []
  let inFence = false

  const isFence = (line: string) => /^\s*```/.test(line)
  const isSeparator = (line: string) => {
    const t = line.trim()
    if (!t.includes("|") || !t.includes("-")) return false
    return /^[|:\-\s]+$/.test(t)
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const next = i + 1 < lines.length ? lines[i + 1] : ""

    if (isFence(line)) inFence = !inFence

    const looksLikeTableHeader = !inFence && line.includes("|") && isSeparator(next)
    const prev = out.length ? out[out.length - 1] : ""
    const prevNonEmpty = prev.trim().length > 0

    if (looksLikeTableHeader && prevNonEmpty) out.push("")
    out.push(line)
  }

  return out.join("\n")
}

function normalizeBrokenSingleLineGfmTable(line: string) {
  // Some model outputs squash the whole table into a single line, using `| |` as a row separator:
  //   领域模型: | a | b | | :--- | :--- | | row1... | | row2... |
  // Fix by:
  // - splitting prefix text from table
  // - converting `| | <rowStart>` into `|\n| <rowStart>`
  // - ensuring the separator row has the same column count as header
  if (!line.includes("|") || !line.includes(":---")) return line

  const firstPipe = line.indexOf("|")
  if (firstPipe < 0) return line

  const prefix = line.slice(0, firstPipe).trimEnd()
  let table = line.slice(firstPipe).trim()

  // Insert newlines at likely row boundaries.
  // Only split when the next token looks like a new row start (separator row `:---` or text).
  table = table.replace(/\|\s*\|\s*(?=:[-]{3}|[A-Za-z\u4e00-\u9fff])/g, "|\n| ")

  // Normalize each line to start with a pipe.
  table = table
    .split("\n")
    .map((l) => (l.trim().startsWith("|") ? l.trim() : `| ${l.trim()}`))
    .join("\n")

  const rows = table.split("\n").filter((l) => l.trim().length > 0)
  if (rows.length >= 2) {
    const header = rows[0]
    const sep = rows[1]

    const countCols = (row: string) => {
      const parts = row.split("|").map((x) => x.trim())
      // strip leading/trailing empty caused by leading/ending |
      if (parts.length && parts[0] === "") parts.shift()
      if (parts.length && parts[parts.length - 1] === "") parts.pop()
      return parts.length
    }

    const headerCols = countCols(header)
    const sepCols = countCols(sep)
    if (headerCols > 0 && sepCols > 0 && sepCols !== headerCols) {
      // rebuild separator row to match header column count
      rows[1] = `| ${Array.from({ length: headerCols }, () => ":---").join(" | ")} |`
      table = rows.join("\n")
    }
  }

  return prefix ? `${prefix}\n\n${table}` : table
}

export function normalizeMarkdownTables(input: string) {
  const modelFixed = normalizeModelTablesListToGfmTable(input || "")
  const lines = modelFixed.split("\n")
  const fixed = lines
    .map((l) => (l.includes(":---") && l.includes("|") ? normalizeBrokenSingleLineGfmTable(l) : l))
    .join("\n")
  return normalizeGfmTables(fixed)
}

// Recommended dashboard-readable baseline:
// - body: 14px (text-sm) with 24px line-height (leading-6)
// - subtle spacing between blocks
export const defaultMarkdownComponents: Components = {
  p: (props) => <p className="text-sm text-slate-700 leading-6 mb-2 last:mb-0" {...props} />,
  a: (props) => <a className="text-blue-600 hover:underline" target="_blank" {...props} />,
  code: (props) => (
    <code className="bg-slate-100 rounded px-1 py-0.5 font-mono text-[12px] text-slate-700" {...props} />
  ),
  ul: (props) => <ul className="text-sm text-slate-700 leading-6 list-disc pl-5 space-y-1 my-2" {...props} />,
  ol: (props) => <ol className="text-sm text-slate-700 leading-6 list-decimal pl-5 space-y-1 my-2" {...props} />,
  li: (props) => <li className="pl-1 marker:text-slate-400" {...props} />,
  strong: (props) => <strong className="font-semibold text-slate-900" {...props} />,
  em: (props) => <em className="italic text-slate-700" {...props} />,
  del: (props) => <del className="line-through text-slate-400" {...props} />,
  blockquote: (props) => (
    <blockquote className="border-l-4 border-slate-200 pl-4 py-2 my-3 italic text-sm text-slate-600 bg-slate-50 rounded-r" {...props} />
  ),
  hr: (props) => <hr className="my-6 border-slate-100" {...props} />,
  table: (props) => (
    <div className="my-4 w-full overflow-x-auto">
      <table className="w-full min-w-full text-sm text-left border-collapse" {...props} />
    </div>
  ),
  thead: (props) => <thead className="bg-slate-50 text-slate-500 font-medium" {...props} />,
  tbody: (props) => <tbody className="divide-y divide-slate-100 border-t border-slate-100" {...props} />,
  tr: (props) => <tr className="transition-colors hover:bg-slate-50/50" {...props} />,
  th: (props) => <th className="py-3 px-4 font-semibold text-slate-700 whitespace-nowrap" {...props} />,
  td: (props) => <td className="py-3 px-4 text-slate-600 align-top" {...props} />,
  h1: (props) => <h1 className="text-xl font-semibold text-slate-900 mt-6 mb-3" {...props} />,
  h2: (props) => <h2 className="text-lg font-semibold text-slate-900 mt-5 mb-2.5" {...props} />,
  h3: (props) => <h3 className="text-base font-semibold text-slate-900 mt-4 mb-2" {...props} />,
  h4: (props) => <h4 className="text-sm font-semibold text-slate-900 mt-3 mb-2" {...props} />,
  h5: (props) => <h5 className="text-sm font-semibold text-slate-700 mt-3 mb-2" {...props} />,
  h6: (props) => <h6 className="text-sm font-semibold text-slate-600 mt-3 mb-2" {...props} />,
}

export function Markdown({
  children,
  normalizeTables = true,
  components,
}: {
  children: string
  normalizeTables?: boolean
  components?: Components
}) {
  const content = normalizeTables ? normalizeMarkdownTables(children) : children
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components || defaultMarkdownComponents}>
      {content}
    </ReactMarkdown>
  )
}

