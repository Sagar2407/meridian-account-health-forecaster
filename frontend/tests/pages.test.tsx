/**
 * The five pages, driven through a mocked API rather than a mocked component.
 *
 * Each test stubs `fetch` and asserts what a person would see. That keeps the
 * tests honest about the contract: a change to a response shape breaks them
 * here rather than only in the browser.
 *
 * The negative assertions matter as much as the positive ones. Two of these
 * tests assert that no latent field and no prompt key appears in the rendered
 * document, which is half of the Phase 9 exit gate.
 */

import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../src/App'
import { AccountPage } from '../src/pages/AccountPage'
import { DemoPage } from '../src/pages/DemoPage'
import { EvaluationPage } from '../src/pages/EvaluationPage'
import { formatMetric } from '../src/pages/formatMetric'
import { PortfolioPage } from '../src/pages/PortfolioPage'
import { ReviewPage } from '../src/pages/ReviewPage'
import { RunPage } from '../src/pages/RunPage'
import {
  abstention,
  accountDetail,
  accountPage,
  forecast,
  health,
  reviewCard,
  reviewCase,
  runState,
  scan,
  urlOf,
} from './fixtures'

/** Latent fields that must never reach the browser. */
const LEAKY = [
  'health_band',
  'health_archetype',
  'churn_probability',
  'health_index',
  'outcome_reason',
  'usage_cliff_date',
]

/** Payload keys a trace may never carry. */
const HIDDEN = [
  'prompt',
  'system_prompt',
  'chain_of_thought',
  'messages',
  'api_key',
]

type Handler = (url: string, init?: RequestInit) => unknown

function stubApi(handler: Handler) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = urlOf(input)
    const body = handler(url, init)
    if (body === undefined) {
      return Promise.resolve(
        new Response(
          JSON.stringify({ code: 'ACCOUNT_NOT_FOUND', message: 'not found' }),
          {
            status: 404,
          },
        ),
      )
    }
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
  })
}

/** `EventSource` does not exist in jsdom; the run page must survive without it. */
class SilentEventSource {
  static instances: SilentEventSource[] = []
  onerror: (() => void) | null = null
  constructor(readonly url: string) {
    SilentEventSource.instances.push(this)
  }
  addEventListener() {}
  close() {}
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function renderAt(path: string, element: React.ReactElement, pattern: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={pattern} element={element} />
        <Route path="*" element={<p>elsewhere</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PortfolioPage', () => {
  it('lists accounts with their renewal window and contract value', async () => {
    stubApi((url) => (url.includes('/api/accounts') ? accountPage : undefined))

    renderAt('/', <PortfolioPage />, '/')

    expect(await screen.findByText('Northwind Freight')).toBeInTheDocument()
    expect(screen.getByText('QuillTelecom Co.')).toBeInTheDocument()
    expect(screen.getByText('$1,250,000')).toBeInTheDocument()
    expect(screen.getByText('62 days')).toBeInTheDocument()
  })

  it('always shows the synthetic-data banner', async () => {
    stubApi((url) => (url.includes('/api/accounts') ? accountPage : undefined))

    renderAt('/', <PortfolioPage />, '/')

    expect(
      await screen.findByText(/Every account, ticket, note, and event is/),
    ).toBeInTheDocument()
  })

  it('says plainly when the portfolio cannot be loaded', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ code: 'INTERNAL_ERROR', message: 'database is down' }),
        {
          status: 500,
        },
      ),
    )

    renderAt('/', <PortfolioPage />, '/')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'database is down',
    )
  })

  it('runs a scan and reports its bounds beside its findings', async () => {
    stubApi((url) => {
      if (url.includes('/api/portfolio-scans')) return scan
      if (url.includes('/api/accounts')) return accountPage
      return undefined
    })

    renderAt('/', <PortfolioPage />, '/')
    fireEvent.click(
      await screen.findByRole('button', { name: 'Run portfolio scan' }),
    )

    const panel = await screen.findByLabelText('Portfolio scan result')
    expect(
      within(panel).getByText('Portfolio scan SCAN-test'),
    ).toBeInTheDocument()
    // The exit-gate numbers are on the page, not only in a log.
    expect(within(panel).getByText('0 / 200')).toBeInTheDocument()
    expect(within(panel).getByText('2 / 4')).toBeInTheDocument()
  })
})

