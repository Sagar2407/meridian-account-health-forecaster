/**
 * The typed client for every endpoint the browser uses (plan section 19).
 *
 * One module, so the shapes the pages render are declared once and a change to
 * the API surfaces as a type error rather than as an undefined at runtime.
 *
 * Two rules are visible in the types themselves. There is no field here for a
 * prompt, a raw model reply, or a latent label: the server never sends them and
 * the browser has no name to render them under. And every failure arrives as
 * `ApiError`, carrying the stable code from section 19.3, so a page can decide
 * what to show from the code rather than by matching on a message.
 */

export const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/** The stable error codes of plan section 19.3. */
export type ErrorCode =
  | 'ACCOUNT_NOT_FOUND'
  | 'REQUEST_BLOCKED'
  | 'CRITICAL_DATA_GAP'
  | 'MODEL_UNAVAILABLE'
  | 'INDEX_VERSION_MISMATCH'
  | 'RETRIEVAL_EXHAUSTED'
  | 'UNRESOLVED_CONFLICT'
  | 'VERIFICATION_FAILED'
  | 'INTERNAL_ERROR'

export type Route = 'green' | 'amber' | 'red' | 'blocked'

/** A failure the server described, rather than a bare network error. */
export class ApiError extends Error {
  readonly code: ErrorCode
  readonly status: number
  readonly detail?: Record<string, unknown>

  constructor(
    code: ErrorCode,
    message: string,
    status: number,
    detail?: Record<string, unknown>,
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.detail = detail
  }
}

export type SubsystemHealth = { status: string; detail: string }

export type HealthResponse = {
  status: 'ok' | 'degraded'
  service: string
  version: string
  environment: string
  data_mode: 'synthetic'
  demo_mode: boolean
  subsystems: Record<string, SubsystemHealth>
}

export type AccountSummary = {
  account_id: string
  account_name: string
  segment: string
  industry: string
  region: string
  acv_usd: number
  renewal_date: string
  days_to_renewal: number
  sponsor_status: string
  onboarding_completed: boolean
  high_value: boolean
}

export type AccountPage = {
  items: AccountSummary[]
  total: number
  offset: number
  limit: number
}

export type UsagePoint = {
  week_start: string
  active_users: number
  sessions: number
  feature_events: number
  advanced_feature_adoption_pct: number
}

export type RecentItem = {
  kind: 'ticket' | 'note' | 'event'
  item_date: string
  label: string
  detail: string
  signal: 'positive' | 'negative' | 'neutral'
}

export type AccountIndicators = {
  weeks_observed: number
  active_users_last_week: number
  adoption_trend_13w: number
  open_tickets: number
  escalations_26w: number
  average_ticket_sentiment: number | null
  external_events_26w: number
  sponsor_status: string
  onboarding_completed: boolean
}

export type PriorAssessment = {
  assessment_id: string
  created_at: string
  cutoff: string
  predicted_outcome: string
  confidence: number
  route: string
  summary: string
}

export type AccountProfile = {
  account_id: string
  account_name: string
  segment: string
  industry: string
  region: string
  country: string
  employees: number
  licensed_seats: number
  acv_usd: number
  contract_term_months: number
  contract_start_date: string
  renewal_date: string
  forecast_as_of_date: string
  products_owned: string[]
  num_products: number
  primary_product: string
  csm_name: string
  exec_sponsor_name: string
  sponsor_status: string
  onboarding_completed: boolean
}

export type AccountDetail = {
  profile: AccountProfile
  effective_cutoff: string
  high_value: boolean
  high_value_reason: string
  indicators: AccountIndicators
  usage: UsagePoint[]
  recent: RecentItem[]
  prior_assessments: PriorAssessment[]
}

export type Citation = {
  doc_id: string
  parent_id: string
  source_type: string
  subtype: string
  account_id: string | null
  doc_date: string | null
  excerpt: string
  retrieval_score: number
  signal: 'positive' | 'negative' | 'neutral'
  sub_goal: string | null
}

