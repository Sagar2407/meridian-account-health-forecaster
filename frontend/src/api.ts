export type HealthResponse = {
  status: 'ok'
  service: string
  version: string
  environment: string
  data_mode: 'synthetic'
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export async function fetchHealth(
  signal?: AbortSignal,
): Promise<HealthResponse> {
  const response = await fetch(`${apiBaseUrl}/api/health`, { signal })
  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`)
  }
  return (await response.json()) as HealthResponse
}