describe('AccountPage', () => {
  it('shows the profile, the cutoff, and the indicator strip', async () => {
    stubApi((url) =>
      url.includes('/api/accounts/ACC-1042') ? accountDetail : undefined,
    )

    renderAt('/accounts/ACC-1042', <AccountPage />, '/accounts/:accountId')

    expect(
      await screen.findByRole('heading', { name: 'Northwind Freight' }),
    ).toBeInTheDocument()
    expect(screen.getByText('2026-08-01')).toBeInTheDocument()
    expect(screen.getByText('612')).toBeInTheDocument()
    expect(screen.getByText('Active users, last week')).toBeInTheDocument()
  })

  it('draws the trajectory with its cutoff marker', async () => {
    stubApi((url) =>
      url.includes('/api/accounts/ACC-1042') ? accountDetail : undefined,
    )

    renderAt('/accounts/ACC-1042', <AccountPage />, '/accounts/:accountId')

    const chart = await screen.findByRole('img', {
      name: /Weekly active users/,
    })
    expect(chart).toHaveAccessibleName(
      /ends at the effective cutoff 2026-08-01/,
    )
  })

  it('shows prior assessments as history, not as a current label', async () => {
    stubApi((url) =>
      url.includes('/api/accounts/ACC-1042') ? accountDetail : undefined,
    )

    renderAt('/accounts/ACC-1042', <AccountPage />, '/accounts/:accountId')

    const history = (
      await screen.findByRole('heading', { name: 'Previous assessments' })
    ).parentElement as HTMLElement
    expect(within(history).getByText('Renewed')).toBeInTheDocument()
    expect(within(history).getByText(/confidence 0.69/)).toBeInTheDocument()
  })

  it('reports an unknown account with the code the API returned', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'ACCOUNT_NOT_FOUND',
          message: 'There is no account ACC-9999 in this portfolio.',
        }),
        { status: 404 },
      ),
    )

    renderAt('/accounts/ACC-9999', <AccountPage />, '/accounts/:accountId')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('ACCOUNT_NOT_FOUND')
    expect(alert).toHaveTextContent('There is no account ACC-9999')
  })

  it('renders no latent field anywhere on the page', async () => {
    stubApi((url) =>
      url.includes('/api/accounts/ACC-1042') ? accountDetail : undefined,
    )

    const { container } = renderAt(
      '/accounts/ACC-1042',
      <AccountPage />,
      '/accounts/:accountId',
    )
    await screen.findByRole('heading', { name: 'Northwind Freight' })

    const markup = container.innerHTML.toLowerCase()
    for (const field of LEAKY) expect(markup).not.toContain(field)
  })
})

describe('RunPage', () => {
  it('shows the finished decision when the run has already completed', async () => {
    vi.stubGlobal('EventSource', SilentEventSource)
    stubApi((url) =>
      url.includes('/api/assessments/RUN-test') ? runState : undefined,
    )

    renderAt('/runs/RUN-test', <RunPage />, '/runs/:runId')

    expect(
      await screen.findByRole('heading', { name: 'Assessment result' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Renewed' })).toBeInTheDocument()
    expect(screen.getByText('Run RUN-test')).toBeInTheDocument()
  })

  it('links to the review case a red run opened', async () => {
    vi.stubGlobal('EventSource', SilentEventSource)
    stubApi((url) =>
      url.includes('/api/assessments/RUN-test') ? runState : undefined,
    )

    renderAt('/runs/RUN-test', <RunPage />, '/runs/:runId')

    expect(await screen.findByText('CASE-ACC-1042-0001-01')).toBeInTheDocument()
  })

  it('renders no prompt or hidden reasoning key', async () => {
    vi.stubGlobal('EventSource', SilentEventSource)
    stubApi((url) =>
      url.includes('/api/assessments/RUN-test') ? runState : undefined,
    )

    const { container } = renderAt(
      '/runs/RUN-test',
      <RunPage />,
      '/runs/:runId',
    )
    await screen.findByRole('heading', { name: 'Assessment result' })

    const markup = container.innerHTML.toLowerCase()
    for (const key of HIDDEN) expect(markup).not.toContain(key)
    for (const field of LEAKY) expect(markup).not.toContain(field)
  })

  it('says a run is no longer tracked rather than spinning forever', async () => {
    vi.stubGlobal('EventSource', SilentEventSource)
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'ACCOUNT_NOT_FOUND',
          message: 'No run RUN-gone is being tracked.',
        }),
        { status: 404 },
      ),
    )

    renderAt('/runs/RUN-gone', <RunPage />, '/runs/:runId')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No run RUN-gone is being tracked.',
    )
  })
})

