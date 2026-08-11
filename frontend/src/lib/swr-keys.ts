/** Shared SWR cache keys — keep list/detail navigations on the same key. */

export const AGENTS_LIST_KEY = ["agents-list-all"] as const

export const agentKey = (namespace: string, name: string) =>
  ["agent", namespace, name] as const

export const descriptorKey = (namespace: string, name: string) =>
  ["descriptor", namespace, name] as const

export const descriptorSignatureKey = (namespace: string, name: string) =>
  ["descriptor-signature", namespace, name] as const

export const descriptorSemanticDomainKey = (namespace: string, name: string) =>
  ["descriptor-semantic-domain", namespace, name] as const

export const semanticGroupKey = (id: string) => ["semantic-group", id] as const

export const discoveryScansKey = (page: number, pageSize: number) =>
  ["discovery-scans", page, pageSize] as const

export const discoveryScanKey = (id: string) => ["discovery-scan", id] as const

export const discoveryAssociationsKey = ["discovery-associations"] as const
