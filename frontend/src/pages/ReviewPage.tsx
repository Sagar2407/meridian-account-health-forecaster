/**
 * The review queue (plan section 20.5).
 *
 * Priority ordering, the full decision card, and the four reviewer actions.
 * The override control requires a reason code and a note before it will submit,
 * which mirrors the server's own validator rather than replacing it: the server
 * refuses an override without them regardless, and the form's job is to make
 * that requirement visible before a reviewer has typed anything else.
 */

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  ApiError,
  fetchReviewCard,
  fetchReviewQueue,
  hasDecision,
  submitReviewDecision,
  type RegressionCase,
  type ReviewAction,
  type ReviewCard,
  type ReviewCase,
  type ReviewReasonCode,
} from '../api'
import { DecisionCard } from '../components/DecisionCard'
import {
  EmptyNote,
  ErrorNote,
  RouteBadge,
  Spinner,
  SyntheticBanner,
} from '../components/Primitives'

const REASON_CODES: ReviewReasonCode[] = [
  'agrees_with_evidence',
  'evidence_contradicts_outcome',
  'known_context_missing',
  'model_miscalibrated',
  'coverage_insufficient',
  'policy_requires_human_action',
  'other',
]

const OUTCOMES = [
  'Churned',
  'Contracted',
  'Renewed',
  'Expanded',
  'insufficient_evidence',
]

/** Red before amber, then oldest first: the queue a person should work down. */
function priority(a: ReviewCase, b: ReviewCase): number {
  const rank = (item: ReviewCase) =>
    item.route === 'red' ? 0 : item.route === 'amber' ? 1 : 2
  const byRoute = rank(a) - rank(b)
  if (byRoute !== 0) return byRoute
  return a.created_at.localeCompare(b.created_at)
}

