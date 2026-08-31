import { useEffect, useState } from 'react'

import { fetchHealth, type HealthResponse } from './api'
import './styles.css'

type HealthState =
  | { kind: 'loading' }
  | { kind: 'online'; health: HealthResponse }
  | { kind: 'offline' }

export function App() {
  const [healthState, setHealthState] = useState<HealthState>({
    kind: 'loading',
  })

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    void fetchHealth(controller.signal)
      .then((health) => {
        if (active) setHealthState({ kind: 'online', health })
      })
      .catch(() => {
        if (active) setHealthState({ kind: 'offline' })
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [])

  const isOnline = healthState.kind === 'online'

  return (
    <main>
      <section className="hero" aria-labelledby="page-title">
        <p className="eyebrow">CMU Agentic AI Capstone</p>
        <h1 id="page-title">Meridian</h1>
        <p className="lede">
          Enterprise account-health forecasting with point-in-time evidence,
          calibrated confidence, and human-review guardrails.
        </p>

        <div className="status-card" aria-live="polite">
          <span
            className={`status-dot status-dot--${healthState.kind}`}
            aria-hidden="true"
          />
          <div>
            <p className="status-label">
              {healthState.kind === 'loading'
                ? 'Checking API'
                : isOnline
                  ? 'Foundation online'
                  : 'API unavailable'}
            </p>
            <p className="status-detail">
              {isOnline
                ? `${healthState.health.service} · v${healthState.health.version} · ${
                    healthState.health.environment
                  }`
                : 'Start the backend to complete the health check.'}
            </p>
          </div>
        </div>
      </section>

      <section className="boundary" aria-labelledby="boundary-title">
        <p className="section-number">Phase 0</p>
        <h2 id="boundary-title">Engineering foundation</h2>
        <p>
          This release verifies the application shell only. Forecasting,
          retrieval, agent orchestration, and dataset access arrive in later
          validated phases.
        </p>
        <ul>
          <li>Read-only decision support</li>
          <li>Synthetic data only</li>
          <li>No automated customer action</li>
        </ul>
      </section>
    </main>
  )
}