describe('ReviewPage', () => {
  it('keeps the order the server sent', async () => {
    // The server orders by route, ACV, renewal proximity, then age (plan
    // section 20.5). The page used to re-sort by route and age, which would
    // silently discard the two commercial keys, so this asserts the queue is
    // rendered exactly as delivered -- including an order a client-side sort
    // by route would have changed.
    stubApi((url) => {
      if (url.includes('/api/review-cases?')) {
        return [
          { ...reviewCase, case_id: 'CASE-amber', route: 'amber' },
          reviewCase,
        ]
      }
      return undefined
    })

    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    )

    const items = await screen.findAllByRole('button', { pressed: false })
    expect(items[0]).toHaveTextContent('amber')
    expect(items[1]).toHaveTextContent('red')
  })

  it('shows the contract value and renewal the queue is ordered by', async () => {
    stubApi((url) => {
      if (url.includes('/api/review-cases?')) return [reviewCase]
      return undefined
    })

    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    )

    const items = await screen.findAllByRole('button', { pressed: false })
    expect(items[0]).toHaveTextContent('$412,000 · renews in 121d')
  })

  it('says nothing about terms for a case whose account is gone', async () => {
    stubApi((url) => {
      if (url.includes('/api/review-cases?')) {
        return [
          {
            ...reviewCase,
            acv_usd: null,
            renewal_date: null,
            days_to_renewal: null,
          },
        ]
      }
      return undefined
    })

    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    )

    const items = await screen.findAllByRole('button', { pressed: false })
    expect(items[0]).not.toHaveTextContent('renews in')
    expect(items[0]).toHaveTextContent('ACC-1042')
  })

  it('marks an overdue renewal as overdue rather than negative', async () => {
    stubApi((url) => {
      if (url.includes('/api/review-cases?')) {
        return [{ ...reviewCase, days_to_renewal: -9 }]
      }
      return undefined
    })

    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    )

    const items = await screen.findAllByRole('button', { pressed: false })
    expect(items[0]).toHaveTextContent('renewal 9d overdue')
  })

  it('shows the decision card for the selected case', async () => {
    stubApi((url) => {
      if (url.includes('/api/review-cases?')) return [reviewCase]
      if (url.includes(`/api/review-cases/${reviewCase.case_id}`))
        return reviewCard
      return undefined
    })

    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByText('ACC-1042'))

    expect(
      await screen.findByRole('heading', { name: 'Renewed' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/What is the renewal outlook/)).toBeInTheDocument()
  })

  it('refuses to submit an override until it carries a reason code and a note', async () => {
    stubApi((url) => {
      if (url.includes('/api/review-cases?')) return [reviewCase]
      if (url.includes(`/api/review-cases/${reviewCase.case_id}`))
        return reviewCard
      return undefined
    })

    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    )
    fireEvent.click(await screen.findByText('ACC-1042'))
    fireEvent.click(await screen.findByLabelText('override'))

    const submit = screen.getByRole('button', { name: 'Record decision' })
    expect(submit).toBeDisabled()
    expect(
      screen.getByText(/An override needs a specific reason code and a note/),
    ).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/Note/), {
      target: { value: 'The sponsor was rehired last week.' },
    })
    fireEvent.change(screen.getByLabelText(/Reason code/), {
      target: { value: 'known_context_missing' },
    })

    expect(
      screen.getByRole('button', { name: 'Record decision' }),
    ).toBeEnabled()
  })

  it('reports the regression record an override created', async () => {
    stubApi((url, init) => {
      if (init?.method === 'POST') {
        return {
          case: { ...reviewCase, status: 'resolved', action: 'override' },
          regression: {
            regression_id: 'REG-00001',
            case_id: reviewCase.case_id,
            assessment_id: reviewCase.assessment_id,
            account_id: 'ACC-1042',
            created_at: '2026-09-01T11:00:00Z',
            origin: 'reviewer_override',
            cutoff: '2026-08-01',
            question: 'What is the renewal outlook?',
            system_outcome: 'Renewed',
            reviewer_outcome: 'Churned',
            reason_code: 'known_context_missing',
            note: 'The sponsor was rehired.',
            confidence: 0.69,
            route: 'red',
          },
        }
      }
      if (url.includes('/api/review-cases?')) return [reviewCase]
      if (url.includes(`/api/review-cases/${reviewCase.case_id}`))
        return reviewCard
      return undefined
    })

    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    )
    fireEvent.click(await screen.findByText('ACC-1042'))
    fireEvent.click(await screen.findByLabelText('approve'))
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent('REG-00001')
    expect(status).toHaveTextContent('reviewer override')
    expect(status).toHaveTextContent(
      'system said Renewed, reviewer said Churned',
    )
  })

  it('says the queue is empty rather than showing nothing at all', async () => {
    stubApi((url) => (url.includes('/api/review-cases?') ? [] : undefined))

    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    )

    expect(
      await screen.findByText('Nothing is waiting for review.'),
    ).toBeInTheDocument()
  })
})

