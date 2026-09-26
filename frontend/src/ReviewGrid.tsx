import type { FormEvent } from 'react'

import { cropImageUrl, type SheetCell, type SheetDetail } from './api'

type ReviewGridProps = {
  sheet: SheetDetail
  activeCellId: number | null
  drafts: Record<number, string>
  savingCellIds: Set<number>
  errors: Record<number, string>
  onActivate: (cell: SheetCell) => void
  onDraftChange: (cellId: number, value: string) => void
  onSave: (cell: SheetCell) => void
}

export function ReviewGrid({
  sheet,
  activeCellId,
  drafts,
  savingCellIds,
  errors,
  onActivate,
  onDraftChange,
  onSave,
}: ReviewGridProps) {
  const labels = new Map(sheet.columns.map((column) => [column.name, column.label]))

  return (
    <div className="review-table-wrap">
      <table className="review-table" aria-label={`${sheet.vehicle} log sheet`}>
        <thead>
          <tr>
            {sheet.columns.map((column) => <th key={column.name} scope="col">{column.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {sheet.rows.map((row) => (
            <tr key={row.row_number}>
              {row.cells.map((cell) => {
                const label = labels.get(cell.field_name) ?? cell.field_name
                const isGuestName = cell.field_name === 'guest_name'
                const extractionId = cell.id
                const isFlagged = !isGuestName && cell.needs_review && extractionId !== null
                const isActive = isFlagged && extractionId === activeCellId
                const value = cell.effective_value ?? ''

                return (
                  <td
                    key={cell.field_name}
                    data-testid={`cell-${row.row_number}-${cell.field_name}`}
                    className={isFlagged ? 'review-cell review-cell--flagged' : 'review-cell'}
                    onMouseEnter={() => { if (isFlagged) onActivate(cell) }}
                  >
                    {isGuestName ? (
                      <span className="excluded-value">Excluded</span>
                    ) : isFlagged ? (
                      <>
                        <button
                          type="button"
                          className="flagged-value"
                          aria-label={`Review ${label} row ${row.row_number}`}
                          onClick={() => onActivate(cell)}
                        >
                          {value || 'Blank'}
                        </button>
                        {isActive && extractionId !== null && (
                          <CellEditor
                            cell={cell}
                            label={label}
                            value={drafts[extractionId] ?? value}
                            isSaving={savingCellIds.has(extractionId)}
                            error={errors[extractionId] || null}
                            onChange={(next) => onDraftChange(extractionId, next)}
                            onSave={() => onSave(cell)}
                          />
                        )}
                      </>
                    ) : (
                      <span className={cell.missing ? 'missing-value' : undefined}>
                        {cell.missing || !value ? '—' : value}
                      </span>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

type CellEditorProps = {
  cell: SheetCell
  label: string
  value: string
  isSaving: boolean
  error: string | null
  onChange: (value: string) => void
  onSave: () => void
}

function CellEditor({ cell, label, value, isSaving, error, onChange, onSave }: CellEditorProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSave()
  }

  return (
    <form className="cell-editor" onSubmit={handleSubmit}>
      {cell.crop_url && (
        <img
          src={cropImageUrl(cell.crop_url)}
          alt={`${label} crop for row ${cell.row_number}`}
          className="cell-editor__crop"
        />
      )}
      <p className="cell-editor__reason">
        {cell.rule_flag_reason ?? 'Manual review requested'}
      </p>
      <label>
        <span>Correction for {label} row {cell.row_number}</span>
        <input
          value={value}
          required
          autoFocus
          disabled={isSaving}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
      <button
        type="submit"
        aria-label={`Save ${label} row ${cell.row_number}`}
        disabled={isSaving || value.trim().length === 0}
      >
        {isSaving ? 'Saving…' : 'Save'}
      </button>
      {error && <p className="inline-error" role="alert">{error}</p>}
    </form>
  )
}
