"use client"

import * as React from "react"
import { ChevronDown, ChevronRight, Table as TableIcon } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Markdown } from "@/components/markdown"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"

export const SCHEMA_TABLE_COLUMNS = [
  { id: "expand", size: 56, minSize: 48, maxSize: 72 },
  { id: "tableName", size: 280, minSize: 140, maxSize: 480 },
  { id: "businessObject", size: 160, minSize: 96, maxSize: 280 },
  { id: "description", size: 360, minSize: 160, maxSize: 560 },
] as const

export type StructureTableRow = {
  tableName: string
  md: string
  entity: string
  desc: string
}

type EmptyStateProps = {
  icon: React.ComponentType<{ className?: string }>
  message: string
}

function EmptyState({ icon: Icon, message }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-content-muted">
      <Icon className="h-8 w-8 opacity-40" />
      <p className="text-sm">{message}</p>
    </div>
  )
}

export function DataSourceStructureTab({
  isStructuredSource,
  structureTitle,
  structureCountLabel,
  structureEmptyMessage,
  structureEmptyRowMessage,
  hasSignatureMeta,
  tableList,
  selectedTableName,
  onSelectTable,
  markdownComponents,
}: {
  isStructuredSource: boolean
  structureTitle: string
  structureCountLabel: string
  structureEmptyMessage: string
  structureEmptyRowMessage: string
  hasSignatureMeta: boolean
  tableList: StructureTableRow[]
  selectedTableName: string | null
  onSelectTable: (row: StructureTableRow | null) => void
  markdownComponents: React.ComponentProps<typeof Markdown>["components"]
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-medium text-content flex items-center gap-2">
          <TableIcon className="w-4 h-4 text-content-muted" />
          {structureTitle}
        </h3>
        <div className="flex items-center gap-3">
          <Badge variant="secondary" className="bg-surface border-line text-content">
            {structureCountLabel}
          </Badge>
        </div>
      </div>

      <div className="bg-surface rounded-xl border border-line shadow-sm overflow-hidden">
        <div className="p-0">
          {!isStructuredSource || !hasSignatureMeta ? (
            <EmptyState icon={TableIcon} message={structureEmptyMessage} />
          ) : (
            <div className="flex flex-col">
              <div className="flex-1 p-0 overflow-x-auto">
                <Table storageKey="datasource-schema-list" columns={[...SCHEMA_TABLE_COLUMNS]}>
                  <TableHeader className="sticky top-0 bg-surface-muted z-10 shadow-sm">
                    <TableRow>
                      <TableHead columnId="expand" className="text-center" />
                      <TableHead columnId="tableName">表名</TableHead>
                      <TableHead columnId="businessObject">业务对象</TableHead>
                      <TableHead columnId="description">描述</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tableList.length > 0 ? (
                      tableList.map((row, i) => {
                        const isExpanded = selectedTableName === row.tableName
                        return (
                          <React.Fragment key={`${row.tableName}-${i}`}>
                            <TableRow
                              className={cn(
                                "cursor-pointer transition-colors group",
                                isExpanded
                                  ? "bg-surface-muted border-b-0"
                                  : "hover:bg-surface-muted/50",
                              )}
                              onClick={() => onSelectTable(isExpanded ? null : row)}
                            >
                              <TableCell columnId="expand" className="text-center py-4 pl-4 pr-2">
                                <div
                                  className={cn(
                                    "w-6 h-6 rounded-md flex items-center justify-center transition-all duration-200",
                                    isExpanded
                                      ? "bg-surface-active text-content"
                                      : "text-content-muted group-hover:bg-surface-muted group-hover:text-content",
                                  )}
                                >
                                  {isExpanded ? (
                                    <ChevronDown className="h-4 w-4" />
                                  ) : (
                                    <ChevronRight className="h-4 w-4" />
                                  )}
                                </div>
                              </TableCell>
                              <TableCell
                                columnId="tableName"
                                className="font-mono text-sm font-medium text-content py-4"
                              >
                                <div
                                  className="min-w-0 break-all leading-snug"
                                  title={row.tableName}
                                >
                                  {row.tableName}
                                </div>
                              </TableCell>
                              <TableCell
                                columnId="businessObject"
                                className="text-sm text-content py-4"
                              >
                                <div
                                  className="min-w-0 break-words leading-snug"
                                  title={row.entity || undefined}
                                >
                                  {row.entity || "-"}
                                </div>
                              </TableCell>
                              <TableCell
                                columnId="description"
                                className="text-sm text-content-muted py-4"
                              >
                                <div
                                  className="min-w-0 break-words leading-snug line-clamp-3"
                                  title={row.desc || undefined}
                                >
                                  {row.desc || "-"}
                                </div>
                              </TableCell>
                            </TableRow>
                            {isExpanded ? (
                              <TableRow className="bg-surface-muted hover:bg-surface-muted border-t-0 border-b border-line">
                                <TableCell
                                  colSpan={4}
                                  className="p-0 border-t-0 bg-surface-muted"
                                >
                                  <div className="px-16 pb-8 pt-0 animate-in slide-in-from-top-1 duration-200 bg-surface-muted">
                                    <div className="p-0 overflow-x-auto">
                                      <Markdown components={markdownComponents}>
                                        {row.md
                                          .replace(/^\s*## Table:.*$/m, "")
                                          .trim()}
                                      </Markdown>
                                    </div>
                                  </div>
                                </TableCell>
                              </TableRow>
                            ) : null}
                          </React.Fragment>
                        )
                      })
                    ) : (
                      <TableRow>
                        <TableCell
                          colSpan={4}
                          className="h-24 text-center text-content-muted"
                        >
                          {structureEmptyRowMessage}
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
