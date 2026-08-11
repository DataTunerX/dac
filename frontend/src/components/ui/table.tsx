"use client"

import * as React from "react"
import {
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type ColumnSizingState,
  type Header,
  type Table as TanStackTable,
} from "@tanstack/react-table"
import { cn } from "@/lib/utils"
import {
  clampColumnSizing,
  readStoredColumnSizing,
  resolveColumnBounds,
  writeStoredColumnSizing,
} from "@/lib/table-column-sizing"
export { TableWrapper } from "./table-wrapper"

const EMPTY_ROWS: unknown[] = []
const KEYBOARD_RESIZE_STEP = 8

export type TableColumnConfig = {
  id: string
  size?: number
  minSize?: number
  maxSize?: number
}

type TableContextValue = {
  getTable: () => TanStackTable<unknown> | null
  columnConfig: TableColumnConfig[]
}

/** Subscribers re-render when column widths change (headers + colgroup only). */
type ColumnSizingContextValue = {
  sizingVersion: number
}

const TableContext = React.createContext<TableContextValue>({
  getTable: () => null,
  columnConfig: [],
})

const ColumnSizingContext = React.createContext<ColumnSizingContextValue>({
  sizingVersion: 0,
})

function findHeader(
  table: TanStackTable<unknown> | null,
  columnId?: string,
): Header<unknown, unknown> | undefined {
  if (!table || !columnId) return undefined
  return table.getFlatHeaders().find((header) => header.column.id === columnId)
}

function columnLabel(children: React.ReactNode, columnId?: string): string {
  if (typeof children === "string" && children.trim()) return children.trim()
  if (typeof children === "number") return String(children)
  return columnId ?? "列"
}

function ColumnResizeHandle({
  header,
  label,
  columnConfig,
}: {
  header: Header<unknown, unknown>
  label: string
  columnConfig: TableColumnConfig[]
}) {
  const minSize = header.column.columnDef.minSize ?? 56
  const maxSize = header.column.columnDef.maxSize ?? 480
  const table = header.getContext().table

  const setWidth = React.useCallback(
    (width: number) => {
      const clamped = Math.min(maxSize, Math.max(minSize, width))
      table.setColumnSizing((prev) => {
        const next = { ...prev, [header.column.id]: clamped }
        return columnConfig.length ? clampColumnSizing(next, columnConfig) : next
      })
    },
    [columnConfig, header.column.id, maxSize, minSize, table],
  )

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 1 : KEYBOARD_RESIZE_STEP
    const current = header.getSize()

    switch (event.key) {
      case "ArrowLeft":
        event.preventDefault()
        setWidth(current - step)
        break
      case "ArrowRight":
        event.preventDefault()
        setWidth(current + step)
        break
      case "Home":
        event.preventDefault()
        setWidth(minSize)
        break
      case "End":
        event.preventDefault()
        setWidth(maxSize)
        break
      default:
        break
    }
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={`调整「${label}」列宽`}
      aria-valuemin={minSize}
      aria-valuemax={maxSize}
      aria-valuenow={header.getSize()}
      tabIndex={0}
      onKeyDown={onKeyDown}
      onMouseDown={header.getResizeHandler()}
      onTouchStart={header.getResizeHandler()}
      onDoubleClick={() => header.column.resetSize()}
      className={cn(
        "absolute -right-2 top-0 z-10 flex h-full w-4 cursor-col-resize touch-none select-none items-stretch justify-center bg-transparent",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cta/40 focus-visible:ring-offset-1",
        "after:absolute after:inset-y-2 after:w-px after:bg-line hover:after:bg-cta/60",
        header.column.getIsResizing() && "after:bg-cta/60",
      )}
    />
  )
}

function TableColGroup() {
  React.useContext(ColumnSizingContext)
  const { getTable } = React.useContext(TableContext)
  const table = getTable()
  if (!table) return null

  return (
    <colgroup>
      {table.getFlatHeaders().map((header) => (
        <col
          key={header.id}
          style={{
            width: header.getSize(),
            minWidth: header.column.columnDef.minSize,
            maxWidth: header.column.columnDef.maxSize,
          }}
        />
      ))}
    </colgroup>
  )
}

export type TableProps = React.TableHTMLAttributes<HTMLTableElement> & {
  /** Column sizing config — enables drag-to-resize when provided. */
  columns?: TableColumnConfig[]
  /** Persist column widths in localStorage for this table instance. */
  storageKey?: string
}

