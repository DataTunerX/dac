import { api } from "@/lib/api"

export type GPUAvailabilityResponse = {
  available: boolean
  nodeCount: number
  totalGPUs: number
  resourceKey: string
}

export async function getGPUAvailability(): Promise<GPUAvailabilityResponse> {
  const res = await api.get<GPUAvailabilityResponse>("/environment/gpu")
  return res.data
}
