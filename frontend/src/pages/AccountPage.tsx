/**
 * The account page (plan section 20.2).
 *
 * Profile, the 104-week trajectory with its cutoff marker, the indicator strip,
 * recent evidence, prior assessments, and the control that starts an
 * assessment.
 *
 * The question box offers safe presets and accepts free text. Free text is not
 * validated here beyond a length cap: the intake guardrail decides what is
 * answerable, and duplicating that judgement in the browser would give a reader
 * two different answers about the same request depending on where it was typed.
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import {
  ApiError,
  fetchAccount,
  startAssessment,
  type AccountDetail,
} from '../api'
import {
  EmptyNote,
  ErrorNote,
  RouteBadge,
  Spinner,
  SyntheticBanner,
} from '../components/Primitives'
import { UsageChart } from '../components/UsageChart'

const PRESETS = [
  'What is the renewal outlook for this account, and what drives it?',
  'Does support history explain the current adoption trend?',
  'What is the relationship risk on this account?',
  'Is there an expansion case here?',
]

const money = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

export function AccountPage() {
  const { accountId = '' } = useParams()
  const navigate = useNavigate()
  const [search] = useSearchParams()
  const [detail, setDetail] = useState<AccountDetail | null>(null)
  const [error, setError] = useState<{ message: string; code?: string } | null>(
    null,
  )
  const [question, setQuestion] = useState(PRESETS[0])
  const [starting, setStarting] = useState(false)

  // No state is reset here: `App` keys this page by its account id, so
  // navigating to a different account remounts it rather than leaving one
  // account's chart on screen while another one loads.
  useEffect(() => {
    const controller = new AbortController()
    void fetchAccount(accountId, controller.signal)
      .then(setDetail)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(
          cause instanceof ApiError
            ? { message: cause.message, code: cause.code }
            : { message: 'The account could not be loaded.' },
        )
      })
    return () => controller.abort()
  }, [accountId])

  const assess = async () => {
    setStarting(true)
    setError(null)
    try {
      const started = await startAssessment(accountId, question)
      void navigate(`/runs/${started.run_id}`)
    } catch (cause: unknown) {
      setError(
        cause instanceof ApiError
          ? { message: cause.message, code: cause.code }
          : { message: 'The assessment could not be started.' },
      )
      setStarting(false)
    }
  }

  if (error && !detail) {
    return (
      <div className="page">
        <ErrorNote message={error.message} code={error.code} />
        <Link to="/" className="inline-link">
          Back to the portfolio
        </Link>
      </div>
    )
  }

  if (!detail) return <Spinner label="Loading the account…" />

  const { profile, indicators } = detail
  const autoOpen = search.get('assess') === '1'

  return (
    <div className="page">
      <SyntheticBanner />

      <header className="page__header">
        <div>
          <p className="page__eyebrow">
            <Link to="/" className="inline-link">
              Portfolio
            </Link>{' '}
            · {profile.account_id}
          </p>
          <h1>{profile.account_name}</h1>
          <p className="page__lede">
            {profile.segment} · {profile.industry} · {profile.region} ·{' '}
            {money.format(profile.acv_usd)} · renews {profile.renewal_date}
          </p>
          <p className="page__cutoff">
            Effective point-in-time cutoff{' '}
            <strong>{detail.effective_cutoff}</strong>. Nothing after this date
            is available to an assessment, a chart, or a citation.
          </p>
        </div>
        {detail.high_value ? (
          <p className="chip chip--emphasis" title={detail.high_value_reason}>
            high value · {detail.high_value_reason}
          </p>
        ) : null}
      </header>

      {error ? <ErrorNote message={error.message} code={error.code} /> : null}

      <section className="assess-panel" aria-labelledby="assess-title">
        <h2 id="assess-title">Run an assessment</h2>
        <label htmlFor="question">Question</label>
        <textarea
          id="question"
          value={question}
          maxLength={500}
          rows={2}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <div className="assess-panel__presets">
          {PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              className="button button--ghost button--small"
              onClick={() => setQuestion(preset)}
            >
              {preset.slice(0, 42)}…
            </button>
          ))}
        </div>
        <button
          type="button"
          className="button button--primary"
          onClick={() => void assess()}
          disabled={starting}
          autoFocus={autoOpen}
        >
          {starting ? 'Starting…' : 'Assess this account'}
        </button>
      </section>

      <section className="indicators" aria-label="Account indicators">
        <Indicator label="Weeks observed" value={indicators.weeks_observed} />
        <Indicator
          label="Active users, last week"
          value={indicators.active_users_last_week}
        />
        <Indicator
          label="Adoption trend, 13 weeks"
          value={indicators.adoption_trend_13w}
          tone={indicators.adoption_trend_13w >= 0 ? 'positive' : 'negative'}
        />
        <Indicator label="Open tickets" value={indicators.open_tickets} />
        <Indicator
          label="Urgent tickets, 26 weeks"
          value={indicators.escalations_26w}
          tone={indicators.escalations_26w > 0 ? 'negative' : 'neutral'}
        />
        <Indicator
          label="Average ticket sentiment"
          value={indicators.average_ticket_sentiment ?? '—'}
          tone={
            indicators.average_ticket_sentiment === null
              ? 'neutral'
              : indicators.average_ticket_sentiment >= 0
                ? 'positive'
                : 'negative'
          }
        />
        <Indicator
          label="External events, 26 weeks"
          value={indicators.external_events_26w}
        />
        <Indicator
          label="Sponsor"
          value={indicators.sponsor_status}
          tone={indicators.sponsor_status === 'lost' ? 'negative' : 'neutral'}
        />
        <Indicator
          label="Onboarding"
          value={indicators.onboarding_completed ? 'complete' : 'incomplete'}
          tone={indicators.onboarding_completed ? 'positive' : 'negative'}
        />
      </section>

      <section aria-labelledby="usage-title">
        <h2 id="usage-title">Usage trajectory</h2>
        <UsageChart usage={detail.usage} cutoff={detail.effective_cutoff} />
      </section>

      <div className="two-column">
        <section aria-labelledby="recent-title">
          <h2 id="recent-title">Recent activity</h2>
          {detail.recent.length === 0 ? (
            <EmptyNote>
              No notes, tickets, or events at or before the cutoff.
            </EmptyNote>
          ) : (
            <ul className="recent-list">
              {detail.recent.map((item) => (
                <li key={`${item.kind}-${item.item_date}-${item.label}`}>
                  <span className={`chip chip--${item.signal}`}>
                    {item.kind}
                  </span>
                  <span className="recent-list__date">{item.item_date}</span>
                  <span className="recent-list__label">{item.label}</span>
                  <span className="recent-list__detail">{item.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="history-title">
          <h2 id="history-title">Previous assessments</h2>
          {detail.prior_assessments.length === 0 ? (
            <EmptyNote>
              This system has not assessed this account before. Prior
              assessments are context, never a label carried forward.
            </EmptyNote>
          ) : (
            <ul className="history-list">
              {detail.prior_assessments.map((prior) => (
                <li key={prior.assessment_id}>
                  <RouteBadge route={prior.route} />
                  <span className="history-list__outcome">
                    {prior.predicted_outcome}
                  </span>
                  <span className="history-list__meta">
                    {prior.created_at} · confidence{' '}
                    {prior.confidence.toFixed(2)} · cutoff {prior.cutoff}
                  </span>
                  <span className="history-list__summary">{prior.summary}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}

function Indicator({
  label,
  value,
  tone = 'neutral',
}: {
  label: string
  value: string | number
  tone?: 'positive' | 'negative' | 'neutral'
}) {
  return (
    <article className={`indicator indicator--${tone}`}>
      <p className="indicator__value">{value}</p>
      <p className="indicator__label">{label}</p>
    </article>
  )
}
