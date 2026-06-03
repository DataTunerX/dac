export type DataSourceKind =
  | "mysql"
  | "postgres"
  | "minio"
  | "fileserver"
  | "coderepo"
  | "generic"

export function normalizeDataSourceKind(
  descriptorType?: string,
  sourceType?: string,
): DataSourceKind {
  const dt = String(descriptorType || "").trim().toLowerCase()
  const st = String(sourceType || "").trim().toLowerCase()

  if (dt === "structured-mysql" || st === "mysql") return "mysql"
  if (dt === "structured-postgres" || st === "postgres") return "postgres"
  if (dt === "code" || st === "github" || st === "gitee" || st === "gitlab" || st === "git") return "coderepo"
  if (st === "minio") return "minio"
  if (st === "fileserver") return "fileserver"
  return "generic"
}

export function isStructuredDataSourceKind(kind: DataSourceKind) {
  return kind === "mysql" || kind === "postgres"
}

export function getDataSourceKindLabel(kind: DataSourceKind) {
  switch (kind) {
    case "mysql":
      return "MySQL"
    case "postgres":
      return "PostgreSQL"
    case "minio":
      return "MinIO"
    case "fileserver":
      return "文件服务"
    case "coderepo":
      return "代码仓库"
    default:
      return "通用"
  }
}
