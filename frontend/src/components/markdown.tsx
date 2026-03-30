import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

type Components = Parameters<typeof ReactMarkdown>[0]["components"]

/**
 * Convert JSON-style escape sequences (literal \n, \t, etc.) into real characters.
 * Use when content comes from API/DB as a string with escaped newlines (e.g. "line1\\n\\nline2").
 */
function unescapeJsonLike(input: string): string {
  if (!input || typeof input !== "string") return input
  return input
    .replace(/\\n/g, "\n")
    .replace(/\\r/g, "\r")
    .replace(/\\t/g, "\t")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, "\\")
}

/** Collapse 4+ consecutive newlines to 2, so parsing doesn't produce huge gaps. */
function normalizeExcessiveNewlines(input: string): string {
  return (input || "").replace(/\n{4,}/g, "\n\n\n")
}

/**
 * Balance unclosed code fences (```). Model output often omits the closing ```.
 * Count line-starting ``` (optional language/tip); if odd, append a closing ```.
 * Does not touch content inside code blocks.
 */
function normalizeCodeFences(input: string): string {
  const text = input || ""
  const lines = text.split("\n")
  let count = 0
  for (const line of lines) {
    if (/^\s*```\s*[\w-]*\s*$/.test(line)) count++
  }
  if (count % 2 === 0) return text
  return text.trimEnd() + "\n\n```\n"
}

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
  table = table.replace(/\|\s*\|\s*(?=:[-]{3}|\S)/g, "|\n| ")

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

/**
 * Run all built-in normalizers: unescape \\n etc. → excessive newlines → code fences → tables.
 * Safe to use for model/LLM output and for strings from API/DB with escaped newlines.
 */
export function normalizeMarkdown(input: string) {
  const step0 = unescapeJsonLike(input || "")
  const step1 = normalizeExcessiveNewlines(step0)
  const step2 = normalizeCodeFences(step1)
  return normalizeMarkdownTables(step2)
}

// Recommended dashboard-readable baseline:
// - body: 14px (text-sm) with 24px line-height (leading-6)
// - subtle spacing between blocks
export const defaultMarkdownComponents: Components = {
  p: (props) => <p className="text-sm text-content leading-6 mb-2 last:mb-0" {...props} />,
  a: (props) => <a className="text-cta hover:underline cursor-pointer" target="_blank" rel="noopener noreferrer" {...props} />,
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
    <blockquote className="border-l-4 border-line pl-4 py-2 my-3 italic text-sm text-content bg-surface-muted rounded-r" {...props} />
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
  normalizeTables = true,
  components,
}: {
  children: string
  normalizeTables?: boolean
  components?: Components
}) {
  const content = normalizeTables ? normalizeMarkdown(children) : children
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components || defaultMarkdownComponents}>
      {content}
    </ReactMarkdown>
  )
}

