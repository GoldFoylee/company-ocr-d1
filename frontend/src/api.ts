const configuredApiBaseUrl =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const API_BASE_URL = configuredApiBaseUrl.replace(/\/$/, '')

export type HealthResponse = { status: 'ok' }

export type SheetSummary = {
  id: number
  vehicle: string
  branch: string
  date: string
  status: string
  force_verified: boolean
}

export type SheetColumn = {
  name: string
  label: string
  excluded: boolean
}

export type SheetCell = {
  id: number | null
  row_number: number
  field_name: string
  raw_ocr_value: string | null
  final_value: string | null
  effective_value: string | null
  confidence: number | null
  rule_flag: boolean
  rule_flag_reason: string | null
  reviewed_at: string | null
  needs_review: boolean
  crop_url: string | null
  excluded: boolean
  missing: boolean
}

export type SheetRow = { row_number: number; cells: SheetCell[] }
export type SheetDetail = SheetSummary & { columns: SheetColumn[]; rows: SheetRow[] }

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

export type SheetUploadResponse = {
  sheet_id: number
  row_count: number
  extraction_count: number
  status: string
}

export type SheetUploadInput = {
  image: File
  vehicle: string
  branch: string
  sheetDate: string
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function errorForResponse(response: Response): Promise<ApiError> {
  let message = `Request failed with status ${response.status}`
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') message = body.detail
  } catch {
    // Keep the status-based fallback when the response is not JSON.
  }
  return new ApiError(response.status, message)
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init)
  if (!response.ok) throw await errorForResponse(response)
  return (await response.json()) as T
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const body = await requestJson<unknown>('/health', { signal })
  if (
    typeof body !== 'object' || body === null || !('status' in body) || body.status !== 'ok'
  ) {
    throw new Error('Health response did not match the expected contract')
  }
  return { status: 'ok' }
}

export function fetchSheets(signal?: AbortSignal): Promise<SheetSummary[]> {
  return requestJson<SheetSummary[]>('/sheets', { signal })
}

export function fetchSheet(sheetId: number, signal?: AbortSignal): Promise<SheetDetail> {
  return requestJson<SheetDetail>(`/sheets/${sheetId}`, { signal })
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

export function uploadSheet(input: SheetUploadInput): Promise<SheetUploadResponse> {
  const body = new FormData()
  body.append('image', input.image)
  body.append('vehicle', input.vehicle)
  body.append('branch', input.branch)
  body.append('sheet_date', input.sheetDate)
  return requestJson<SheetUploadResponse>('/sheets/upload', { method: 'POST', body })
}

export function cropImageUrl(relativePath: string): string {
  return `${API_BASE_URL}${relativePath.startsWith('/') ? relativePath : `/${relativePath}`}`
}

export async function downloadSheetExport(sheetId: number): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/sheets/${sheetId}/export`)
  if (!response.ok) throw await errorForResponse(response)
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') ?? ''
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? `billing-${sheetId}.xlsx`
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
