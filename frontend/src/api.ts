const configuredApiBaseUrl =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const API_BASE_URL = configuredApiBaseUrl.replace(/\/$/, '')

export type HealthResponse = {
  status: 'ok'
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`, { signal })

  if (!response.ok) {
    throw new Error(`Health request failed with status ${response.status}`)
  }

  const body: unknown = await response.json()
  if (
    typeof body !== 'object' ||
    body === null ||
    !('status' in body) ||
    body.status !== 'ok'
  ) {
    throw new Error('Health response did not match the expected contract')
  }

  return { status: 'ok' }
}
