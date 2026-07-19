import { stripModelLeakTags } from "@/lib/strip-model-leak-tags"

/** Fence-aware line scan — all line transforms share this so code blocks stay untouched. */
function pushMappedLines(out: string[], chunk: string | string[]) {
  const parts = Array.isArray(chunk) ? chunk : [chunk]
  for (const part of parts) {
    if (part.includes("\n")) out.push(...part.split("\n"))
    else out.push(part)
  }
}

function mapLines(
  text: string,
  fn: (line: string, ctx: { inFence: boolean }) => string | string[]
): string {
  const lines = (text || "").split("\n")
  let inFence = false
  const out: string[] = []
  for (const line of lines) {
    if (/^\s*```/.test(line)) inFence = !inFence
    pushMappedLines(out, fn(line, { inFence }))
  }
  return out.join("\n")
}

function unescapeJsonLike(input: string): string {
  return input
    .replace(/\\n/g, "\n")
    .replace(/\\r/g, "\r")
    .replace(/\\t/g, "\t")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, "\\")
}

function collapseExcessiveNewlines(input: string): string {
  return input.replace(/\n{4,}/g, "\n\n\n")
}

function balanceCodeFences(input: string): string {
  const lines = input.split("\n")
  let count = 0
  for (const line of lines) {
    if (/^\s*```\s*[\w-]*\s*$/.test(line)) count++
  }
  if (count % 2 === 0) return input
  return input.trimEnd() + "\n\n```\n"
}

// --- GFM tables (model output repair) ---

function parseTableCells(row: string): string[] {
  const parts = row.split("|").map((c) => c.trim())
  if (parts.length && parts[0] === "") parts.shift()
  if (parts.length && parts[parts.length - 1] === "") parts.pop()
  return parts
}

function isSeparatorLine(line: string): boolean {
  const t = line.trim()
  if (!t.includes("|") || !t.includes("-")) return false
  return /^[|:\-\s]+$/.test(t)
}

/**
 * Squashed single-line tables always include a separator on the same line.
 * Do not treat normal rows that merely have empty cells (`|  |`) as squashed —
 * that previously corrupted schema tables with blank Key/Comment columns.
 */
function lineLooksLikeSquashedTable(line: string): boolean {
  if (!line.includes("|")) return false
  if (!/\|[\s:]*-{3,}/.test(line)) return false
  return (line.match(/\|/g)?.length ?? 0) >= 6
}

function alignSeparatorToHeader(table: string): string {
  const rows = table.split("\n").filter((l) => l.trim())
  if (rows.length < 2) return table
  const headerCols = parseTableCells(rows[0]).length
  const sepCols = parseTableCells(rows[1]).length
  if (headerCols > 0 && sepCols > 0 && sepCols !== headerCols) {
    rows[1] = `| ${Array.from({ length: headerCols }, () => ":---").join(" | ")} |`
  }
  return rows.join("\n")
}

/** Index of the closing `|` after the Nth cell, or -1. */
function indexAfterNthCell(row: string, n: number): number {
  let count = 0
  let i = row.indexOf("|")
  if (i < 0) return -1
  for (i = i + 1; i < row.length; i++) {
    if (row[i] === "|") {
      count++
      if (count === n) return i
    }
  }
  return -1
}

/**
 * Split a data line that still has multiple logical rows joined by `| |`.
 * Uses header column count so empty cells inside a single row are preserved.
 */
function splitDataLineByColumnCount(row: string, headerCols: number): string[] {
  const results: string[] = []
  let remaining = row.trim()
  if (!remaining.startsWith("|")) remaining = `| ${remaining}`

  while (remaining) {
    const cells = parseTableCells(remaining)
    if (cells.length <= headerCols) {
      results.push(remaining)
      break
    }
    const splitAt = indexAfterNthCell(remaining, headerCols)
    if (splitAt < 0) {
      results.push(remaining)
      break
    }
    results.push(remaining.slice(0, splitAt + 1).trim())
    remaining = remaining.slice(splitAt + 1).trim()
    if (remaining && !remaining.startsWith("|")) remaining = `| ${remaining}`
  }
  return results.filter(Boolean)
}

