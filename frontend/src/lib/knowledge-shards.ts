export type KnowledgeShard = {
  content?: string
  metadata?: Record<string, unknown>
  score?: number
}

export type KnowledgeShardWithIndex = KnowledgeShard & {
  originalIndex: number
}

export type KnowledgeFileGroup = {
  id: string
  label: string
  detail?: string
  shards: KnowledgeShardWithIndex[]
}

export const UNKNOWN_KNOWLEDGE_FILE_GROUP_ID = "__unknown__"

function metaString(metadata: Record<string, unknown> | undefined, key: string): string {
  const value = metadata?.[key]
  return typeof value === "string" ? value.trim() : ""
}

function basenameFromPath(path: string): string {
  const withoutProtocol = path.replace(/^[^:]+:\/\//, "")
  const parts = withoutProtocol.split(/[/\\]/).filter(Boolean)
  return parts[parts.length - 1] || path
}

export function getKnowledgeFileGroupKey(metadata?: Record<string, unknown>): string {
  const fileName = metaString(metadata, "file_name")
  if (fileName) return `file:${fileName}`

  const minioPath = metaString(metadata, "minio_path")
  if (minioPath) return `path:${minioPath}`

  const source = metaString(metadata, "source")
  if (source && (source.includes("/") || source.includes("://"))) {
    return `path:${source}`
  }

  const filePath = metaString(metadata, "file_path")
  if (filePath) return `path:${filePath}`

  const moduleName = metaString(metadata, "module_name")
  if (moduleName) return `module:${moduleName}`

  return UNKNOWN_KNOWLEDGE_FILE_GROUP_ID
}

export function getKnowledgeFileGroupLabel(
  key: string,
  metadata?: Record<string, unknown>,
): { label: string; detail?: string } {
  if (key === UNKNOWN_KNOWLEDGE_FILE_GROUP_ID) {
    return { label: "未关联文件" }
  }

  if (key.startsWith("file:")) {
    const label = key.slice("file:".length)
    const detail = metaString(metadata, "minio_path") || metaString(metadata, "source")
    return { label, detail: detail && detail !== label ? detail : undefined }
  }

  if (key.startsWith("path:")) {
    const path = key.slice("path:".length)
    return { label: basenameFromPath(path), detail: path }
  }

  if (key.startsWith("module:")) {
    const label = key.slice("module:".length)
    const contentType = metaString(metadata, "content_type")
    return { label, detail: contentType || undefined }
  }

  return { label: key }
}

export function groupKnowledgeShards(results: KnowledgeShard[]): KnowledgeFileGroup[] {
  const map = new Map<string, KnowledgeFileGroup>()

  results.forEach((shard, originalIndex) => {
    const key = getKnowledgeFileGroupKey(shard.metadata)
    let group = map.get(key)
    if (!group) {
      const { label, detail } = getKnowledgeFileGroupLabel(key, shard.metadata)
      group = { id: key, label, detail, shards: [] }
      map.set(key, group)
    }
    group.shards.push({ ...shard, originalIndex })
  })

  return Array.from(map.values()).sort((a, b) => {
    if (a.id === UNKNOWN_KNOWLEDGE_FILE_GROUP_ID) return 1
    if (b.id === UNKNOWN_KNOWLEDGE_FILE_GROUP_ID) return -1
    const labelCmp = a.label.localeCompare(b.label, "zh-CN")
    if (labelCmp !== 0) return labelCmp
    return b.shards.length - a.shards.length
  })
}

export function getSummaryPreview(text: string): {
  preview: string
  fileCount: number
} {
  const raw = (text || "").trim()
  if (!raw) return { preview: "（空）", fileCount: 0 }

  const re = /===\s*文件:\s*([^=]+?)\s*===/g
  const matches: Array<{ idx: number; end: number }> = []
  for (;;) {
    const m = re.exec(raw)
    if (!m) break
    matches.push({ idx: m.index, end: re.lastIndex })
  }

  const intro = (matches.length > 0 ? raw.slice(0, matches[0].idx) : raw)
    .replace(/模块名称[:：]\s*/g, "")
    .replace(/模块业务描述[:：]\s*/g, "")
    .replace(/\s+/g, " ")
    .trim()

  let preview = intro
  if (!preview && matches.length > 0) {
    const start = matches[0].end
    const end = matches.length > 1 ? matches[1].idx : raw.length
    preview = raw
      .slice(start, end)
      .replace(/^文件摘要[:：]\s*/gm, "")
      .replace(/\s+/g, " ")
      .trim()
  }

  if (!preview) {
    preview = raw.replace(/\s+/g, " ").trim()
  }

  if (preview.length > 180) {
    preview = `${preview.slice(0, 180)}...`
  }

  return { preview: preview || "（空）", fileCount: matches.length }
}
