import { useEffect, useState } from 'react'

import { API_BASE_URL, fetchHealth } from './api'
import './App.css'

type ConnectionState = 'checking' | 'connected' | 'unavailable'

function App() {
  const [connectionState, setConnectionState] =
    useState<ConnectionState>('checking')

  useEffect(() => {
    const controller = new AbortController()

    fetchHealth(controller.signal)
      .then(() => setConnectionState('connected'))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          setConnectionState('unavailable')
        }
      })

    return () => controller.abort()
  }, [])

  const statusMessage = {
    checking: 'Checking backend…',
    connected: 'Backend connected',
    unavailable: 'Backend unavailable',
  }[connectionState]

  return (
    <main>
      <section className="status-card" aria-live="polite">
        <p className="eyebrow">Draft 1 OCR Pipeline</p>
        <h1>Development environment</h1>
        <div className={`connection-status ${connectionState}`}>
          <span className="status-dot" aria-hidden="true" />
          <strong>{statusMessage}</strong>
        </div>
        <p className="endpoint">
          Health endpoint: <code>{API_BASE_URL}/health</code>
        </p>
      </section>
    </main>
  )
}

export default App