export type Driver = {
  name: string
  direction: 'positive' | 'negative'
  contribution: number
  value: number
  description?: string
}

export type ConfidenceBreakdown = {
  calibrated_probability: number
  coverage_score: number
  agreement_score: number
  raw_confidence: number
  applied_caps: string[]
  confidence: number
}

export type MetricObservation = {
  name: string
  value: number
  window: string
  source: string
  coverage: number
  calculation_version: string
}

export type RequestedData = { source: string; detail: string; window: string }

/** A released forecast. `is_abstention` is absent, so the shape decides. */
export type ForecastDecision = {
  account_id: string
  cutoff: string
  outcome: string
  distribution: Record<string, number>
  confidence: number
  confidence_breakdown: ConfidenceBreakdown
  rationale: string
  drivers: Driver[]
  citations: Citation[]
  counterevidence: Citation[]
  cited_doc_ids: string[]
  limitations: string[]
  recommended_action: string
  route: Route
  route_reason: string
  narrative_source: 'model' | 'deterministic'
  selected_by: 'linear' | 'tree_of_thought'
  model_name: string
}

/** A degraded result. There is deliberately no outcome field to render. */
export type InsufficientEvidenceDecision = {
  account_id: string
  cutoff: string
  verified_metrics: MetricObservation[]
  gaps: string[]
  requested_data: RequestedData[]
  citations: Citation[]
  limitations: string[]
  recommended_action: string
  route: Route
  route_reason: string
  reason_code: ErrorCode
}

export type Decision = ForecastDecision | InsufficientEvidenceDecision

/** Narrow a decision by the field an abstention cannot have. */
export function isForecast(decision: Decision): decision is ForecastDecision {
  return 'outcome' in decision
}

/**
 * Narrow a stored review card's decision, which may be an empty object.
 *
 * A case recorded before decision cards were stored has `{}` where the decision
 * belongs. That is a real state in an existing database, not a defect, so the
 * page checks for it rather than rendering a card with no fields.
 */
export function hasDecision(
  value: Decision | Record<string, never>,
): value is Decision {
  return 'account_id' in value && 'cutoff' in value
}

export type TraceEvent = {
  run_id: string
  thread_id: string
  sequence: number
  timestamp: string
  node: string
  event: string
  payload: Record<string, unknown>
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
}

export type GuardrailDecision = {
  stage: string
  outcome: string
  rule_ids: string[]
  reason_codes: string[]
  message: string
}

export type BlockedDecision = {
  account_id: string
  message: string
  rule_ids: string[]
  reason_codes: string[]
  route: 'blocked'
  reason_code: ErrorCode
}

export type AssessmentState = {
  run_id: string
  account_id: string
  question: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  started_at: string
  finished_at: string | null
  events_emitted: number
  last_event: string | null
  route: Route | null
  error: string | null
  blocked: BlockedDecision | null
  decision: Decision | null
  guardrails: GuardrailDecision[]
  trace: TraceEvent[]
  assessment_id: string | null
  review_case_id: string | null
  total_tokens: number
  model_calls: number
}

export type StartAssessmentResponse = {
  run_id: string
  status: string
  account_id: string
  question: string
  events_url: string
  result_url: string
}

export type ScanRun = {
  account_id: string
  status: string
  route: string | null
  outcome: string | null
  confidence: number | null
  abstained: boolean
  review_case_id: string | null
  assessment_id: string | null
  model_calls: number
  tokens: number
  latency_ms: number
  error: string | null
}

export type ScanSummary = {
  scanned: number
  completed: number
  failed: number
  blocked: number
  auto_released: number
  queued_for_review: number
  abstentions: number
  risk_accounts: string[]
  expansion_candidates: string[]
  review_load: Record<string, number>
  total_model_calls: number
  total_tokens: number
  budget_exhausted: boolean
  concurrency_observed: number
}

