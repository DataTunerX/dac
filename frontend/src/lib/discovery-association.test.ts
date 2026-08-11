import { describe, expect, it } from "vitest"
import {
  detectCreateType,
  discoveryMatchType,
  extractDataSourceEndpoint,
  getConnectionIdentity,
  isMinioConsole,
  parseEndpointFromCodeRepoPath,
  splitHostPort,
  type DiscoveredService,
} from "@/lib/discovery"

function svc(partial: Partial<DiscoveredService> & Pick<DiscoveredService, "host" | "port">): DiscoveredService {
  return {
    protocol: "tcp",
    serviceType: "http",
    tls: false,
    ...partial,
  }
}

describe("splitHostPort", () => {
  it("uses explicit port when provided", () => {
    expect(splitHostPort("10.0.0.1", "3306")).toEqual({ host: "10.0.0.1", port: "3306" })
  })

  it("splits combined host:port for MinIO", () => {
    expect(splitHostPort("10.233.74.151:9000")).toEqual({
      host: "10.233.74.151",
      port: "9000",
    })
  })

  it("returns null without a usable port", () => {
    expect(splitHostPort("10.0.0.1")).toBeNull()
  })
})

describe("parseEndpointFromCodeRepoPath", () => {
  it("parses http URL with explicit port", () => {
    expect(parseEndpointFromCodeRepoPath("http://10.233.74.151:8929")).toEqual({
      host: "10.233.74.151",
      port: "8929",
    })
  })

  it("defaults port for scheme", () => {
    expect(parseEndpointFromCodeRepoPath("https://gitlab.example.com/group/repo.git")).toEqual({
      host: "gitlab.example.com",
      port: "443",
    })
  })
})

describe("extractDataSourceEndpoint", () => {
  it("extracts gitlab from codeRepoPath", () => {
    expect(
      extractDataSourceEndpoint({
        type: "gitlab",
        metadata: { codeRepoPath: "http://10.233.74.151:8929" },
      })
    ).toEqual({
      matchType: "coderepo",
      host: "10.233.74.151",
      port: "8929",
    })
  })

  it("extracts minio from combined host", () => {
    expect(
      extractDataSourceEndpoint({
        type: "minio",
        metadata: { host: "10.233.74.151:9000", bucket: "dac-files" },
      })
    ).toEqual({
      matchType: "minio",
      host: "10.233.74.151",
      port: "9000",
    })
  })

  it("extracts mysql host+port", () => {
    expect(
      extractDataSourceEndpoint({
        type: "mysql",
        metadata: { host: "10.0.0.1", port: "3306" },
      })
    ).toEqual({
      matchType: "mysql",
      host: "10.0.0.1",
      port: "3306",
    })
  })
})

describe("discovery create / match types", () => {
  const gitlab = svc({
    host: "10.233.74.151",
    port: 8929,
    product: "gitlab",
    metadata: { "http.server": "nginx", "http.status": "302" },
  })
  const minioApi = svc({
    host: "10.233.74.151",
    port: 9000,
    product: "minio",
    metadata: { "http.server": "MinIO", "http.status": "403" },
  })
  const minioConsole = svc({
    host: "10.233.74.151",
    port: 9001,
    product: "minio",
    metadata: { "http.server": "MinIO Console", "http.status": "200" },
  })
  const nginx = svc({
    host: "10.233.74.151",
    port: 8060,
    product: "nginx 1.24.0",
    metadata: { "http.server": "nginx/1.24.0", "http.status": "404" },
  })

  it("allows create for gitlab and minio api", () => {
    expect(detectCreateType(gitlab)).toBe("coderepo")
    expect(detectCreateType(minioApi)).toBe("minio")
  })

  it("blocks create for minio console and nginx", () => {
    expect(isMinioConsole(minioConsole)).toBe(true)
    expect(detectCreateType(minioConsole)).toBeNull()
    expect(detectCreateType(nginx)).toBeNull()
  })

  it("allows create for fileserver", () => {
    expect(
      detectCreateType(
        svc({ host: "10.233.74.151", port: 8000, product: "fileserver" })
      )
    ).toBe("fileserver")
  })

  it("matches created gitlab/minio identities to discovered services", () => {
    const gitlabDs = extractDataSourceEndpoint({
      type: "gitlab",
      metadata: { codeRepoPath: "http://10.233.74.151:8929" },
    })!
    const minioDs = extractDataSourceEndpoint({
      type: "minio",
      metadata: { host: "10.233.74.151:9000" },
    })!

    expect(getConnectionIdentity(discoveryMatchType(gitlab), gitlab.host, gitlab.port)).toBe(
      getConnectionIdentity(gitlabDs.matchType, gitlabDs.host, gitlabDs.port)
    )
    expect(getConnectionIdentity(discoveryMatchType(minioApi), minioApi.host, minioApi.port)).toBe(
      getConnectionIdentity(minioDs.matchType, minioDs.host, minioDs.port)
    )
  })

  it("keeps gitlab and minio identities distinct for incremental association", () => {
    const gitlabId = getConnectionIdentity(discoveryMatchType(gitlab), gitlab.host, gitlab.port)
    const minioId = getConnectionIdentity(discoveryMatchType(minioApi), minioApi.host, minioApi.port)
    expect(gitlabId).not.toBe(minioId)
    expect(gitlabId).toBe("coderepo://10.233.74.151:8929")
    expect(minioId).toBe("minio://10.233.74.151:9000")
  })

  it("treats multiple mysql databases on same host:port as one connection identity", () => {
    const a = extractDataSourceEndpoint({
      type: "mysql",
      metadata: { host: "10.0.0.1", port: "3306", database: "db_a" },
    })!
    const b = extractDataSourceEndpoint({
      type: "mysql",
      metadata: { host: "10.0.0.1", port: "3306", database: "db_b" },
    })!
    expect(getConnectionIdentity(a.matchType, a.host, a.port)).toBe(
      getConnectionIdentity(b.matchType, b.host, b.port)
    )
    expect(getConnectionIdentity(a.matchType, a.host, a.port)).toBe("mysql://10.0.0.1:3306")
  })
})