export function ReviewPage() {
  const [cases, setCases] = useState<ReviewCase[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [loaded, setCard] = useState<{
    caseId: string
    card: ReviewCard
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [outcomeNote, setOutcomeNote] = useState<string | null>(null)
  const [regression, setRegression] = useState<RegressionCase | null>(null)

  const [action, setAction] = useState<ReviewAction>('approve')
  const [reasonCode, setReasonCode] = useState<ReviewReasonCode>(
    'agrees_with_evidence',
  )
  const [note, setNote] = useState('')
  const [correctedOutcome, setCorrectedOutcome] = useState(OUTCOMES[0])
  const [reviewer, setReviewer] = useState('reviewer@meridian.test')
  const [submitting, setSubmitting] = useState(false)

  const loadQueue = useCallback(() => {
    void fetchReviewQueue('open')
      .then((items) => {
        setCases([...items].sort(priority))
        setError(null)
      })
      .catch((cause: unknown) =>
        setError(
          cause instanceof ApiError
            ? cause.message
            : 'The review queue could not load.',
        ),
      )
  }, [])

  useEffect(loadQueue, [loadQueue])

  // The card is stored with the case it belongs to, so selecting a different
  // case replaces both together rather than clearing one and then loading the
  // other. That is what keeps a card from being shown under the wrong case id
  // for the moment between the two.
  useEffect(() => {
    if (!selected) return undefined
    const controller = new AbortController()
    void fetchReviewCard(selected, controller.signal)
      .then((loaded) => setCard({ caseId: selected, card: loaded }))
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(
          cause instanceof ApiError
            ? cause.message
            : 'The decision card could not load.',
        )
      })
    return () => controller.abort()
  }, [selected])

  const submit = async () => {
    if (!selected) return
    setSubmitting(true)
    setError(null)
    setOutcomeNote(null)
    setRegression(null)
    try {
      const result = await submitReviewDecision(selected, {
        reviewer,
        action,
        reason_code: reasonCode,
        note,
        corrected_outcome: action === 'override' ? correctedOutcome : null,
        requested_data:
          action === 'request_data'
            ? [
                {
                  source: 'retrieval_index',
                  detail: note || 'Supply the missing evidence and re-run.',
                  window: 'through the assessment cutoff',
                },
              ]
            : undefined,
      })
      setOutcomeNote(
        `Case ${result.case.case_id} resolved as ${result.case.action}.`,
      )
      setRegression(result.regression)
      setSelected(null)
      setNote('')
      loadQueue()
    } catch (cause: unknown) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : 'The decision could not be recorded.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  const card = loaded && loaded.caseId === selected ? loaded.card : null

  const overrideIncomplete =
    action === 'override' && (note.trim() === '' || reasonCode === 'other')

  return (
    <div className="page">
      <SyntheticBanner />

      <header className="page__header">
        <div>
          <p className="page__eyebrow">
            <Link to="/" className="inline-link">
              Portfolio
            </Link>
          </p>
          <h1>Review queue</h1>
          <p className="page__lede">
            Cases the system declined to release on its own, red first, then
            oldest. Every decision here is recorded; an override, a data
            request, or an escalation also files a regression case.
          </p>
        </div>
      </header>

      {error ? <ErrorNote message={error} /> : null}
      {outcomeNote ? (
        <div className="success-note" role="status">
          <p>{outcomeNote}</p>
          {regression ? (
            <p>
              Regression case <strong>{regression.regression_id}</strong>{' '}
              recorded ({regression.origin.replace(/_/g, ' ')}): system said{' '}
              {regression.system_outcome}
              {regression.reviewer_outcome
                ? `, reviewer said ${regression.reviewer_outcome}`
                : ''}
              .
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="two-column two-column--narrow-left">
        <section aria-labelledby="queue-title">
          <h2 id="queue-title">Open cases</h2>
          {!cases ? <Spinner label="Loading the queue…" /> : null}
          {cases && cases.length === 0 ? (
            <EmptyNote>Nothing is waiting for review.</EmptyNote>
          ) : null}
          <ul className="queue-list">
            {(cases ?? []).map((item) => (
              <li key={item.case_id}>
                <button
                  type="button"
                  className={`queue-item${selected === item.case_id ? ' is-selected' : ''}`}
                  onClick={() => setSelected(item.case_id)}
                  aria-pressed={selected === item.case_id}
                >
                  <RouteBadge route={item.route} />
                  <span className="queue-item__account">{item.account_id}</span>
                  <span className="queue-item__reason">{item.reason}</span>
                  <span className="queue-item__meta">{item.created_at}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="card-title">
          <h2 id="card-title">Decision card</h2>
          {!selected ? (
            <EmptyNote>
              Select a case to see what the system decided and why.
            </EmptyNote>
          ) : null}
          {selected && !card ? <Spinner label="Loading the decision…" /> : null}

          {card ? (
            <>
              <p className="card__question">
                <strong>Question asked:</strong> {card.question}
              </p>
              {hasDecision(card.decision) ? (
                <DecisionCard decision={card.decision} />
              ) : (
                <EmptyNote>
                  This case predates decision-card storage; the summary is in
                  the queue entry.
                </EmptyNote>
              )}

              <form
                className="review-form"
                onSubmit={(event) => {
                  event.preventDefault()
                  void submit()
                }}
              >
                <h3>Your decision</h3>

                <label htmlFor="reviewer">Reviewer</label>
                <input
                  id="reviewer"
                  value={reviewer}
                  onChange={(event) => setReviewer(event.target.value)}
                  required
                />

                <fieldset>
                  <legend>Action</legend>
                  {(
                    [
                      'approve',
                      'override',
                      'request_data',
                      'escalate',
                    ] as ReviewAction[]
                  ).map((option) => (
                    <label key={option} className="radio">
                      <input
                        type="radio"
                        name="action"
                        value={option}
                        checked={action === option}
                        onChange={() => setAction(option)}
                      />
                      {option.replace('_', ' ')}
                    </label>
                  ))}
                </fieldset>

                {action === 'override' ? (
                  <>
                    <label htmlFor="corrected">Correct outcome</label>
                    <select
                      id="corrected"
                      value={correctedOutcome}
                      onChange={(event) =>
                        setCorrectedOutcome(event.target.value)
                      }
                    >
                      {OUTCOMES.map((outcome) => (
                        <option key={outcome} value={outcome}>
                          {outcome}
                        </option>
                      ))}
                    </select>
                  </>
                ) : null}

                <label htmlFor="reason-code">
                  Reason code{action === 'override' ? ' (required)' : ''}
                </label>
                <select
                  id="reason-code"
                  value={reasonCode}
                  onChange={(event) =>
                    setReasonCode(event.target.value as ReviewReasonCode)
                  }
                >
                  {REASON_CODES.map((code) => (
                    <option key={code} value={code}>
                      {code.replace(/_/g, ' ')}
                    </option>
                  ))}
                </select>

                <label htmlFor="note">
                  Note{action === 'override' ? ' (required)' : ''}
                </label>
                <textarea
                  id="note"
                  rows={3}
                  maxLength={1000}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />

                {overrideIncomplete ? (
                  <p className="form-hint" role="status">
                    An override needs a specific reason code and a note. Both
                    are stored as regression metadata, so a later change can be
                    tested against this case.
                  </p>
                ) : null}

                <button
                  type="submit"
                  className="button button--primary"
                  disabled={submitting || overrideIncomplete}
                >
                  {submitting ? 'Recording…' : 'Record decision'}
                </button>
              </form>
            </>
          ) : null}
        </section>
      </div>
    </div>
  )
}