export function Table({
  className,
  columns: columnConfig,
  storageKey,
  children,
  style,
  ...props
}: TableProps) {
  const resizable = (columnConfig?.length ?? 0) > 0
  const stableColumnConfig = React.useMemo(
    () => columnConfig ?? [],
    [columnConfig],
  )

  // SSR + first client paint use defaults; load localStorage after hydration.
  const [columnSizing, setColumnSizing] = React.useState<ColumnSizingState>({})
  const [sizingLoaded, setSizingLoaded] = React.useState(!storageKey)
  const [sizingVersion, bumpSizing] = React.useReducer((n: number) => n + 1, 0)
  const tableRef = React.useRef<TanStackTable<unknown> | null>(null)

  React.useEffect(() => {
    if (!storageKey || !resizable) {
      setSizingLoaded(true)
      return
    }
    setColumnSizing(readStoredColumnSizing(storageKey, stableColumnConfig))
    setSizingLoaded(true)
  }, [resizable, stableColumnConfig, storageKey])

  const columnDefs = React.useMemo<ColumnDef<unknown>[]>(
    () =>
      stableColumnConfig.map((column) => {
        const bounds = resolveColumnBounds(column)
        return {
          id: column.id,
          accessorKey: column.id,
          header: column.id,
          size: bounds.size,
          minSize: bounds.minSize,
          maxSize: bounds.maxSize,
          enableResizing: true,
        }
      }),
    [stableColumnConfig],
  )

  const table = useReactTable({
    data: EMPTY_ROWS,
    columns: columnDefs,
    state: resizable ? { columnSizing } : undefined,
    onColumnSizingChange: resizable
      ? (updater) => {
          setColumnSizing((prev) => {
            const next =
              typeof updater === "function" ? updater(prev) : updater
            return stableColumnConfig.length
              ? clampColumnSizing(next, stableColumnConfig)
              : next
          })
          bumpSizing()
        }
      : undefined,
    columnResizeMode: "onChange",
    enableColumnResizing: resizable,
    getCoreRowModel: getCoreRowModel(),
  })

  tableRef.current = table

  const isResizing = Boolean(table.getState().columnSizingInfo.isResizingColumn)
  const wasResizingRef = React.useRef(false)

  React.useEffect(() => {
    if (!storageKey || !resizable || !sizingLoaded) return

    const wasResizing = wasResizingRef.current
    wasResizingRef.current = isResizing

    if (wasResizing && !isResizing) {
      writeStoredColumnSizing(storageKey, columnSizing)
    }
  }, [columnSizing, isResizing, resizable, sizingLoaded, storageKey])

  const tableContextValue = React.useMemo<TableContextValue>(
    () => ({
      getTable: () => tableRef.current,
      columnConfig: stableColumnConfig,
    }),
    [stableColumnConfig],
  )

  const sizingContextValue = React.useMemo(
    () => ({ sizingVersion }),
    [sizingVersion],
  )

  return (
    <TableContext.Provider value={tableContextValue}>
      <ColumnSizingContext.Provider value={sizingContextValue}>
        <div className={cn("w-full", resizable && "overflow-x-auto")}>
          <table
            className={cn(
              "w-full min-w-full text-sm caption-bottom",
              resizable && "table-fixed",
              className,
            )}
            style={
              resizable
                ? {
                    ...style,
                    minWidth: Math.max(table.getCenterTotalSize(), 0),
                  }
                : style
            }
            {...props}
          >
            {resizable ? <TableColGroup /> : null}
            {children}
          </table>
        </div>
      </ColumnSizingContext.Provider>
    </TableContext.Provider>
  )
}

export const TableHeader = React.memo(function TableHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("bg-surface-muted", className)} {...props} />
})

export const TableBody = React.memo(function TableBody({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={className} {...props} />
})

export const TableRow = React.memo(function TableRow({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn(
        "border-b border-line transition-colors hover:bg-surface-muted/50 data-[state=selected]:bg-surface-muted",
        className,
      )}
      {...props}
    />
  )
})

export type TableHeadProps = React.ThHTMLAttributes<HTMLTableCellElement> & {
  columnId?: string
}

export function TableHead({
  className,
  style,
  columnId,
  children,
  scope = "col",
  ...props
}: TableHeadProps) {
  React.useContext(ColumnSizingContext)
  const { getTable, columnConfig } = React.useContext(TableContext)
  const table = getTable()
  const header = findHeader(table, columnId)
  const resizable = Boolean(header?.column.getCanResize())
  const label = columnLabel(children, columnId)

  return (
    <th
      scope={scope}
      className={cn(
        "relative px-4 py-3 text-left text-xs font-semibold text-content",
        resizable && "select-none",
        className,
      )}
      style={style}
      {...props}
    >
      {children}
      {resizable && header ? (
        <ColumnResizeHandle
          header={header}
          label={label}
          columnConfig={columnConfig}
        />
      ) : null}
    </th>
  )
}

export type TableCellProps = React.TdHTMLAttributes<HTMLTableCellElement> & {
  columnId?: string
}

export const TableCell = React.memo(function TableCell({
  className,
  style,
  columnId: _columnId,
  ...props
}: TableCellProps) {
  return (
    <td
      // overflow-hidden keeps table-fixed columns from painting over neighbors
      className={cn("px-4 py-3 align-middle overflow-hidden", className)}
      style={style}
      {...props}
    />
  )
})