describe('EvaluationPage', () => {
  it('shows published metrics and names the artifact they came from', async () => {
    stubApi((url) => {
      if (url.includes('/api/evaluations/guardrails')) {
        return {
          eval_id: 'guardrails',
          status: 'published',
          command: 'make evaluate-guardrails',
          artifact: 'artifacts/safety/guardrail_eval.json',
          metrics: { hard_false_pass_rate: 0, false_block_rate: 0, cases: 36 },
          detail: '',
        }
      }
      return {
        eval_id: 'other',
        status: 'not_run',
        command: 'make evaluate-tot',
        artifact: 'artifacts/tot/tot_ablation.json',
        metrics: null,
        detail: 'This evaluation has not been run in this checkout.',
      }
    })

    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>,
    )

    // The metric is deliberately in two places: the headline row and the
    // collapsed full listing. Both are expected, so both are counted.
    expect(await screen.findAllByText('hard false pass rate')).toHaveLength(2)
    expect(
      screen.getByText('Every metric in artifacts/safety/guardrail_eval.json'),
    ).toBeInTheDocument()
  })

  it('renders the correctness, calibration, and routing tables, and switches split', async () => {
    const summary = {
      headline_split: 'test',
      macro_f1: 0.749,
      splits: {
        test: {
          directory: 'abc123-20260902T000322+0000',
          commit: 'abc123def456',
          per_class: {
            Churned: {
              precision: 0.8571,
              recall: 0.6667,
              f1: 0.75,
              support: 9,
            },
          },
          confusion_matrix: {
            classes: ['Churned', 'Renewed'],
            rows: [
              [6, 3],
              [0, 8],
            ],
          },
          routing_quality: {
            green: { count: 0, errors: 0, error_rate: 0, auto_released: true },
            red: {
              count: 16,
              errors: 4,
              error_rate: 0.25,
              auto_released: false,
            },
          },
          release_targets: [
            { metric: 'Macro F1', target: 0.7, measured: 0.749, met: true },
            {
              metric: 'Expected calibration error',
              target: 0.1,
              measured: 0.1712,
              met: false,
            },
          ],
        },
        development: {
          directory: 'abc123-20260902T005438+0000',
          commit: 'abc123def456',
          per_class: {
            Contracted: {
              precision: 0.7,
              recall: 0.5833,
              f1: 0.6364,
              support: 12,
            },
          },
          release_targets: [],
        },
      },
    }
    stubApi((url) =>
      url.includes('/api/evaluations/system')
        ? {
            eval_id: 'system',
            status: 'published',
            command: 'make evaluate-system',
            artifact: 'artifacts/evaluation/summary.json',
            metrics: summary,
            detail: '',
          }
        : {
            eval_id: 'other',
            status: 'not_run',
            command: 'make evaluate-tot',
            artifact: 'artifacts/tot/tot_ablation.json',
            metrics: null,
            detail: 'This evaluation has not been run in this checkout.',
          },
    )

    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>,
    )

    // A target that was missed must read as missed, not as a number the eye
    // slides over. This is the one release target the system does not meet.
    expect(await screen.findByText('NOT MET')).toBeInTheDocument()

    // A class name appears in the per-class table and again down the confusion
    // matrix, so each assertion is scoped to the table it means.
    const perClass = screen.getByRole('table', { name: 'Per class' })
    expect(within(perClass).getByText('0.8571')).toBeInTheDocument()

    const matrix = screen.getByRole('table', {
      name: 'Confusion matrix — rows are truth, columns prediction',
    })
    expect(within(matrix).getByText('6')).toBeInTheDocument()

    const bands = screen.getByRole('table', {
      name: 'Error rate inside each review band — what a reviewer is promised',
    })
    expect(within(bands).getByText('red')).toBeInTheDocument()

    // The held-out split leads, because it is the released measurement.
    const heldOut = screen.getByRole('button', { name: 'Held out' })
    expect(heldOut).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(screen.getByRole('button', { name: 'Development' }))
    const development = await screen.findByRole('table', { name: 'Per class' })
    expect(within(development).getByText('Contracted')).toBeInTheDocument()
    // This split publishes no release targets in the stub, so the missed-target
    // row must be gone rather than left over from the split before it.
    expect(screen.queryByText('NOT MET')).not.toBeInTheDocument()
  })

  it('says which evaluations have not been run, with the command that produces them', async () => {
    stubApi(() => ({
      eval_id: 'tot',
      status: 'not_run',
      command: 'make evaluate-tot',
      artifact: 'artifacts/tot/tot_ablation.json',
      metrics: null,
      detail: 'This evaluation has not been run in this checkout.',
    }))

    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>,
    )

    const unrun = await screen.findAllByText('Not run in this checkout.')
    expect(unrun.length).toBeGreaterThan(0)
    expect(screen.getAllByText('make evaluate-tot').length).toBeGreaterThan(0)
  })
})