function splitOversizedDataRows(table: string): string {
  const rows = table.split("\n").filter((l) => l.trim())
  if (rows.length < 2) return table
  const headerCols = parseTableCells(rows[0]).length
  if (headerCols < 1) return table

  const out: string[] = []
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]
    if (i < 2 || isSeparatorLine(row)) {
      out.push(row)
      continue
    }
    out.push(...splitDataLineByColumnCount(row, headerCols))
  }
  return out.join("\n")
}

/** If a line mixes a separator with following data, break after the separator. */
function breakSeparatorFromData(line: string): string {
  const re = /\|\s*\|/g
  let match: RegExpExecArray | null
  while ((match = re.exec(line)) !== null) {
    const left = line.slice(0, match.index + 1)
    const right = line.slice(match.index + match[0].length - 1)
    if (isSeparatorLine(left) && /\|?\s*[^|:\-\s]/.test(right)) {
      return `${left}\n${right}`
    }
  }
  return line
}

function expandSquashedTableLine(line: string): string {
  const firstPipe = line.indexOf("|")
  if (firstPipe < 0) return line

  const prefix = line.slice(0, firstPipe).trimEnd()
  let table = line.slice(firstPipe).trim()
  // Break before separator: `| header | |---|---|`
  table = table.replace(/\|\s*\|(?=\s*[\s:]*-{3,})/g, "|\n|")
  table = table
    .split("\n")
    .map((l) => breakSeparatorFromData(l.trim().startsWith("|") ? l.trim() : `| ${l.trim()}`))
    .join("\n")
  table = alignSeparatorToHeader(table)
  table = splitOversizedDataRows(table)

  return prefix ? `${prefix}\n\n${table}` : table
}

function convertTablesNumberedList(text: string): string {
  const lines = text.split("\n")
  const out: string[] = []
  let inFence = false
  const isFence = (line: string) => /^\s*```/.test(line)
  const isNumbered = (line: string) => /^\s*\d+\.\s+/.test(line)
  const esc = (v: string) => v.replaceAll("|", "\\|").trim()

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

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (isFence(line)) inFence = !inFence

    if (!inFence && /Tables\s*[:：]/i.test(line)) {
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
        out.push("", "**Tables**", "", "| Table | Description |", "| :--- | :--- |")
        for (const r of rows) {
          const label = r.entity ? `${r.name} (${r.entity})` : r.name
          out.push(`| ${esc(label)} | ${esc(r.desc)} |`)
        }
        out.push("")
        i = j - 1
        continue
      }
    }

    out.push(line)
  }

  return out.join("\n")
}

function ensureBlankLineBeforeTables(text: string): string {
  const lines = text.split("\n")
  const out: string[] = []
  let inFence = false
  const isFence = (line: string) => /^\s*```/.test(line)

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const next = i + 1 < lines.length ? lines[i + 1] : ""
    if (isFence(line)) inFence = !inFence

    const isTableHeader = !inFence && line.includes("|") && isSeparatorLine(next)
    const prev = out.length ? out[out.length - 1] : ""
    if (isTableHeader && prev.trim()) out.push("")
    out.push(line)
  }
  return out.join("\n")
}

/** Expand single-line tables, then ensure a blank line before table blocks (GFM requirement). */
function repairGfmTables(text: string): string {
  const expanded = mapLines(text, (line, { inFence }) => {
    if (inFence || !lineLooksLikeSquashedTable(line)) return line
    return expandSquashedTableLine(line)
  })
  return ensureBlankLineBeforeTables(expanded)
}

/**
 * Normalize LLM / API markdown before react-markdown + remark-gfm.
 * Single pipeline: transport escapes → whitespace → fences → tables.
 */
export function prepareMarkdown(raw: string): string {
  const s = stripModelLeakTags(unescapeJsonLike(raw || ""))
  const s1 = collapseExcessiveNewlines(s)
  const s2 = balanceCodeFences(s1)
  const s3 = convertTablesNumberedList(s2)
  return repairGfmTables(s3)
}

/** @deprecated Use prepareMarkdown */
export const normalizeMarkdown = prepareMarkdown

/** @deprecated Use prepareMarkdown */
export const normalizeMarkdownTables = prepareMarkdown
