/**
 * Shared builders for DataDescriptor create / append payloads.
 * Used by datasources list and discovery "create / continue associate" flows.
 */
import type { DataSourceResponse } from "@/lib/api-types"
import type { UpdateDescriptorRequest } from "@/lib/descriptors-api"

export type DescriptorFormInput = {
  name: string
  namespace?: string
  type: string
  host?: string
  port?: string
  user?: string
  password?: string
  databases?: string[]
  accessKey?: string
  secretKey?: string
  bucket?: string
  path?: string
  extractFiles?: string
  gpuEnabled?: "yes" | "no" | string
  pdfLoader?: string
  promptsConfigMapName?: string
  enableCodeRepo?: boolean
  codeRepoType?: string
  codeRepoPath?: string
  codeRepoBranch?: string
  codeRepoToken?: string
}

export type DescriptorSourcePayload = NonNullable<UpdateDescriptorRequest["sources"]>[number]

export type CreateDescriptorPayload = {
  name: string
  namespace: string
  descriptorType: string
  gpuEnabled: string
  pdfLoader?: string
  sources: DescriptorSourcePayload[]
}

/** Make a DB name safe as a Kubernetes object-name suffix. */
export function sanitizeDBSegment(raw: string): string {
  const cleaned = raw
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40)
  return cleaned || "db"
}

function buildBaseMetadata(data: DescriptorFormInput): Record<string, string> {
  const t = String(data.type || "").trim()
  const base: Record<string, string> = {}
  if (t === "minio") {
    const h = String(data.host ?? "").trim()
    const p = String(data.port ?? "").trim()
    base.host = p ? `${h}:${p}` : h
    base.access_key = String(data.accessKey ?? "")
    base.secret_key = String(data.secretKey ?? "")
    base.bucket = String(data.bucket ?? "")
  } else {
    base.host = String(data.host ?? "")
    base.port = String(data.port ?? "")
    if (t === "fileserver" && data.path) {
      base.path = String(data.path)
    }
  }
  return base
}