describe('App shell', () => {
  it('offers a skip link and names a missing subsystem in its health pill', async () => {
    stubApi((url) => (url.includes('/api/health') ? health : accountPage))

    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(screen.getByText('Skip to main content')).toHaveAttribute(
      'href',
      '#main',
    )
    // The fixture is healthy but has no provider. That is `ok` -- runs still
    // complete, deterministically -- and the pill must still name what is
    // missing rather than claiming everything is ready.
    await waitFor(() =>
      expect(screen.getByText(/Ready · no provider/)).toBeInTheDocument(),
    )
  })

  it('reports an unreachable API rather than an empty header', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(
      new Error('connection refused'),
    )

    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByText('API unavailable')).toBeInTheDocument()
  })

  it('shows a not-found page for an unknown route', () => {
    stubApi(() => health)

    render(
      <MemoryRouter initialEntries={['/nowhere']}>
        <App />
      </MemoryRouter>,
    )

    expect(
      screen.getByRole('heading', { name: 'Page not found' }),
    ).toBeInTheDocument()
  })
})

describe('decision plumbing', () => {
  it('keeps the forecast fixture free of any field the API does not send', () => {
    // A fixture that drifts from the contract makes every test above lie.
    expect(Object.keys(forecast)).toEqual(
      expect.arrayContaining([
        'outcome',
        'distribution',
        'confidence_breakdown',
        'route',
      ]),
    )
    expect(forecast).not.toHaveProperty('prompt')
    expect(forecast).not.toHaveProperty('health_band')
  })
})

