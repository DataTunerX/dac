import { Badge } from "@/components/ui/badge"

export type AgentStatus = "AVAILABLE" | "CREATING" | "UNKNOWN"

export function StatusBadge({ status }: { status: AgentStatus }) {
  if (status === "AVAILABLE") {
    return (
      <Badge
        variant="outline"
        className="bg-[#ecfdf5] text-[#16a34a] border-[#bbf7d0] font-medium"
      >
        AVAILABLE
      </Badge>
    )
  }
  if (status === "CREATING") {
    return (
      <Badge variant="outline" className="bg-cta/10 text-cta border-cta/20">
        CREATING
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="bg-surface-muted text-content border-line">
      UNKNOWN
    </Badge>
  )
}
