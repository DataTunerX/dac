import type { ColumnSizingState } from "@tanstack/react-table"

const STORAGE_PREFIX = "table-column-sizing:"

/** Absolute floor for any resizable column (px). */
export const COLUMN_MIN_WIDTH = 56
/** Absolute ceiling for any resizable column (px). */
export const COLUMN_MAX_WIDTH = 560
/** Min width as a fraction of the column default size. */
export const COLUMN_MIN_RATIO = 0.45
/** Max width as a fraction of the column default size. */
export const COLUMN_MAX_RATIO = 2

export type ColumnSizingColumn = {
  id: string
  size?: number
  minSize?: number
  maxSize?: number
}

export function resolveColumnBounds(column: ColumnSizingColumn): {
  size: number
  minSize: number
  maxSize: number
} {
  const size = column.size ?? 150
  const minSize =
    column.minSize ?? Math.max(COLUMN_MIN_WIDTH, Math.round(size * COLUMN_MIN_RATIO))
  const maxSize =
    column.maxSize ?? Math.min(COLUMN_MAX_WIDTH, Math.round(size * COLUMN_MAX_RATIO))

  return {
    size,
    minSize: Math.min(minSize, maxSize),
    maxSize: Math.max(minSize, maxSize),
  }
}

export function clampColumnSizing(
  sizing: ColumnSizingState,
  columns: ColumnSizingColumn[],
): ColumnSizingState {
  if (columns.length === 0) return sizing

  const bounds = new Map(
    columns.map((column) => [column.id, resolveColumnBounds(column)]),
  )
  const out: ColumnSizingState = {}

  for (const [id, width] of Object.entries(sizing)) {
    const bound = bounds.get(id)
    if (!bound || !Number.isFinite(width)) continue
    out[id] = Math.min(bound.maxSize, Math.max(bound.minSize, width))
  }

  return out
}

function getStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null
  } catch {
    return null
  }
}

function parseStoredColumnSizing(raw: string): ColumnSizingState {
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {}
    const out: ColumnSizingState = {}
    for (const [key, value] of Object.entries(parsed)) {
      const width = Number(value)
      if (Number.isFinite(width) && width > 0) out[key] = width
    }
    return out
  } catch {
    return {}
  }
}

export function readStoredColumnSizing(
  storageKey: string,
  columns?: ColumnSizingColumn[],
): ColumnSizingState {
  const storage = getStorage()
  if (!storage) return {}

  try {
    const raw = storage.getItem(`${STORAGE_PREFIX}${storageKey}`)
    if (!raw) return {}
    const sizing = parseStoredColumnSizing(raw)
    return columns?.length ? clampColumnSizing(sizing, columns) : sizing
  } catch {
    return {}
  }
}

export function writeStoredColumnSizing(
  storageKey: string,
  sizing: ColumnSizingState,
): void {
  const storage = getStorage()
  if (!storage) return
  try {
    storage.setItem(`${STORAGE_PREFIX}${storageKey}`, JSON.stringify(sizing))
  } catch {
    // ignore quota / private mode
  }
}
