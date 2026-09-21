import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('live review workflow', () => {
  it('renders, edits, submits, and verifies synthetic review data through the real API', async () => {
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Review flagged fields' })).toBeInTheDocument()

    const driverInput = await screen.findByLabelText('Correction for Driver name')
    expect(driverInput).toHaveValue('Jahn Doe')
    fireEvent.change(driverInput, { target: { value: 'John Doe' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Driver name' }))

    expect(
      await screen.findByText('Correction saved for Driver name: John Doe.'),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText('Correction for Driver name')).not.toBeInTheDocument()

    const distanceInput = screen.getByLabelText('Correction for End km')
    fireEvent.change(distanceInput, { target: { value: '12845' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for End km' }))

    expect(await screen.findByText('All flagged fields reviewed.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Verify SYNTHETIC-01 sheet' }))

    expect(await screen.findByText('Sheet verified')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Verify SYNTHETIC-01 sheet' })).not.toBeInTheDocument()
    })
  })
})