export type ScanView = {
  scan_id: string
  status: string
  started_at: string
  finished_at: string | null
  requested_accounts: number
  concurrency_limit: number
  model_call_budget: number
  summary: ScanSummary
  runs: ScanRun[]
  skipped: string[]
  error: string | null
}

export type ReviewCase = {
  case_id: string
  assessment_id: string
  account_id: string
  created_at: string
  reason: string
  status: string
  route: string
  reason_codes: string[]
  resolved_at: string | null
  reviewer: string | null
  action: string | null
  reason_code: string | null
  note: string | null
  corrected_outcome: string | null
}

export type ReviewCard = {
  case: ReviewCase
  question: string
  cutoff: string
  kind: string
  proposed_outcome: string
  confidence: number
  decision: Decision | Record<string, never>
}

export type ReviewAction = 'approve' | 'override' | 'request_data' | 'escalate'

export type ReviewReasonCode =
  | 'agrees_with_evidence'
  | 'evidence_contradicts_outcome'
  | 'known_context_missing'
  | 'model_miscalibrated'
  | 'coverage_insufficient'
  | 'policy_requires_human_action'
  | 'other'

export type ReviewDecisionRequest = {
  reviewer: string
  action: ReviewAction
  reason_code: ReviewReasonCode
  note: string
  corrected_outcome?: string | null
  requested_data?: { source: string; detail: string; window: string }[]
}

export type RegressionCase = {
  regression_id: string
  case_id: string | null
  assessment_id: string | null
  account_id: string
  created_at: string
  origin: string
  cutoff: string
  question: string
  system_outcome: string
  reviewer_outcome: string | null
  reason_code: string
  note: string
  confidence: number
  route: string
}

export type EvaluationResult = {
  eval_id: string
  status: 'published' | 'not_run'
  command: string
  artifact: string
  metrics: Record<string, unknown> | null
  detail: string
}

type RequestOptions = {
  signal?: AbortSignal
  method?: 'GET' | 'POST'
  body?: unknown
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { signal, method = 'GET', body } = options
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method,
    signal,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    let code: ErrorCode = 'INTERNAL_ERROR'
    let message = `Request failed with status ${response.status}`
    let detail: Record<string, unknown> | undefined
    try {
      const payload = (await response.json()) as {
        code?: ErrorCode
        message?: string
        detail?: Record<string, unknown>
      }
      if (payload.code) code = payload.code
      if (payload.message) message = payload.message
      detail = payload.detail
    } catch {
      // A non-JSON body is a proxy or a crash. The status is all there is,
      // and inventing a code from it would be worse than the default.
    }
    throw new ApiError(code, message, response.status, detail)
  }

  return (await response.json()) as T
}

export const fetchHealth = (signal?: AbortSignal) =>
  request<HealthResponse>('/api/health', { signal })

export type AccountQuery = {
  segment?: string
  region?: string
  renewsWithinDays?: number
  sort?: 'renewal_date' | 'acv_usd' | 'account_id'
  offset?: number
  limit?: number
}

export function fetchAccounts(
  query: AccountQuery = {},
  signal?: AbortSignal,
): Promise<AccountPage> {
  const params = new URLSearchParams()
  if (query.segment) params.set('segment', query.segment)
  if (query.region) params.set('region', query.region)
  if (query.renewsWithinDays !== undefined)
    params.set('renews_within_days', String(query.renewsWithinDays))
  if (query.sort) params.set('sort', query.sort)
  if (query.offset !== undefined) params.set('offset', String(query.offset))
  if (query.limit !== undefined) params.set('limit', String(query.limit))
  const suffix = params.toString() ? `?${params}` : ''
  return request<AccountPage>(`/api/accounts${suffix}`, { signal })
}

export const fetchAccount = (accountId: string, signal?: AbortSignal) =>
  request<AccountDetail>(`/api/accounts/${encodeURIComponent(accountId)}`, {
    signal,
  })

