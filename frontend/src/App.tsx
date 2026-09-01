/**
 * The application shell and its routes (plan section 20).
 *
 * A skip link and a landmark structure come first, because the exit gate asks
 * for accessibility checks and those are the two things a screen-reader or
 * keyboard user notices before anything else on a dashboard with a persistent
 * navigation bar.
 */

import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, useParams } from 'react-router-dom'

import { fetchHealth, type HealthResponse } from './api'
import { AccountPage } from './pages/AccountPage'
import { DemoPage } from './pages/DemoPage'
import { EvaluationPage } from './pages/EvaluationPage'
import { PortfolioPage } from './pages/PortfolioPage'
import { ReviewPage } from './pages/ReviewPage'
import { RunPage } from './pages/RunPage'
import './styles.css'

function HealthPill() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void fetchHealth(controller.signal)
      .then(setHealth)
      .catch(() => {
        if (!controller.signal.aborted) setOffline(true)
      })
    return () => controller.abort()
  }, [])

  if (offline) {
    return (
      <span className="health-pill health-pill--offline" role="status">
        API unavailable
      </span>
    )
  }
  if (!health) {
    return (
      <span className="health-pill" role="status">
        Checking…
      </span>
    )
  }

  const absent = Object.entries(health.subsystems)
    .filter(([, item]) => item.status !== 'ready')
    .map(([name]) => name.replace(/_/g, ' '))

  // `status` is the server's judgement about whether the service can work at
  // all; `absent` is what is missing. They are not the same thing: a run
  // without a provider is `ok` and still produces a deterministic narrative
  // rather than a written one, and a pill that said only "All systems ready"
  // would hide that from the person reading the result.
  const label =
    health.status === 'ok'
      ? absent.length === 0
        ? 'All systems ready'
        : `Ready · no ${absent.join(', ')}`
      : `Degraded · ${absent.join(', ')}`

  return (
    <span
      className={`health-pill health-pill--${health.status}`}
      role="status"
      title={
        absent.length > 0
          ? `Not ready: ${absent.join(', ')}`
          : 'Every subsystem is ready'
      }
    >
      {/* One text node, not two: a pill split across children is awkward to
          query and reads as two labels to assistive technology. */}
      {`${label}${health.demo_mode ? ' · demo mode' : ''}`}
    </span>
  )
}

/**
 * Remount the account page when the account changes.
 *
 * Without a key, navigating from one account to another reuses the component
 * and leaves the previous account's chart, indicators, and history on screen
 * until the new request lands. Keying makes "a different account is a
 * different page" true in React rather than something each effect has to
 * remember to undo.
 */
function KeyedAccountPage() {
  const { accountId = '' } = useParams()
  return <AccountPage key={accountId} />
}

/** Remount the run page when the run changes, for the same reason. */
function KeyedRunPage() {
  const { runId = '' } = useParams()
  return <RunPage key={runId} />
}

export function App() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>

      <header className="app-bar">
        <div className="app-bar__brand">
          <span className="app-bar__mark" aria-hidden="true" />
          <span>
            <strong>Meridian</strong>
            <span className="app-bar__sub">Account health forecasting</span>
          </span>
        </div>
        <nav aria-label="Primary">
          <NavLink to="/" end>
            Portfolio
          </NavLink>
          <NavLink to="/review">Review queue</NavLink>
          <NavLink to="/evaluation">Evaluation</NavLink>
        </nav>
        <HealthPill />
      </header>

      <main id="main">
        <Routes>
          <Route path="/" element={<PortfolioPage />} />
          <Route path="/accounts/:accountId" element={<KeyedAccountPage />} />
          <Route path="/runs/:runId" element={<KeyedRunPage />} />
          <Route path="/demo/:kind" element={<DemoPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
          <Route
            path="*"
            element={
              <div className="page">
                <h1>Page not found</h1>
                <p>
                  <NavLink to="/" className="inline-link">
                    Back to the portfolio
                  </NavLink>
                </p>
              </div>
            }
          />
        </Routes>
      </main>

      <footer className="app-footer">
        <p>
          Read-only decision support over synthetic data. No automated customer
          action. CMU Agentic AI capstone.
        </p>
      </footer>
    </>
  )
}
