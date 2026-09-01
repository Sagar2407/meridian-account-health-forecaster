/**
 * A recorded run, replayed (plan sections 24.3 and 24.5).
 *
 * Section 24.3 is unambiguous about the one thing this page must not do: "if
 * the live budget is unavailable, show a clearly labeled cached run rather than
 * pretending it is live". So the label is not a subtle badge in a corner. It is
 * the first thing on the page, it names the commit and the moment the run was
 * recorded, and there is no prop or query parameter that removes it.
 *
 * Everything below the banner renders through the same `DecisionCard` and
 * `TraceTimeline` a live run uses. A second rendering path for cached runs
 * would be a path nothing else exercises, and a demo is exactly where a
 * divergence would go unnoticed.
 */

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ApiError, fetchDemoRun, type CuratedRun } from '../api'
import { DecisionCard } from '../components/DecisionCard'
import {
  ErrorNote,
  RouteBadge,
  Spinner,
  SyntheticBanner,
} from '../components/Primitives'
import { TraceTimeline } from '../components/TraceTimeline'

export function DemoPage() {
  const { kind = '' } = useParams()
  const [run, setRun] = useState<CuratedRun | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    void fetchDemoRun(kind, controller.signal)
      .then(setRun)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(
          cause instanceof ApiError
            ? cause.message
            : 'That recorded run could not be loaded.',
        )
      })
    return () => controller.abort()
  }, [kind])

  if (error) {
    return (
      <div className="page">
        <ErrorNote message={error} />
        <Link to="/" className="inline-link">
          Back to the portfolio
        </Link>
      </div>
    )
  }

  if (!run) return <Spinner label="Loading the recorded run…" />

  const decision = run.state.decision
  const blocked = run.state.blocked

  return (
    <div className="page">
      <SyntheticBanner />

      <div
        className="cached-banner"
        role="note"
        aria-label="Recorded run notice"
      >
        <strong>This is a recorded run, not a live one.</strong>{' '}
        {run.cached_note}
      </div>

      <header className="page__header">
        <div>
          <p className="page__eyebrow">
            <Link to="/" className="inline-link">
              Portfolio
            </Link>{' '}
            · recorded demo
          </p>
          <h1>{run.label}</h1>
          <p className="page__lede">
            Account {run.account_id}. Question asked: &ldquo;{run.question}
            &rdquo;
          </p>
        </div>
        <RouteBadge route={run.route} />
      </header>

      <div className="two-column two-column--wide-left">
        <div>
          {blocked ? (
            <article className="card card--blocked">
              <h2>Request refused</h2>
              <p>{blocked.message}</p>
              <p className="card__provenance">
                Guardrail {blocked.rule_ids.join(', ') || 'intake'} ·{' '}
                {blocked.reason_codes.join(', ')}
              </p>
            </article>
          ) : null}

          {decision ? <DecisionCard decision={decision} /> : null}
        </div>

        <aside aria-labelledby="recorded-progress">
          <h2 id="recorded-progress">What the run did</h2>
          <TraceTimeline events={run.state.trace} />
        </aside>
      </div>
    </div>
  )
}
