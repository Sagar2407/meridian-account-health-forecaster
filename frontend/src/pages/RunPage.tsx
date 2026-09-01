/**
 * The live assessment page (plan section 20.3), and the result it becomes.
 *
 * One page rather than two. A run is a progress timeline while it is happening
 * and a decision card once it is done, and splitting those across two routes
 * would mean a reader who followed a link to a finished run saw a timeline for
 * a run that had already ended.
 *
 * Events arrive over SSE. If the stream drops, the page falls back to polling
 * rather than showing a spinner forever: a browser tab suspended on a laptop
 * lid is a routine event, not a failure worth surfacing.
 */

import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  ApiError,
  fetchAssessment,
  subscribeToRun,
  type AssessmentState,
  type TraceEvent,
} from '../api'
import { DecisionCard } from '../components/DecisionCard'
import {
  ErrorNote,
  RouteBadge,
  Spinner,
  SyntheticBanner,
} from '../components/Primitives'
import { TraceTimeline } from '../components/TraceTimeline'

export function RunPage() {
  const { runId = '' } = useParams()
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [state, setState] = useState<AssessmentState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const seen = useRef<Set<number>>(new Set())

  // No reset here: `App` keys this page by its run id, so a different run is a
  // fresh mount rather than a component that has to unwind the previous run's
  // timeline before it can show the next one.
  useEffect(() => {
    let pollTimer: ReturnType<typeof setInterval> | undefined

    const poll = () => {
      pollTimer = setInterval(() => {
        void fetchAssessment(runId)
          .then((current) => {
            setEvents(current.trace)
            if (current.status === 'completed' || current.status === 'failed') {
              setState(current)
              if (pollTimer) clearInterval(pollTimer)
            }
          })
          .catch(() => {
            if (pollTimer) clearInterval(pollTimer)
            setError('This run is no longer being tracked.')
          })
      }, 1000)
    }

    const close = subscribeToRun(
      runId,
      (event) => {
        if (seen.current.has(event.sequence)) return
        seen.current.add(event.sequence)
        setEvents((current) =>
          [...current, event].sort((a, b) => a.sequence - b.sequence),
        )
      },
      (finished) => setState(finished),
      () => {
        // The stream ended without a finished frame. Poll instead of stalling.
        poll()
      },
    )

    return () => {
      close()
      if (pollTimer) clearInterval(pollTimer)
    }
  }, [runId])

  useEffect(() => {
    if (state) return
    const controller = new AbortController()
    void fetchAssessment(runId, controller.signal)
      .then((current) => {
        if (current.status === 'completed' || current.status === 'failed')
          setState(current)
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        if (cause instanceof ApiError && cause.code === 'ACCOUNT_NOT_FOUND') {
          setError(cause.message)
        }
      })
    return () => controller.abort()
    // Runs once on mount: a run that had already finished before this page
    // opened would otherwise wait for events that will never be sent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  const finished = state?.status === 'completed' || state?.status === 'failed'

  return (
    <div className="page">
      <SyntheticBanner />

      <header className="page__header">
        <div>
          <p className="page__eyebrow">
            <Link to="/" className="inline-link">
              Portfolio
            </Link>
            {state ? (
              <>
                {' · '}
                <Link
                  to={`/accounts/${state.account_id}`}
                  className="inline-link"
                >
                  {state.account_id}
                </Link>
              </>
            ) : null}
          </p>
          <h1>{finished ? 'Assessment result' : 'Assessment in progress'}</h1>
          <p className="page__lede">Run {runId}</p>
        </div>
        {state?.route ? <RouteBadge route={state.route} /> : null}
      </header>

      {error ? <ErrorNote message={error} /> : null}

      <div className="two-column two-column--wide-left">
        <div>
          {!finished && !error ? (
            <Spinner label="Running the assessment…" />
          ) : null}

          {state?.blocked ? (
            <article className="card card--blocked">
              <h2>Request refused</h2>
              <p>{state.blocked.message}</p>
              <p className="card__provenance">
                Guardrail {state.blocked.rule_ids.join(', ') || 'intake'} ·{' '}
                {state.blocked.reason_codes.join(', ')}
              </p>
            </article>
          ) : null}

          {state?.decision ? <DecisionCard decision={state.decision} /> : null}

          {state?.status === 'failed' ? (
            <ErrorNote message={state.error ?? 'The run failed.'} />
          ) : null}
        </div>

        <aside aria-labelledby="progress-title">
          <h2 id="progress-title">Progress</h2>
          <TraceTimeline events={events} />
          {state ? (
            <dl className="run-facts">
              <div>
                <dt>Model calls</dt>
                <dd>{state.model_calls}</dd>
              </div>
              <div>
                <dt>Tokens</dt>
                <dd>{state.total_tokens}</dd>
              </div>
              {state.review_case_id ? (
                <div>
                  <dt>Review case</dt>
                  <dd>
                    <Link to="/review" className="inline-link">
                      {state.review_case_id}
                    </Link>
                  </dd>
                </div>
              ) : null}
            </dl>
          ) : null}

          {state && state.guardrails.length > 0 ? (
            <section>
              <h3>Guardrail stages</h3>
              <ul className="guardrail-list">
                {state.guardrails.map((guardrail, index) => (
                  <li key={`${guardrail.stage}-${index}`}>
                    <span
                      className={`chip chip--${guardrail.outcome === 'pass' ? 'pass' : 'fail'}`}
                    >
                      {guardrail.stage}
                    </span>
                    <span>{guardrail.message}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  )
}
