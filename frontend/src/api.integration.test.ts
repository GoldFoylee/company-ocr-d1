import { describe, expect, it } from 'vitest'

import { fetchHealth } from './api'

describe('backend health integration', () => {
  it('calls the live backend through the application API client', async () => {
    await expect(fetchHealth()).resolves.toEqual({ status: 'ok' })
  })
})
