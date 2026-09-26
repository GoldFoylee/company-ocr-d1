import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import * as api from './api'
import type {
  FieldCorrectionResponse,
  SheetCell,
  SheetDetail,
  SheetSummary,
  SheetVerificationResponse,
} from './api'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return {
    ...actual,
    fetchSheets: vi.fn(),
    fetchSheet: vi.fn(),
    submitFieldCorrection: vi.fn(),
    uploadSheet: vi.fn(),
    verifySheet: vi.fn(),
    downloadSheetExport: vi.fn(),
  }
})

const FIELD_NAMES = [
  'ds_no', 'date', 'guest_name', 'start_time', 'start_km', 'close_time',
  'close_km', 'total_km', 'total_time', 'toll', 'parking', 'journey_details',
] as const
const FIELD_LABELS = [
  'DS No.', 'Date', 'Guest Name', 'Start Time', 'Start KM', 'Close Time',
  'Close KM', 'Total KM', 'Total Time', 'Toll', 'Parking', 'Journey Details',
]

const sheetOne: SheetSummary = {
  id: 7, vehicle: 'FAKE-001', branch: 'Pune', date: '2026-08-01',
  status: 'review', force_verified: false,
}
const sheetTwo: SheetSummary = {
  id: 8, vehicle: 'FAKE-002', branch: 'Mumbai', date: '2026-08-02',
  status: 'pending', force_verified: false,
}

function makeCell(fieldName: string, overrides: Partial<SheetCell> = {}): SheetCell {
  const index = FIELD_NAMES.indexOf(fieldName as (typeof FIELD_NAMES)[number])
  return {
    id: index + 100,
    row_number: 1,
    field_name: fieldName,
    raw_ocr_value: `${fieldName}-value`,
    final_value: null,
    effective_value: `${fieldName}-value`,
    confidence: 0.96,
    rule_flag: false,
    rule_flag_reason: null,
    reviewed_at: null,
    needs_review: false,
    crop_url: `/review/crops/${index + 100}`,
    excluded: false,
    missing: false,
    ...overrides,
  }
}

function makeDetail(
  sheet: SheetSummary = sheetOne,
  cellOverrides: Record<string, Partial<SheetCell>> = {},
): SheetDetail {
  return {
    ...sheet,
    columns: FIELD_NAMES.map((name, index) => ({
      name,
      label: FIELD_LABELS[index],
      excluded: name === 'guest_name',
    })),
    rows: [{
      row_number: 1,
      cells: FIELD_NAMES.map((name) => makeCell(name, {
        ...(name === 'guest_name' ? {
          id: null,
          raw_ocr_value: null,
          effective_value: null,
          crop_url: null,
          excluded: true,
        } : {}),
        ...cellOverrides[name],
      })),
    }],
  }
}

const flaggedStartKm = {
  raw_ocr_value: '1O00',
  effective_value: '1O00',
  confidence: 0.54,
  rule_flag: true,
  rule_flag_reason: 'Expected digits only',
  needs_review: true,
  crop_url: '/review/crops/104',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.fetchSheets).mockResolvedValue([sheetOne])
  vi.mocked(api.fetchSheet).mockResolvedValue(makeDetail(sheetOne, { start_km: flaggedStartKm }))
  vi.mocked(api.downloadSheetExport).mockResolvedValue(undefined)
})

