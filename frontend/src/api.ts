const configuredApiBaseUrl =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const API_BASE_URL = configuredApiBaseUrl.replace(/\/$/, '')

export type HealthResponse = {
  status: 'ok'
}

export type ReviewQueueItem = {
  id: number
  sheet_id: number
  field_name: string
  image_crop_ref: string
  raw_ocr_value: string
  confidence: number | null
  rule_flag: boolean
  rule_flag_reason: string | null
  final_value: string | null
  reviewer_id: number | null
  created_at: string
  reviewed_at: string | null
  vehicle: string | null
  branch: string | null
  sheet_date: string | null
  sheet_status: string | null
}

export type FieldCorrectionResponse = {
  id: number
  sheet_id: number
  field_name: string
  image_crop_ref: string
  raw_ocr_value: string
  confidence: number | null
  rule_flag: boolean
  rule_flag_reason: string | null
  final_value: string | null
  reviewer_id: number | null
  created_at: string
  reviewed_at: string | null
}

export type SheetVerificationResponse = {
  id: number
  vehicle: string
  branch: string
  date: string
  image_path: string
  status: string
  force_verified: boolean
  force_verified_by: number | null
  force_verified_at: string | null
  verified_via_force: boolean
  unreviewed_flagged_count: number
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init)

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') {
        message = body.detail
      }
    } catch {
      // Keep the status-based fallback when the response is not JSON.
    }
    throw new ApiError(response.status, message)
  }

  return (await response.json()) as T
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const body = await requestJson<unknown>('/health', { signal })
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

export function fetchReviewQueue(signal?: AbortSignal): Promise<ReviewQueueItem[]> {
  return requestJson<ReviewQueueItem[]>('/review/queue', { signal })
}

export function submitFieldCorrection(
  extractionId: number,
  finalValue: string,
): Promise<FieldCorrectionResponse> {
  return requestJson<FieldCorrectionResponse>(
    `/review/fields/${extractionId}/correction`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ final_value: finalValue }),
    },
  )
}

export function verifySheet(sheetId: number): Promise<SheetVerificationResponse> {
  return requestJson<SheetVerificationResponse>(`/review/sheets/${sheetId}/verify`, {
    method: 'POST',
  })
}