describe('page branches that only appear when something goes wrong', () => {
  it('narrows the portfolio when a filter is chosen', async () => {
    const urls: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      urls.push(urlOf(input))
      return Promise.resolve(
        new Response(JSON.stringify(accountPage), { status: 200 }),
      )
    })

    renderAt('/', <PortfolioPage />, '/')
    await screen.findByText('Northwind Freight')

    fireEvent.change(screen.getByLabelText('Renewal window'), {
      target: { value: '30' },
    })

    await waitFor(() =>
      expect(urls.some((url) => url.includes('renews_within_days=30'))).toBe(
        true,
      ),
    )
  })

  it('says the filters match nothing rather than showing a bare table', async () => {
    stubApi(() => ({ items: [], total: 0, offset: 0, limit: 50 }))

    renderAt('/', <PortfolioPage />, '/')

    expect(
      await screen.findByText('No account matches these filters.'),
    ).toBeInTheDocument()
  })

  it('reports a refused scan without losing the account list', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = urlOf(input)
      if (url.includes('/api/portfolio-scans')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              code: 'REQUEST_BLOCKED',
              message: 'The public demo does not start portfolio scans.',
            }),
            { status: 422 },
          ),
        )
      }
      return Promise.resolve(
        new Response(JSON.stringify(accountPage), { status: 200 }),
      )
    })

    renderAt('/', <PortfolioPage />, '/')
    fireEvent.click(
      await screen.findByRole('button', { name: 'Run portfolio scan' }),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The public demo does not start portfolio scans.',
    )
    expect(screen.getByText('Northwind Freight')).toBeInTheDocument()
  })

  it('fills the question box from a preset', async () => {
    stubApi((url) =>
      url.includes('/api/accounts/ACC-1042') ? accountDetail : undefined,
    )

    renderAt('/accounts/ACC-1042', <AccountPage />, '/accounts/:accountId')
    await screen.findByRole('heading', { name: 'Northwind Freight' })

    const presets = screen.getAllByRole('button', { name: /…$/ })
    fireEvent.click(presets[2])

    expect(screen.getByLabelText('Question')).toHaveValue(
      'What is the relationship risk on this account?',
    )
  })

  it('surfaces a blocked request rather than starting a run', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => {
      if (init?.method === 'POST') {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              code: 'REQUEST_BLOCKED',
              message: 'The request could not be accepted.',
            }),
            { status: 422 },
          ),
        )
      }
      return Promise.resolve(
        new Response(JSON.stringify(accountDetail), { status: 200 }),
      )
    })

    renderAt('/accounts/ACC-1042', <AccountPage />, '/accounts/:accountId')
    fireEvent.click(
      await screen.findByRole('button', { name: 'Assess this account' }),
    )

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('REQUEST_BLOCKED')
  })

  it('shows a refusal instead of a decision card when intake blocked the run', async () => {
    vi.stubGlobal('EventSource', SilentEventSource)
    stubApi(() => ({
      ...runState,
      route: 'blocked',
      decision: null,
      review_case_id: null,
      blocked: {
        account_id: 'ACC-1042',
        message:
          'This system does not evaluate the performance of named employees.',
        rule_ids: ['INTAKE-HR'],
        reason_codes: ['refuse_hr_judgment'],
        route: 'blocked',
        reason_code: 'REQUEST_BLOCKED',
      },
    }))

    renderAt('/runs/RUN-blocked', <RunPage />, '/runs/:runId')

    expect(
      await screen.findByRole('heading', { name: 'Request refused' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/does not evaluate the performance/),
    ).toBeInTheDocument()
    expect(screen.getByText(/refuse_hr_judgment/)).toBeInTheDocument()
  })

  it('renders an abstention from a finished run without inventing a label', async () => {
    vi.stubGlobal('EventSource', SilentEventSource)
    stubApi(() => ({ ...runState, decision: abstention, route: 'red' }))

    renderAt('/runs/RUN-abstained', <RunPage />, '/runs/:runId')

    expect(
      await screen.findByRole('heading', { name: 'No categorical forecast' }),
    ).toBeInTheDocument()
  })

  it('reports a failed run with the reason it failed', async () => {
    vi.stubGlobal('EventSource', SilentEventSource)
    stubApi(() => ({
      ...runState,
      status: 'failed',
      decision: null,
      error: 'RuntimeError: the index is unavailable',
    }))

    renderAt('/runs/RUN-failed', <RunPage />, '/runs/:runId')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'the index is unavailable',
    )
  })

  it('records a data request and reports the regression it filed', async () => {
    stubApi((url, init) => {
      if (init?.method === 'POST') {
        const body = JSON.parse(init.body as string) as {
          requested_data?: unknown[]
        }
        expect(body.requested_data).toHaveLength(1)
        return {
          case: { ...reviewCase, status: 'resolved', action: 'request_data' },
          regression: null,
        }
      }
      if (url.includes('/api/review-cases?')) return [reviewCase]
      if (url.includes(`/api/review-cases/${reviewCase.case_id}`))
        return reviewCard
      return undefined
    })

    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    )
    fireEvent.click(await screen.findByText('ACC-1042'))
    fireEvent.click(await screen.findByLabelText('request data'))
    fireEvent.change(screen.getByLabelText(/Note/), {
      target: { value: 'The retrieval index was missing.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }))

    expect(await screen.findByRole('status')).toHaveTextContent(
      'resolved as request_data',
    )
  })

  it('reports a rejected reviewer decision without clearing the queue', async () => {
    stubApi((url, init) => {
      if (init?.method === 'POST') return undefined
      if (url.includes('/api/review-cases?')) return [reviewCase]
      if (url.includes(`/api/review-cases/${reviewCase.case_id}`))
        return reviewCard
      return undefined
    })

    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    )
    fireEvent.click(await screen.findByText('ACC-1042'))
    // The form appears only once the card has loaded.
    fireEvent.click(
      await screen.findByRole('button', { name: 'Record decision' }),
    )

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    // The queue is still on screen: a rejected decision is not a lost session.
    expect(screen.getByText('ACC-1042')).toBeInTheDocument()
  })

  it('says an evaluation could not be read at all', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('offline'))

    render(
      <MemoryRouter>
        <EvaluationPage />
      </MemoryRouter>,
    )

    // One per evaluation the page lists: the system evaluation, the guardrail
    // suite, the Tree-of-Thought ablation, the guardrail-stack ablation, and
    // the retrieval benchmark.
    const notes = await screen.findAllByText(
      'This evaluation could not be read.',
    )
    expect(notes).toHaveLength(5)
  })
})

