/**
 * Cluster-wide dac-configuration / dd-configuration API.
 */
import { api } from "@/lib/api"
import type {
  SystemConfigurationListResponse,
  SystemConfigurationResponse,
  SystemConfigurationVersionListResponse,
  SystemConfigurationVersionResponse,
  UpdateSystemConfigurationRequest,
} from "@/lib/api-types"

export type SystemConfigName = "dac-configuration" | "dd-configuration"

export async function listSystemConfigurations(): Promise<SystemConfigurationListResponse> {
  const res = await api.get<SystemConfigurationListResponse>("/system/configurations")
  return res.data
}

export async function getSystemConfiguration(name: SystemConfigName): Promise<SystemConfigurationResponse> {
  const res = await api.get<SystemConfigurationResponse>(
    `/system/configurations/${encodeURIComponent(name)}`
  )
  return res.data
}

export async function listSystemConfigurationVersions(
  name: SystemConfigName,
  params?: { limit?: number; offset?: number }
): Promise<SystemConfigurationVersionListResponse> {
  const res = await api.get<SystemConfigurationVersionListResponse>(
    `/system/configurations/${encodeURIComponent(name)}/versions`,
    { params }
  )
  return res.data
}

export async function getSystemConfigurationVersion(
  name: SystemConfigName,
  version: string
): Promise<SystemConfigurationVersionResponse> {
  const res = await api.get<SystemConfigurationVersionResponse>(
    `/system/configurations/${encodeURIComponent(name)}/versions/${encodeURIComponent(version)}`
  )
  return res.data
}

export async function updateSystemConfiguration(
  name: SystemConfigName,
  body: UpdateSystemConfigurationRequest
): Promise<SystemConfigurationResponse> {
  const res = await api.put<SystemConfigurationResponse>(
    `/system/configurations/${encodeURIComponent(name)}`,
    body
  )
  return res.data
}
