import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import App from './App'

describe('live tabular review workflow', () => {
  it('loads a physical row, corrects it, verifies it, and downloads the workbook', async () => {
    const createObjectUrl = vi.fn(() => 'blob:synthetic-export')
    const revokeObjectUrl = vi.fn()
    const clickAnchor = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectUrl })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectUrl })

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Review log sheets' })).toBeInTheDocument()
    expect(await screen.findByRole('table', { name: 'FAKE-001 log sheet' })).toBeInTheDocument()
    expect(screen.getByTestId('cell-1-guest_name')).toHaveTextContent('Excluded')

    fireEvent.click(screen.getByRole('button', { name: 'Review Start KM row 1' }))
    expect(screen.getByRole('img', { name: 'Start KM crop for row 1' })).toHaveAttribute(
      'src', expect.stringContaining('/review/crops/'),
    )
    const input = screen.getByLabelText('Correction for Start KM row 1')
    expect(input).toHaveValue('1O0')
    fireEvent.change(input, { target: { value: '100' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save Start KM row 1' }))

    expect(await screen.findByText('Ready to verify')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Mark sheet verified' }))
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Mark sheet verified' })).not.toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Export to Excel' }))
    await waitFor(() => expect(createObjectUrl).toHaveBeenCalledWith(expect.any(Blob)))
    expect(clickAnchor).toHaveBeenCalled()
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:synthetic-export')
  })
})