export const startAssessment = (
  accountId: string,
  question?: string,
  signal?: AbortSignal,
) =>
  request<StartAssessmentResponse>('/api/assessments', {
    method: 'POST',
    signal,
    body: question
      ? { account_id: accountId, question }
      : { account_id: accountId },
  })

export const fetchAssessment = (runId: string, signal?: AbortSignal) =>
  request<AssessmentState>(`/api/assessments/${encodeURIComponent(runId)}`, {
    signal,
  })

export const startScan = (
  body: { account_ids?: string[]; max_accounts?: number; concurrency?: number },
  signal?: AbortSignal,
) => request<ScanView>('/api/portfolio-scans', { method: 'POST', signal, body })

export const fetchScan = (scanId: string, signal?: AbortSignal) =>
  request<ScanView>(`/api/portfolio-scans/${encodeURIComponent(scanId)}`, {
    signal,
  })

export const fetchReviewQueue = (
  status: 'open' | 'resolved' | 'all' = 'open',
  signal?: AbortSignal,
) => request<ReviewCase[]>(`/api/review-cases?status=${status}`, { signal })

export const fetchReviewCard = (caseId: string, signal?: AbortSignal) =>
  request<ReviewCard>(`/api/review-cases/${encodeURIComponent(caseId)}`, {
    signal,
  })

export const submitReviewDecision = (
  caseId: string,
  body: ReviewDecisionRequest,
  signal?: AbortSignal,
) =>
  request<{ case: ReviewCase; regression: RegressionCase | null }>(
    `/api/review-cases/${encodeURIComponent(caseId)}/decision`,
    { method: 'POST', signal, body },
  )

export const fetchRegressions = (signal?: AbortSignal) =>
  request<RegressionCase[]>('/api/review-regressions', { signal })

export const fetchEvaluation = (name: string, signal?: AbortSignal) =>
  request<EvaluationResult>(`/api/evaluations/${encodeURIComponent(name)}`, {
    signal,
  })

/**
 * Subscribe to one run's progress events.
 *
 * `EventSource` rather than a polling loop, because the server already streams
 * and the events are the same `TraceEvent`s the trace is built from. The
 * returned function closes the connection; a caller that forgets leaves a
 * socket open for the life of the page.
 */
export function subscribeToRun(
  runId: string,
  onEvent: (event: TraceEvent) => void,
  onFinished: (state: AssessmentState) => void,
  onError?: () => void,
): () => void {
  const source = new EventSource(
    `${apiBaseUrl}/api/assessments/${encodeURIComponent(runId)}/events`,
  )

  const handleEvent = (message: MessageEvent<string>) => {
    try {
      onEvent(JSON.parse(message.data) as TraceEvent)
    } catch {
      // A frame that will not parse is dropped rather than shown: a progress
      // timeline is a convenience, and a malformed frame must not break it.
    }
  }

  // Every event name the graph emits is a named SSE event, so each is
  // registered rather than relying on the default `message` handler.
  const names = [
    'run_started',
    'request_validated',
    'request_blocked',
    'context_loaded',
    'plan_created',
    'quantitative_completed',
    'retrieval_attempted',
    'retrieval_retried',
    'evidence_screened',
    'evidence_merged',
    'coverage_evaluated',
    'evidence_round_started',
    'conflict_detected',
    'conflict_evaluated',
    'tot_started',
    'tot_completed',
    'tot_pruned',
    'degraded_result',
    'decision_drafted',
    'output_verified',
    'budget_exhausted',
    'decision_routed',
    'review_required',
    'review_resumed',
    'decision_persisted',
    'node_failed',
    'run_completed',
  ]
  for (const name of names) source.addEventListener(name, handleEvent)

  source.addEventListener('run_finished', (message) => {
    try {
      onFinished(
        JSON.parse((message as MessageEvent<string>).data) as AssessmentState,
      )
    } catch {
      onError?.()
    }
    source.close()
  })

  source.onerror = () => {
    source.close()
    onError?.()
  }

  return () => source.close()
}