describe('RunPage when the event stream is unavailable', () => {
  /** An EventSource that fails immediately, as a proxy that blocks SSE would. */
  class FailingEventSource {
    onerror: (() => void) | null = null
    constructor(readonly url: string) {
      queueMicrotask(() => this.onerror?.())
    }
    addEventListener() {}
    close() {}
  }

  it('falls back to polling rather than spinning forever', async () => {
    vi.stubGlobal('EventSource', FailingEventSource)
    let calls = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      calls += 1
      return Promise.resolve(
        new Response(
          JSON.stringify(
            calls < 2
              ? { ...runState, status: 'running', decision: null }
              : runState,
          ),
          { status: 200 },
        ),
      )
    })

    renderAt('/runs/RUN-poll', <RunPage />, '/runs/:runId')

    expect(
      await screen.findByRole(
        'heading',
        { name: 'Renewed' },
        { timeout: 4000 },
      ),
    ).toBeInTheDocument()
  }, 8000)
})

describe('PortfolioPage scan findings', () => {
  it('lists expansion candidates separately from accounts at risk', async () => {
    stubApi((url) => {
      if (url.includes('/api/portfolio-scans')) {
        return {
          ...scan,
          summary: {
            ...scan.summary,
            risk_accounts: [],
            expansion_candidates: ['ACC-1096'],
          },
        }
      }
      if (url.includes('/api/accounts')) return accountPage
      return undefined
    })

    renderAt('/', <PortfolioPage />, '/')
    fireEvent.click(
      await screen.findByRole('button', { name: 'Run portfolio scan' }),
    )

    const panel = await screen.findByLabelText('Portfolio scan result')
    expect(within(panel).getByText('Expansion candidates:')).toBeInTheDocument()
    expect(within(panel).queryByText('At risk:')).not.toBeInTheDocument()
  })
})

describe('evaluation metric formatting', () => {
  it('renders each shape an artifact actually contains', () => {
    expect(formatMetric(36)).toBe('36')
    expect(formatMetric(0.5833)).toBe('0.5833')
    expect(formatMetric(0)).toBe('0')
    expect(formatMetric([])).toBe('none')
    expect(formatMetric(['GE-017', 'GE-018'])).toBe('GE-017, GE-018')
    expect(formatMetric(null)).toBe('—')
    expect(formatMetric(undefined)).toBe('—')
    expect(formatMetric('development')).toBe('development')
    expect(formatMetric(true)).toBe('true')
    expect(formatMetric({ red: 3 })).toBe('{"red":3}')
  })
})

describe('AccountPage indicators', () => {
  it('tones each indicator by what it means, not by its sign alone', async () => {
    stubApi(() => ({
      ...accountDetail,
      indicators: {
        ...accountDetail.indicators,
        adoption_trend_13w: 12.5,
        escalations_26w: 0,
        average_ticket_sentiment: null,
        sponsor_status: 'stable',
        onboarding_completed: false,
      },
    }))

    const { container } = renderAt(
      '/accounts/ACC-1042',
      <AccountPage />,
      '/accounts/:accountId',
    )
    await screen.findByRole('heading', { name: 'Northwind Freight' })

    expect(screen.getByText('incomplete')).toBeInTheDocument()
    // A missing sentiment is neutral, not bad: there is nothing to judge.
    expect(screen.getByText('—')).toBeInTheDocument()
    expect(
      container.querySelectorAll('.indicator--positive').length,
    ).toBeGreaterThan(0)
  })

  it('marks a high-value account with the reason it is high value', async () => {
    stubApi(() => accountDetail)

    renderAt('/accounts/ACC-1042', <AccountPage />, '/accounts/:accountId')

    expect(
      await screen.findByText(/high value · segment Strategic/),
    ).toBeInTheDocument()
  })
})

describe('the health pill before the first response', () => {
  it('says it is checking rather than claiming a state it does not know', () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      () => new Promise<Response>(() => {}),
    )

    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(screen.getByText('Checking…')).toBeInTheDocument()
  })

  it('reports every subsystem as ready when nothing is missing', async () => {
    stubApi((url) =>
      url.includes('/api/health')
        ? {
            ...health,
            subsystems: {
              ...health.subsystems,
              provider: {
                status: 'ready',
                detail: 'provider openai_compatible',
              },
            },
          }
        : accountPage,
    )

    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/All systems ready/)).toBeInTheDocument()
  })

  it('marks demo mode in the pill, because it changes what a run may ask', async () => {
    stubApi((url) =>
      url.includes('/api/health')
        ? { ...health, demo_mode: true }
        : accountPage,
    )

    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/demo mode/)).toBeInTheDocument()
  })
})

