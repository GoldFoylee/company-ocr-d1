import { useCallback, useEffect, useRef, useState } from 'react'

import {
  downloadSheetExport,
  fetchSheet,
  fetchSheets,
  submitFieldCorrection,
  uploadSheet,
  verifySheet,
  type SheetCell,
  type SheetDetail,
  type SheetSummary,
  type SheetUploadInput,
} from './api'
import { ReviewGrid } from './ReviewGrid'
import { UploadSheetForm } from './UploadSheetForm'
import './App.css'

type LoadState = 'loading' | 'ready' | 'error'

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

function unresolvedCount(sheet: SheetDetail | null): number {
  if (!sheet) return 0
  return sheet.rows.reduce(
    (count, row) => count + row.cells.filter(
      (cell) => cell.field_name !== 'guest_name' && cell.needs_review,
    ).length,
    0,
  )
}

function App() {
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [sheets, setSheets] = useState<SheetSummary[]>([])
  const [selectedSheetId, setSelectedSheetId] = useState<number | null>(null)
  const [selectedSheet, setSelectedSheet] = useState<SheetDetail | null>(null)
  const [isSheetLoading, setIsSheetLoading] = useState(false)
  const [activeCellId, setActiveCellId] = useState<number | null>(null)
  const [drafts, setDrafts] = useState<Record<number, string>>({})
  const [savingCellIds, setSavingCellIds] = useState<Set<number>>(new Set())
  const [cellErrors, setCellErrors] = useState<Record<number, string>>({})
  const [isUploading, setIsUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [isVerifying, setIsVerifying] = useState(false)
  const [isExporting, setIsExporting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const detailRequest = useRef(0)

  const selectSheet = useCallback(async (sheetId: number) => {
    const requestId = ++detailRequest.current
    setSelectedSheetId(sheetId)
    setIsSheetLoading(true)
    setActionError(null)
    setActiveCellId(null)
    try {
      const detail = await fetchSheet(sheetId)
      if (requestId === detailRequest.current) setSelectedSheet(detail)
    } catch (error) {
      if (requestId === detailRequest.current) setActionError(errorMessage(error))
    } finally {
      if (requestId === detailRequest.current) setIsSheetLoading(false)
    }
  }, [])

  const loadSheets = useCallback(async (preferredSheetId?: number) => {
    setLoadState('loading')
    setActionError(null)
    try {
      const items = await fetchSheets()
      setSheets(items)
      const currentId = preferredSheetId ?? selectedSheetId
      const target = items.find((item) => item.id === currentId) ?? items[0]
      if (target) await selectSheet(target.id)
      else {
        setSelectedSheetId(null)
        setSelectedSheet(null)
      }
      setLoadState('ready')
    } catch (error) {
      setLoadState('error')
      setActionError(errorMessage(error))
    }
  }, [selectSheet, selectedSheetId])

  useEffect(() => {
    let active = true
    fetchSheets()
      .then(async (items) => {
        if (!active) return
        setSheets(items)
        const target = items[0]
        if (target) {
          setSelectedSheetId(target.id)
          setIsSheetLoading(true)
          const detail = await fetchSheet(target.id)
          if (!active) return
          setSelectedSheet(detail)
          setIsSheetLoading(false)
        }
        setLoadState('ready')
      })
      .catch((error: unknown) => {
        if (!active) return
        setIsSheetLoading(false)
        setLoadState('error')
        setActionError(errorMessage(error))
      })
    return () => { active = false }
  }, [])

  function activateCell(cell: SheetCell) {
    if (cell.field_name === 'guest_name' || !cell.needs_review || cell.id === null) return
    const cellId = cell.id
    setActiveCellId(cellId)
    setDrafts((current) => ({
      ...current,
      [cellId]: current[cellId] ?? cell.effective_value ?? cell.raw_ocr_value ?? '',
    }))
  }

  async function saveCorrection(cell: SheetCell) {
    if (cell.field_name === 'guest_name' || cell.id === null) return
    const cellId = cell.id
    const finalValue = drafts[cellId] ?? cell.effective_value ?? cell.raw_ocr_value ?? ''
    setSavingCellIds((current) => new Set(current).add(cellId))
    setCellErrors((current) => ({ ...current, [cellId]: '' }))
    setNotice(null)
    try {
      const corrected = await submitFieldCorrection(cellId, finalValue)
      setSelectedSheet((current) => current ? {
        ...current,
        rows: current.rows.map((row) => ({
          ...row,
          cells: row.cells.map((item) => item.id === corrected.id ? {
            ...item,
            final_value: corrected.final_value,
            effective_value: corrected.final_value ?? finalValue,
            reviewed_at: corrected.reviewed_at,
            needs_review: false,
          } : item),
        })),
      } : current)
      setActiveCellId(null)
      setNotice('Correction saved.')
    } catch (error) {
      setCellErrors((current) => ({ ...current, [cellId]: errorMessage(error) }))
    } finally {
      setSavingCellIds((current) => {
        const next = new Set(current)
        next.delete(cellId)
        return next
      })
    }
  }

  async function processUpload(input: SheetUploadInput) {
    setIsUploading(true)
    setUploadError(null)
    setNotice(null)
    try {
      const result = await uploadSheet(input)
      const items = await fetchSheets()
      setSheets(items)
      await selectSheet(result.sheet_id)
      setLoadState('ready')
      setNotice(`Sheet #${result.sheet_id} processed with ${result.row_count} rows.`)
    } catch (error) {
      setUploadError(errorMessage(error))
    } finally {
      setIsUploading(false)
    }
  }

  async function markVerified() {
    if (!selectedSheet) return
    setIsVerifying(true)
    setActionError(null)
    setNotice(null)
    try {
      const verified = await verifySheet(selectedSheet.id)
      setSelectedSheet((current) => current ? { ...current, status: verified.status } : current)
      setSheets((current) => current.map((sheet) =>
        sheet.id === verified.id ? { ...sheet, status: verified.status } : sheet,
      ))
      setNotice(`${verified.vehicle} marked verified.`)
    } catch (error) {
      setActionError(errorMessage(error))
    } finally {
      setIsVerifying(false)
    }
  }

  async function exportSelectedSheet() {
    if (!selectedSheet) return
    setIsExporting(true)
    setActionError(null)
    try {
      await downloadSheetExport(selectedSheet.id)
      setNotice(`Excel export downloaded for ${selectedSheet.vehicle}.`)
    } catch (error) {
      setActionError(errorMessage(error))
    } finally {
      setIsExporting(false)
    }
  }

  const remaining = unresolvedCount(selectedSheet)

  return (
    <main className="review-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Draft 1 OCR Pipeline</p>
          <h1>Review log sheets</h1>
          <p className="page-intro">
            Work across the form as a table. Only cells that still need attention are highlighted.
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={() => void loadSheets()}>
          Refresh sheets
        </button>
      </header>

      <UploadSheetForm
        isUploading={isUploading}
        error={uploadError}
        onUpload={processUpload}
      />

      {notice && <div className="notice" role="status" aria-live="polite">{notice}</div>}

      {loadState === 'error' && (
        <section className="state-panel" role="alert">
          <h2>Sheets unavailable</h2>
          <p>{actionError}</p>
          <button type="button" onClick={() => void loadSheets()}>Try again</button>
        </section>
      )}

      {loadState === 'loading' && sheets.length === 0 && (
        <p className="state-message">Loading processed sheets…</p>
      )}

      {loadState === 'ready' && sheets.length === 0 && (
        <section className="state-panel">
          <h2>No processed sheets</h2>
          <p>Upload the first sheet to begin review.</p>
        </section>
      )}

      {sheets.length > 0 && (
        <div className="review-workspace">
          <aside className="sheet-switcher" aria-label="Processed sheets">
            <p className="eyebrow">Processed sheets</p>
            <div className="sheet-switcher__list">
              {sheets.map((sheet) => (
                <button
                  key={sheet.id}
                  type="button"
                  aria-label={`Open ${sheet.vehicle}`}
                  className={sheet.id === selectedSheetId ? 'sheet-option sheet-option--active' : 'sheet-option'}
                  onClick={() => void selectSheet(sheet.id)}
                >
                  <strong>{sheet.vehicle}</strong>
                  <span>{sheet.branch} · {sheet.date}</span>
                  <small>{sheet.status === 'verified' ? 'Verified' : `Sheet #${sheet.id}`}</small>
                </button>
              ))}
            </div>
          </aside>

          <section className="sheet-review" aria-live="polite">
            {isSheetLoading && <p className="state-message">Loading sheet…</p>}
            {!isSheetLoading && selectedSheet && (
              <>
                <header className="sheet-toolbar">
                  <div>
                    <p className="sheet-kicker">Sheet #{selectedSheet.id}</p>
                    <h2>{selectedSheet.vehicle}</h2>
                    <p>{selectedSheet.branch} · {selectedSheet.date}</p>
                  </div>
                  <div className="sheet-toolbar__actions">
                    <span className={remaining ? 'status-chip status-chip--attention' : 'status-chip'}>
                      {selectedSheet.status === 'verified'
                        ? 'Verified'
                        : remaining ? `${remaining} flagged` : 'Ready to verify'}
                    </span>
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={isExporting}
                      onClick={() => void exportSelectedSheet()}
                    >
                      {isExporting ? 'Preparing Excel…' : 'Export to Excel'}
                    </button>
                    {selectedSheet.status !== 'verified' && (
                      <button
                        type="button"
                        disabled={remaining > 0 || isVerifying}
                        onClick={() => void markVerified()}
                      >
                        {isVerifying ? 'Marking verified…' : 'Mark sheet verified'}
                      </button>
                    )}
                  </div>
                </header>
                {actionError && <p className="inline-error action-error" role="alert">{actionError}</p>}
                <ReviewGrid
                  sheet={selectedSheet}
                  activeCellId={activeCellId}
                  drafts={drafts}
                  savingCellIds={savingCellIds}
                  errors={cellErrors}
                  onActivate={activateCell}
                  onDraftChange={(cellId, value) =>
                    setDrafts((current) => ({ ...current, [cellId]: value }))
                  }
                  onSave={(cell) => void saveCorrection(cell)}
                />
              </>
            )}
          </section>
        </div>
      )}
    </main>
  )
}

export default App
