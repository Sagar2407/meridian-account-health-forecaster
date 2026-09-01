/**
 * The portfolio page (plan section 20.1).
 *
 * Summary cards, a sortable table, filters, and the two actions that start
 * work: assess one account, or scan a bounded slice of the portfolio.
 *
 * The scan control names its own bounds in the button's own words. A control
 * that can spend model calls should say how many before it is pressed, not
 * after.
 */

import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import {
  ApiError,
  fetchAccounts,
  fetchDemoRuns,
  fetchScan,
  startScan,
  type AccountPage,
  type AccountSummary,
  type CuratedRunSummary,
  type ScanView,
} from '../api'
import {
  EmptyNote,
  ErrorNote,
  RouteBadge,
  Spinner,
  SyntheticBanner,
} from '../components/Primitives'

type Sort = 'renewal_date' | 'acv_usd' | 'account_id'

const money = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

export function PortfolioPage() {
  const navigate = useNavigate()
  // One value rather than a page and an error that can disagree: a request
  // either produced a page or a reason it did not, and setting both separately
  // is what forces a synchronous reset inside the effect.
  const [result, setResult] = useState<
    | { kind: 'loading' }
    | { kind: 'ready'; page: AccountPage }
    | { kind: 'error'; message: string }
  >({ kind: 'loading' })
  const [segment, setSegment] = useState('')
  const [region, setRegion] = useState('')
  const [renewsWithin, setRenewsWithin] = useState('')
  const [sort, setSort] = useState<Sort>('renewal_date')
  const [scan, setScan] = useState<ScanView | null>(null)
  const [scanError, setScanError] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [curated, setCurated] = useState<CuratedRunSummary[]>([])

  useEffect(() => {
    const controller = new AbortController()
    void fetchAccounts(
      {
        segment: segment || undefined,
        region: region || undefined,
        renewsWithinDays: renewsWithin ? Number(renewsWithin) : undefined,
        sort,
        limit: 50,
      },
      controller.signal,
    )
      .then((page) => setResult({ kind: 'ready', page }))
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setResult({
          kind: 'error',
          message:
            cause instanceof ApiError
              ? cause.message
              : 'The portfolio could not be loaded.',
        })
      })
    return () => controller.abort()
  }, [segment, region, renewsWithin, sort])

  // Section 24.5's curated demo entries. An empty list is normal -- a local
  // checkout has no cache -- and the panel simply does not appear.
  useEffect(() => {
    const controller = new AbortController()
    void fetchDemoRuns(controller.signal)
      .then(setCurated)
      .catch(() => setCurated([]))
    return () => controller.abort()
  }, [])

  const runScan = useCallback(async () => {
    setScanning(true)
    setScanError(null)
    try {
      const started = await startScan({ max_accounts: 10, concurrency: 4 })
      setScan(started)
      // The scan runs on the server; poll until it settles. A scan of ten
      // offline accounts takes seconds, so this is a short wait rather than a
      // background job the page has to remember.
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 500))
        const current = await fetchScan(started.scan_id)
        setScan(current)
        if (current.status !== 'running') break
      }
    } catch (cause: unknown) {
      setScanError(
        cause instanceof ApiError
          ? cause.message
          : 'The portfolio scan could not be started.',
      )
    } finally {
      setScanning(false)
    }
  }, [])

  const page = result.kind === 'ready' ? result.page : null
  const accounts: AccountSummary[] = page?.items ?? []
  const segments = [...new Set(accounts.map((item) => item.segment))].sort()
  const regions = [...new Set(accounts.map((item) => item.region))].sort()
  const atRisk = accounts.filter((item) => item.days_to_renewal <= 90).length
  const strategic = accounts.filter((item) => item.high_value).length

  return (
    <div className="page">
      <SyntheticBanner />

      <header className="page__header">
        <div>
          <h1>Portfolio</h1>
          <p className="page__lede">
            Read-only account-health forecasting. Select an account to assess
            it, or run a bounded scan across the accounts renewing soonest.
          </p>
        </div>
      </header>

      <section className="summary-cards" aria-label="Portfolio summary">
        <article className="summary-card">
          <p className="summary-card__value">{page?.total ?? '—'}</p>
          <p className="summary-card__label">Accounts matching filters</p>
        </article>
        <article className="summary-card">
          <p className="summary-card__value">{atRisk}</p>
          <p className="summary-card__label">
            Renewing within 90 days (this page)
          </p>
        </article>
        <article className="summary-card">
          <p className="summary-card__value">{strategic}</p>
          <p className="summary-card__label">High value (this page)</p>
        </article>
        <article className="summary-card summary-card--action">
          <button
            type="button"
            className="button button--primary"
            onClick={() => void runScan()}
            disabled={scanning}
          >
            {scanning ? 'Scanning…' : 'Run portfolio scan'}
          </button>
          <p className="summary-card__label">
            Up to 10 accounts, 4 at a time, inside the configured model-call
            budget
          </p>
        </article>
      </section>

      {curated.length > 0 ? (
        <section className="curated" aria-labelledby="curated-title">
          <h2 id="curated-title">See it work, without spending anything</h2>
          <p className="curated__lede">
            Four runs recorded from the real graph. Each is replayed exactly as
            it happened and is labelled as a recording, not a live result.
          </p>
          <ul className="curated__list">
            {curated.map((item) => (
              <li key={item.kind}>
                <Link to={`/demo/${item.kind}`} className="curated__link">
                  <span className="curated__kind">
                    {item.kind.replace(/_/g, ' ')}
                  </span>
                  <span className="curated__label">{item.label}</span>
                  <span className="curated__meta">
                    {item.account_id} · routed {item.route}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {scanError ? <ErrorNote message={scanError} /> : null}
      {scan ? <ScanSummaryPanel scan={scan} /> : null}

      <section className="filters" aria-label="Filters">
        <label>
          Segment
          <select
            value={segment}
            onChange={(event) => setSegment(event.target.value)}
          >
            <option value="">All segments</option>
            {segments.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label>
          Region
          <select
            value={region}
            onChange={(event) => setRegion(event.target.value)}
          >
            <option value="">All regions</option>
            {regions.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label>
          Renewal window
          <select
            value={renewsWithin}
            onChange={(event) => setRenewsWithin(event.target.value)}
          >
            <option value="">Any</option>
            <option value="30">Within 30 days</option>
            <option value="90">Within 90 days</option>
            <option value="180">Within 180 days</option>
          </select>
        </label>
        <label>
          Sort by
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as Sort)}
          >
            <option value="renewal_date">Renewal date</option>
            <option value="acv_usd">Contract value</option>
            <option value="account_id">Account id</option>
          </select>
        </label>
      </section>

      {result.kind === 'error' ? <ErrorNote message={result.message} /> : null}
      {result.kind === 'loading' ? (
        <Spinner label="Loading the portfolio…" />
      ) : null}

      {page ? (
        <table className="data-table">
          <caption className="visually-hidden">
            Accounts matching the current filters, sorted by{' '}
            {sort.replace('_', ' ')}
          </caption>
          <thead>
            <tr>
              <th scope="col">Account</th>
              <th scope="col">Segment</th>
              <th scope="col">Region</th>
              <th scope="col">Contract value</th>
              <th scope="col">Renews</th>
              <th scope="col">Sponsor</th>
              <th scope="col">Assess</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((account) => (
              <tr key={account.account_id}>
                <th scope="row">
                  <Link to={`/accounts/${account.account_id}`}>
                    {account.account_name}
                  </Link>
                  <span className="data-table__sub">{account.account_id}</span>
                </th>
                <td>
                  {account.segment}
                  {account.high_value ? (
                    <span className="chip">high value</span>
                  ) : null}
                </td>
                <td>{account.region}</td>
                <td>{money.format(account.acv_usd)}</td>
                <td>
                  {account.renewal_date}
                  <span className="data-table__sub">
                    {account.days_to_renewal} days
                  </span>
                </td>
                <td>{account.sponsor_status}</td>
                <td>
                  <button
                    type="button"
                    className="button button--small"
                    onClick={() =>
                      void navigate(`/accounts/${account.account_id}?assess=1`)
                    }
                  >
                    Assess
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {page && accounts.length === 0 ? (
        <EmptyNote>No account matches these filters.</EmptyNote>
      ) : null}
    </div>
  )
}

function ScanSummaryPanel({ scan }: { scan: ScanView }) {
  const summary = scan.summary
  return (
    <section className="scan-panel" aria-label="Portfolio scan result">
      <header>
        <h2>Portfolio scan {scan.scan_id}</h2>
        <p className="scan-panel__status">{scan.status}</p>
      </header>
      <dl className="scan-panel__stats">
        <div>
          <dt>Scanned</dt>
          <dd>{summary.scanned}</dd>
        </div>
        <div>
          <dt>Auto-released</dt>
          <dd>{summary.auto_released}</dd>
        </div>
        <div>
          <dt>Queued for review</dt>
          <dd>{summary.queued_for_review}</dd>
        </div>
        <div>
          <dt>Abstentions</dt>
          <dd>{summary.abstentions}</dd>
        </div>
        <div>
          <dt>Model calls</dt>
          <dd>
            {summary.total_model_calls} / {scan.model_call_budget}
          </dd>
        </div>
        <div>
          <dt>Peak concurrency</dt>
          <dd>
            {summary.concurrency_observed} / {scan.concurrency_limit}
          </dd>
        </div>
      </dl>
      {summary.risk_accounts.length > 0 ? (
        <p>
          <strong>At risk:</strong>{' '}
          {summary.risk_accounts.map((id) => (
            <Link key={id} to={`/accounts/${id}`} className="inline-link">
              {id}
            </Link>
          ))}
        </p>
      ) : null}
      {summary.expansion_candidates.length > 0 ? (
        <p>
          <strong>Expansion candidates:</strong>{' '}
          {summary.expansion_candidates.map((id) => (
            <Link key={id} to={`/accounts/${id}`} className="inline-link">
              {id}
            </Link>
          ))}
        </p>
      ) : null}
      <ul className="scan-panel__runs">
        {scan.runs.map((run) => (
          <li key={run.account_id}>
            <RouteBadge route={run.route} />
            <Link to={`/accounts/${run.account_id}`} className="inline-link">
              {run.account_id}
            </Link>
            <span>
              {run.outcome ?? (run.abstained ? 'no label' : run.status)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