describe('DemoPage', () => {
  const cached = {
    kind: 'conflict',
    label: 'An account whose evidence disagrees with itself.',
    account_id: 'ACC-1042',
    question: 'What is the renewal outlook for this account?',
    route: 'red',
    recorded_at: '2026-09-01T12:00:00Z',
    commit: 'a4563f45de05d6a75016cf9eefcd4316b387485e',
    is_cached: true,
    cached_note:
      'This is a recorded run, not a live one. It was produced by the real graph at commit a4563f45de05 on 2026-09-01.',
    state: runState,
  }

  it('says it is a recording before it shows anything else', async () => {
    // Section 24.3 forbids showing a cached run as though it were live, so the
    // label is the first thing on the page rather than a badge in a corner.
    // The synthetic-data banner is also a note, so this one is found by name.
    stubApi(() => cached)

    renderAt('/demo/conflict', <DemoPage />, '/demo/:kind')

    const banner = await screen.findByRole('note', {
      name: 'Recorded run notice',
    })
    expect(banner).toHaveTextContent('This is a recorded run, not a live one.')
    expect(banner).toHaveTextContent('a4563f45de05')
  })

  it('renders the recorded decision through the same card a live run uses', async () => {
    stubApi(() => cached)

    renderAt('/demo/conflict', <DemoPage />, '/demo/:kind')

    expect(
      await screen.findByRole('heading', { name: 'Renewed' }),
    ).toBeInTheDocument()
    // The account appears in the header and again on the card, by design.
    expect(screen.getAllByText(/ACC-1042/).length).toBeGreaterThan(0)
  })

  it('shows what the recorded run did', async () => {
    stubApi(() => cached)

    renderAt('/demo/conflict', <DemoPage />, '/demo/:kind')

    expect(await screen.findByText('Request received')).toBeInTheDocument()
  })

  it('renders a recorded refusal without inventing a decision', async () => {
    stubApi(() => ({
      ...cached,
      kind: 'guardrail_refusal',
      route: 'blocked',
      state: {
        ...runState,
        route: 'blocked',
        decision: null,
        blocked: {
          account_id: 'ACC-1042',
          message:
            'This system does not evaluate the performance of named employees.',
          rule_ids: ['INTAKE-HR'],
          reason_codes: ['refuse_hr_judgment'],
          route: 'blocked',
          reason_code: 'REQUEST_BLOCKED',
        },
      },
    }))

    renderAt('/demo/guardrail_refusal', <DemoPage />, '/demo/:kind')

    expect(
      await screen.findByRole('heading', { name: 'Request refused' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Renewed' }),
    ).not.toBeInTheDocument()
  })

  it('says so when this deployment has no run of that kind', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'ACCOUNT_NOT_FOUND',
          message:
            "No curated run of kind 'nope' is cached in this deployment.",
        }),
        { status: 404 },
      ),
    )

    renderAt('/demo/nope', <DemoPage />, '/demo/:kind')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No curated run of kind',
    )
  })
})

describe('the curated panel on the landing page', () => {
  it('offers every cached run, and nothing when there is no cache', async () => {
    stubApi((url) => {
      if (url.includes('/api/demo-runs')) {
        return [
          {
            kind: 'fast_path',
            label: 'A straightforward account.',
            account_id: 'ACC-1000',
            question: 'q',
            route: 'amber',
            recorded_at: '2026-09-01T12:00:00Z',
            commit: 'abc123',
            is_cached: true,
          },
        ]
      }
      if (url.includes('/api/accounts')) return accountPage
      return undefined
    })

    renderAt('/', <PortfolioPage />, '/')

    expect(
      await screen.findByRole('heading', {
        name: 'See it work, without spending anything',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('fast path')).toBeInTheDocument()
  })

  it('does not appear when this deployment has no cache', async () => {
    stubApi((url) => {
      if (url.includes('/api/demo-runs')) return []
      if (url.includes('/api/accounts')) return accountPage
      return undefined
    })

    renderAt('/', <PortfolioPage />, '/')
    await screen.findByText('Northwind Freight')

    expect(
      screen.queryByRole('heading', {
        name: 'See it work, without spending anything',
      }),
    ).not.toBeInTheDocument()
  })
})
