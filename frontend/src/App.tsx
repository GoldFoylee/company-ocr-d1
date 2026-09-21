import { useCallback, useEffect, useState, type FormEvent } from 'react'

import {
  fetchReviewQueue,
  submitFieldCorrection,
  verifySheet,
  type ReviewQueueItem,
  type SheetVerificationResponse,
} from './api'
import './App.css'

type LoadState = 'loading' | 'ready' | 'error'

type SheetSummary = {
  id: number
  vehicle: string
  branch: string
  date: string | null
}

type ReviewFieldCardProps = {
  field: ReviewQueueItem
  value: string
  isSaving: boolean
  error: string | null
  onChange: (value: string) => void
  onSubmit: () => void
}

function fieldLabel(fieldName: string): string {
  const words = fieldName.replaceAll('_', ' ')
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}`
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

export function ReviewFieldCard({
  field,
  value,
  isSaving,
  error,
  onChange,
  onSubmit,
}: ReviewFieldCardProps) {
  const label = fieldLabel(field.field_name)
  const inputId = `correction-${field.id}`
  const confidence =
    field.confidence === null ? 'Not provided' : `${Math.round(field.confidence * 100)}%`

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSubmit()
  }

  return (
    <article className="field-card">
      <div className="field-card__heading">
        <div>
          <p className="field-card__kicker">Flagged field</p>
          <h3>{label}</h3>
        </div>
        <span className="confidence">{confidence} confidence</span>
      </div>

      <dl className="field-details">
        <div>
          <dt>Raw OCR</dt>
          <dd className="ocr-value">{field.raw_ocr_value}</dd>
        </div>
        <div>
          <dt>Reason</dt>
          <dd>{field.rule_flag_reason ?? 'Manual review requested'}</dd>
        </div>
        <div>
          <dt>Crop reference</dt>
          <dd className="crop-reference">{field.image_crop_ref}</dd>
        </div>
      </dl>

      <form className="correction-form" onSubmit={handleSubmit}>
        <label htmlFor={inputId}>Correction for {label}</label>
        <div className="correction-form__controls">
          <input
            id={inputId}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            disabled={isSaving}
            required
          />
          <button
            type="submit"
            aria-label={`Save correction for ${label}`}
            disabled={isSaving || value.trim().length === 0}
          >
            {isSaving ? 'Saving…' : 'Save correction'}
          </button>
        </div>
        {error && <p className="inline-error" role="alert">{error}</p>}
      </form>
    </article>
  )
}

function App() {
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [queue, setQueue] = useState<ReviewQueueItem[]>([])
  const [sheets, setSheets] = useState<SheetSummary[]>([])
  const [drafts, setDrafts] = useState<Record<number, string>>({})
  const [savingFieldIds, setSavingFieldIds] = useState<Set<number>>(new Set())
  const [fieldErrors, setFieldErrors] = useState<Record<number, string>>({})
  const [verifyingSheetId, setVerifyingSheetId] = useState<number | null>(null)
  const [sheetErrors, setSheetErrors] = useState<Record<number, string>>({})
  const [verifiedSheets, setVerifiedSheets] = useState<
    Record<number, SheetVerificationResponse>
  >({})
  const [notice, setNotice] = useState<string | null>(null)

  const applyQueue = useCallback((items: ReviewQueueItem[]) => {
    setQueue(items)
    setDrafts((current) => {
      const next = { ...current }
      for (const item of items) {
        next[item.id] = item.final_value ?? item.raw_ocr_value
      }
      return next
    })
    setSheets((current) => {
      const byId = new Map(current.map((sheet) => [sheet.id, sheet]))
      for (const item of items) {
        byId.set(item.sheet_id, {
          id: item.sheet_id,
          vehicle: item.vehicle ?? `Sheet ${item.sheet_id}`,
          branch: item.branch ?? 'Unknown branch',
          date: item.sheet_date,
        })
      }
      return [...byId.values()]
    })
    setLoadState('ready')
  }, [])

  const loadQueue = useCallback(async () => {
    setLoadState('loading')
    try {
      applyQueue(await fetchReviewQueue())
    } catch (error) {
      setLoadState('error')
      setNotice(errorMessage(error))
    }
  }, [applyQueue])

  useEffect(() => {
    const controller = new AbortController()
    fetchReviewQueue(controller.signal)
      .then(applyQueue)
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          setLoadState('error')
          setNotice(errorMessage(error))
        }
      })
    return () => controller.abort()
  }, [applyQueue])

  async function saveCorrection(field: ReviewQueueItem) {
    const finalValue = drafts[field.id] ?? field.raw_ocr_value
    setSavingFieldIds((current) => new Set(current).add(field.id))
    setFieldErrors((current) => ({ ...current, [field.id]: '' }))
    setNotice(null)

    try {
      const corrected = await submitFieldCorrection(field.id, finalValue)
      setQueue((current) => current.filter((item) => item.id !== field.id))
      setNotice(
        `Correction saved for ${fieldLabel(field.field_name)}: ` +
          `${corrected.final_value ?? finalValue}.`,
      )
    } catch (error) {
      setFieldErrors((current) => ({
        ...current,
        [field.id]: errorMessage(error),
      }))
    } finally {
      setSavingFieldIds((current) => {
        const next = new Set(current)
        next.delete(field.id)
        return next
      })
    }
  }

  async function markVerified(sheet: SheetSummary) {
    setVerifyingSheetId(sheet.id)
    setSheetErrors((current) => ({ ...current, [sheet.id]: '' }))
    setNotice(null)

    try {
      const verified = await verifySheet(sheet.id)
      setVerifiedSheets((current) => ({ ...current, [sheet.id]: verified }))
      setNotice(`${sheet.vehicle} sheet verified.`)
    } catch (error) {
      setSheetErrors((current) => ({
        ...current,
        [sheet.id]: errorMessage(error),
      }))
    } finally {
      setVerifyingSheetId(null)
    }
  }

  return (
    <main className="review-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Draft 1 OCR Pipeline</p>
          <h1>Review flagged fields</h1>
          <p className="page-intro">
            Confirm or correct every flagged value before verifying its sheet.
          </p>
        </div>
        <button className="secondary-button" type="button" onClick={() => void loadQueue()}>
          Refresh queue
        </button>
      </header>

      {notice && <div className="notice" role="status" aria-live="polite">{notice}</div>}

      {loadState === 'loading' && <p className="state-message">Loading review queue…</p>}

      {loadState === 'error' && (
        <section className="state-panel" role="alert">
          <h2>Review queue unavailable</h2>
          <p>The backend could not return the queue.</p>
          <button type="button" onClick={() => void loadQueue()}>Try again</button>
        </section>
      )}

      {loadState === 'ready' && sheets.length === 0 && (
        <section className="state-panel state-panel--success">
          <h2>Queue clear</h2>
          <p>No flagged fields awaiting review.</p>
        </section>
      )}

      {loadState === 'ready' && sheets.length > 0 && (
        <div className="sheet-list">
          {sheets.map((sheet) => {
            const fields = queue.filter((item) => item.sheet_id === sheet.id)
            const verified = verifiedSheets[sheet.id]
            const isVerifying = verifyingSheetId === sheet.id

            return (
              <section className="sheet-card" key={sheet.id} aria-labelledby={`sheet-${sheet.id}`}>
                <header className="sheet-card__header">
                  <div>
                    <p className="sheet-label">Sheet #{sheet.id}</p>
                    <h2 id={`sheet-${sheet.id}`}>{sheet.vehicle}</h2>
                    <p>{sheet.branch} · {sheet.date ?? 'Date unavailable'}</p>
                  </div>
                  <span className={`count-badge${verified ? ' count-badge--verified' : ''}`}>
                    {verified ? 'Verified' : `${fields.length} remaining`}
                  </span>
                </header>

                {fields.map((field) => (
                  <ReviewFieldCard
                    key={field.id}
                    field={field}
                    value={drafts[field.id] ?? field.raw_ocr_value}
                    isSaving={savingFieldIds.has(field.id)}
                    error={fieldErrors[field.id] || null}
                    onChange={(value) =>
                      setDrafts((current) => ({ ...current, [field.id]: value }))
                    }
                    onSubmit={() => void saveCorrection(field)}
                  />
                ))}

                {fields.length === 0 && !verified && (
                  <div className="verify-panel">
                    <div>
                      <h3>All flagged fields reviewed.</h3>
                      <p>Verification is recorded only after the server confirms it.</p>
                    </div>
                    <button
                      type="button"
                      aria-label={`Verify ${sheet.vehicle} sheet`}
                      disabled={isVerifying}
                      onClick={() => void markVerified(sheet)}
                    >
                      {isVerifying ? 'Verifying…' : 'Verify sheet'}
                    </button>
                    {sheetErrors[sheet.id] && (
                      <p className="inline-error" role="alert">{sheetErrors[sheet.id]}</p>
                    )}
                  </div>
                )}

                {verified && (
                  <div className="verified-panel" role="status">
                    <span aria-hidden="true">✓</span>
                    <div>
                      <h3>Sheet verified</h3>
                      <p>{verified.vehicle} has no flagged fields awaiting review.</p>
                    </div>
                  </div>
                )}
              </section>
            )
          })}
        </div>
      )}
    </main>
  )
}

export default App
