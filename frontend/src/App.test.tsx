import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ReviewFieldCard } from './App'
import type { ReviewQueueItem } from './api'

const flaggedField: ReviewQueueItem = {
  id: 41,
  sheet_id: 7,
  field_name: 'driver_name',
  image_crop_ref: '/synthetic/crops/driver-name.png',
  raw_ocr_value: 'Jahn Doe',
  confidence: 0.61,
  rule_flag: true,
  rule_flag_reason: 'Name needs review',
  final_value: null,
  reviewer_id: null,
  created_at: '2026-09-21T08:00:00Z',
  reviewed_at: null,
  vehicle: 'SYNTHETIC-01',
  branch: 'Demo',
  sheet_date: '2026-09-21',
  sheet_status: 'review',
}

function ControlledField({ onSubmit }: { onSubmit: (value: string) => void }) {
  const [value, setValue] = useState(flaggedField.raw_ocr_value)

  return (
    <ReviewFieldCard
      field={flaggedField}
      value={value}
      isSaving={false}
      error={null}
      onChange={setValue}
      onSubmit={() => onSubmit(value)}
    />
  )
}

describe('ReviewFieldCard', () => {
  it('renders the OCR value and flag reason', () => {
    render(<ControlledField onSubmit={() => undefined} />)

    expect(screen.getByRole('heading', { name: 'Driver name' })).toBeInTheDocument()
    expect(screen.getByText('Jahn Doe')).toBeInTheDocument()
    expect(screen.getByText('Name needs review')).toBeInTheDocument()
    expect(screen.getByLabelText('Correction for Driver name')).toHaveValue('Jahn Doe')
  })

  it('keeps the correction input controlled while it is edited', () => {
    render(<ControlledField onSubmit={() => undefined} />)

    const input = screen.getByLabelText('Correction for Driver name')
    fireEvent.change(input, { target: { value: 'John Doe' } })

    expect(input).toHaveValue('John Doe')
  })

  it('submits the current controlled value', () => {
    const onSubmit = vi.fn()
    render(<ControlledField onSubmit={onSubmit} />)

    fireEvent.change(screen.getByLabelText('Correction for Driver name'), {
      target: { value: 'John Doe' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Driver name' }))

    expect(onSubmit).toHaveBeenCalledWith('John Doe')
  })
})