function extractFilesList(data: DescriptorFormInput): string[] {
  return String(data.extractFiles ?? "")
    .split(/\r?\n|,/g)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** Build POST body for creating a DataDescriptor from form values. */
export function buildCreateDescriptorPayload(data: DescriptorFormInput): CreateDescriptorPayload {
  const namespace = String(data.namespace || "default").trim() || "default"
  const t = String(data.type || "").trim()
  const gpuEnabled = data.gpuEnabled === "yes" ? "yes" : "no"
  const pdfLoader = data.pdfLoader ?? "auto"
  const promptsName = String(data.promptsConfigMapName || "").trim()
  const hasPrompts = Boolean(promptsName)

  const repoType = String(data.codeRepoType || "").trim()
  const repoPath = String(data.codeRepoPath || "").trim()
  const repoBranch = String(data.codeRepoBranch || "").trim()
  const repoToken = String(data.codeRepoToken || "").trim()

  const isCodeRepo = t === "coderepo"
  const isStructuredDB = t === "mysql" || t === "postgres"
  const descriptorType = isCodeRepo ? "code" : isStructuredDB ? `structured-${t}` : "unstructured"
  const name = String(data.name || "").trim()

  if (isCodeRepo) {
    const sourceType = repoType || "github"
    return {
      name,
      namespace,
      descriptorType,
      gpuEnabled,
      sources: [
        {
          name: `${name}-source`,
          type: sourceType,
          metadata: {
            codeRepoPath: repoPath,
            codeRepoBranch: repoBranch || "main",
            codeRepoToken: repoToken,
          },
          ...(hasPrompts ? { prompts: { configMapName: promptsName } } : {}),
          extract: { tables: [] },
          processing: { cleaning: [] },
        },
      ],
    }
  }

  const hasCodeRepo =
    Boolean(data.enableCodeRepo) && Boolean(repoType || repoPath || repoBranch || repoToken)
  const baseMetadata = buildBaseMetadata(data)
  const extractFiles = extractFilesList(data)

  const buildSource = (sourceName: string, metadata: Record<string, string>): DescriptorSourcePayload => ({
    name: sourceName,
    type: t,
    metadata,
    ...(hasPrompts ? { prompts: { configMapName: promptsName } } : {}),
    ...(hasCodeRepo
      ? {
          codeRepo: {
            codeRepoType: repoType,
            codeRepoPath: repoPath,
            codeRepoBranch: repoBranch,
            codeRepoToken: repoToken,
          },
        }
      : {}),
    extract: t === "minio" || t === "fileserver" ? { files: extractFiles } : { tables: [] },
    processing: { cleaning: [] },
  })

  let sources: DescriptorSourcePayload[]
  if (isStructuredDB) {
    const dbs = (data.databases ?? []).map((s) => s.trim()).filter(Boolean)
    if (dbs.length === 0) {
      throw new Error("请至少选择一个数据库")
    }
    sources = dbs.map((db) =>
      buildSource(`${name}-${sanitizeDBSegment(db)}`, {
        ...baseMetadata,
        user: String(data.user ?? ""),
        password: String(data.password ?? ""),
        database: db,
      }),
    )
  } else {
    sources = [buildSource(`${name}-source`, baseMetadata)]
  }

  return {
    name,
    namespace,
    descriptorType,
    gpuEnabled,
    ...(descriptorType === "unstructured" ? { pdfLoader } : {}),
    sources,
  }
}

/** Map an existing API source into an update payload source. */
export function toUpdateSource(src: DataSourceResponse): DescriptorSourcePayload {
  return {
    name: src.name,
    type: src.type,
    metadata: { ...(src.metadata ?? {}) },
    ...(src.prompts?.configMapName
      ? { prompts: { configMapName: src.prompts.configMapName } }
      : {}),
    ...(src.codeRepo
      ? {
          codeRepo: {
            codeRepoType: src.codeRepo.codeRepoType,
            codeRepoPath: src.codeRepo.codeRepoPath,
            codeRepoBranch: src.codeRepo.codeRepoBranch,
            codeRepoToken: src.codeRepo.codeRepoToken,
          },
        }
      : {}),
    extract: {
      tables: src.extract?.tables ?? [],
      querys: src.extract?.querys ?? [],
      files: src.extract?.files ?? [],
    },
    processing: {
      cleaning: (src.processing?.cleaning ?? []).map((c) => ({
        rule: c.rule,
        params: c.params,
      })),
    },
  }
}

/**
 * Merge newly selected databases into existing sources for the same connection.
 * Returns sources suitable for PUT + resync (no delete/recreate).
 */
export function buildAppendSources(opts: {
  existingSources: DataSourceResponse[]
  descriptorName: string
  type: "mysql" | "postgres"
  host: string
  port: string
  user: string
  password: string
  newDatabases: string[]
  promptsConfigMapName?: string
}): DescriptorSourcePayload[] {
  const existing = opts.existingSources.map(toUpdateSource)
  const existingDbs = new Set(
    existing
      .map((s) => String(s.metadata?.database ?? "").trim())
      .filter(Boolean),
  )
  const promptsName = String(opts.promptsConfigMapName || "").trim()
  const hasPrompts = Boolean(promptsName)

  const additions: DescriptorSourcePayload[] = []
  for (const db of opts.newDatabases) {
    const name = db.trim()
    if (!name || existingDbs.has(name)) continue
    existingDbs.add(name)
    additions.push({
      name: `${opts.descriptorName}-${sanitizeDBSegment(name)}`,
      type: opts.type,
      metadata: {
        host: opts.host,
        port: opts.port,
        user: opts.user,
        password: opts.password,
        database: name,
      },
      ...(hasPrompts ? { prompts: { configMapName: promptsName } } : {}),
      extract: { tables: [] },
      processing: { cleaning: [] },
    })
  }

  if (additions.length === 0) {
    throw new Error("请至少选择一个尚未关联的数据库")
  }

  return [...existing, ...additions]
}