describe('tabular review screen', () => {
  it('renders all physical columns in order and highlights only unresolved flags', async () => {
    render(<App />)

    const table = await screen.findByRole('table', { name: 'FAKE-001 log sheet' })
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(
      FIELD_LABELS,
    )
    expect(screen.getByTestId('cell-1-start_km')).toHaveClass('review-cell--flagged')
    expect(screen.getByTestId('cell-1-close_km')).not.toHaveClass('review-cell--flagged')
    expect(screen.queryByRole('button', { name: 'Review Close KM row 1' })).not.toBeInTheDocument()
  })

  it('shows the real crop, reason, and inline editor for a flagged cell', async () => {
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Review Start KM row 1' }))

    expect(screen.getByText('Expected digits only')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Start KM crop for row 1' })).toHaveAttribute(
      'src', expect.stringContaining('/review/crops/104'),
    )
    expect(screen.getByLabelText('Correction for Start KM row 1')).toHaveValue('1O00')
  })

  it('changes the grid only after a correction succeeds', async () => {
    const pending = deferred<FieldCorrectionResponse>()
    vi.mocked(api.submitFieldCorrection).mockReturnValue(pending.promise)
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Review Start KM row 1' }))
    fireEvent.change(screen.getByLabelText('Correction for Start KM row 1'), {
      target: { value: '1000' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save Start KM row 1' }))
    expect(screen.getByTestId('cell-1-start_km')).toHaveClass('review-cell--flagged')

    pending.resolve({
      id: 104, sheet_id: 7, field_name: 'start_km',
      image_crop_ref: '/data/crops/start-km.png', raw_ocr_value: '1O00',
      confidence: 0.54, rule_flag: true, rule_flag_reason: 'Expected digits only',
      final_value: '1000', reviewer_id: null, created_at: '2026-09-26T08:00:00Z',
      reviewed_at: '2026-09-26T08:01:00Z',
    })

    await waitFor(() => {
      expect(screen.getByTestId('cell-1-start_km')).not.toHaveClass('review-cell--flagged')
    })
    expect(screen.getByTestId('cell-1-start_km')).toHaveTextContent('1000')
    expect(screen.queryByLabelText('Correction for Start KM row 1')).not.toBeInTheDocument()
  })

  it('keeps the local draft and flag visible when correction fails', async () => {
    vi.mocked(api.submitFieldCorrection).mockRejectedValue(new Error('Save failed'))
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Review Start KM row 1' }))
    const input = screen.getByLabelText('Correction for Start KM row 1')
    fireEvent.change(input, { target: { value: '1000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Start KM row 1' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Save failed')
    expect(input).toHaveValue('1000')
    expect(screen.getByTestId('cell-1-start_km')).toHaveClass('review-cell--flagged')
  })

  it('shows a real processing state for synchronous upload and selects the result', async () => {
    const pending = deferred<{ sheet_id: number; row_count: number; extraction_count: number; status: string }>()
    vi.mocked(api.uploadSheet).mockReturnValue(pending.promise)
    vi.mocked(api.fetchSheets)
      .mockResolvedValueOnce([sheetOne])
      .mockResolvedValueOnce([sheetTwo, sheetOne])
    vi.mocked(api.fetchSheet).mockImplementation(async (sheetId) =>
      makeDetail(sheetId === sheetTwo.id ? sheetTwo : sheetOne),
    )
    render(<App />)

    await screen.findByRole('table', { name: 'FAKE-001 log sheet' })
    fireEvent.change(screen.getByLabelText('Sheet image'), {
      target: { files: [new File(['image'], 'sheet.jpg', { type: 'image/jpeg' })] },
    })
    fireEvent.change(screen.getByLabelText('Vehicle number'), { target: { value: 'FAKE-002' } })
    fireEvent.change(screen.getByLabelText('Branch'), { target: { value: 'Mumbai' } })
    fireEvent.change(screen.getByLabelText('Sheet date'), { target: { value: '2026-08-02' } })
    const processButton = screen.getByRole('button', { name: 'Process sheet' })
    fireEvent.submit(processButton.closest('form')!)

    expect(screen.getByRole('status')).toHaveTextContent('Processing sheet')
    expect(screen.getByRole('button', { name: 'Processing sheet…' })).toBeDisabled()
    pending.resolve({ sheet_id: 8, row_count: 1, extraction_count: 11, status: 'review' })

    expect(await screen.findByRole('table', { name: 'FAKE-002 log sheet' })).toBeInTheDocument()
  })

  it('switches between processed sheets', async () => {
    vi.mocked(api.fetchSheets).mockResolvedValue([sheetOne, sheetTwo])
    vi.mocked(api.fetchSheet).mockImplementation(async (sheetId) =>
      makeDetail(sheetId === sheetTwo.id ? sheetTwo : sheetOne),
    )
    render(<App />)

    await screen.findByRole('table', { name: 'FAKE-001 log sheet' })
    fireEvent.click(screen.getByRole('button', { name: 'Open FAKE-002' }))

    expect(await screen.findByRole('table', { name: 'FAKE-002 log sheet' })).toBeInTheDocument()
    expect(api.fetchSheet).toHaveBeenLastCalledWith(8)
  })

  it('marks a clean sheet verified only after server confirmation', async () => {
    vi.mocked(api.fetchSheet).mockResolvedValue(makeDetail(sheetOne))
    const pending = deferred<SheetVerificationResponse>()
    vi.mocked(api.verifySheet).mockReturnValue(pending.promise)
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Mark sheet verified' }))
    expect(screen.getByRole('button', { name: 'Marking verified…' })).toBeDisabled()
    expect(screen.queryByText('Verified')).not.toBeInTheDocument()
    pending.resolve({
      id: 7, vehicle: 'FAKE-001', branch: 'Pune', date: '2026-08-01',
      image_path: '/data/uploads/sheet.jpg', status: 'verified', force_verified: false,
      force_verified_by: null, force_verified_at: null, verified_via_force: false,
      unreviewed_flagged_count: 0,
    })

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Mark sheet verified' })).not.toBeInTheDocument()
    })
    expect(screen.getAllByText('Verified')).toHaveLength(2)
  })

  it('downloads the selected sheet through the live export API', async () => {
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Export to Excel' }))
    await waitFor(() => expect(api.downloadSheetExport).toHaveBeenCalledWith(7))
  })

  it('never renders or requests guest-name content from a malformed API payload', async () => {
    vi.mocked(api.fetchSheet).mockResolvedValue(makeDetail(sheetOne, {
      guest_name: {
        id: 999, raw_ocr_value: 'SENSITIVE PERSON', final_value: 'SENSITIVE CORRECTION',
        effective_value: 'SENSITIVE PERSON', rule_flag: true,
        rule_flag_reason: 'SENSITIVE REASON', needs_review: true,
        crop_url: '/review/crops/999', excluded: false,
      },
    }))
    render(<App />)

    await screen.findByRole('table', { name: 'FAKE-001 log sheet' })
    const guestCell = screen.getByTestId('cell-1-guest_name')
    expect(guestCell).toHaveTextContent('Excluded')
    expect(document.body).not.toHaveTextContent('SENSITIVE')
    expect(within(guestCell).queryByRole('button')).not.toBeInTheDocument()
    expect(within(guestCell).queryByRole('img')).not.toBeInTheDocument()
  })
})
