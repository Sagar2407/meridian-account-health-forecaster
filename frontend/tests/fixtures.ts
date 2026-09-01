/**
 * Response fixtures shaped exactly like the API's.
 *
 * Hand-written rather than recorded, and deliberately containing the awkward
 * cases: an abstention with no outcome field at all, a citation with a null
 * account (knowledge-base guidance), and a capped confidence. A fixture that
 * only covers the happy path lets a component pass while being unable to
 * render the states that matter.
 */

import type {
  AccountDetail,
  AccountPage,
  AssessmentState,
  Citation,
  ForecastDecision,
  HealthResponse,
  InsufficientEvidenceDecision,
  ReviewCard,
  ReviewCase,
  ScanView,
  TraceEvent,
} from '../src/api'

export const health: HealthResponse = {
  status: 'ok',
  service: 'meridian-api',
  version: '0.1.0',
  environment: 'test',
  data_mode: 'synthetic',
  demo_mode: false,
  subsystems: {
    dataset: { status: 'ready', detail: 'source tables are present' },
    forecaster: {
      status: 'ready',
      detail: 'a calibrated artifact is available',
    },
    retrieval_index: {
      status: 'ready',
      detail: 'a retrieval index is present',
    },
    database: { status: 'ready', detail: 'application memory exists' },
    provider: { status: 'absent', detail: 'no provider configured' },
  },
}

export const accountPage: AccountPage = {
  items: [
    {
      account_id: 'ACC-1042',
      account_name: 'Northwind Freight',
      segment: 'Strategic',
      industry: 'Logistics',
      region: 'NA',
      acv_usd: 1_250_000,
      renewal_date: '2026-11-30',
      days_to_renewal: 62,
      sponsor_status: 'lost',
      onboarding_completed: true,
      high_value: true,
    },
    {
      account_id: 'ACC-1096',
      account_name: 'QuillTelecom Co.',
      segment: 'Mid-Market',
      industry: 'Telecom',
      region: 'EMEA',
      acv_usd: 210_000,
      renewal_date: '2027-02-14',
      days_to_renewal: 138,
      sponsor_status: 'stable',
      onboarding_completed: false,
      high_value: false,
    },
  ],
  total: 2,
  offset: 0,
  limit: 50,
}

export const supportingCitation: Citation = {
  doc_id: 'NOTE-1042-08',
  parent_id: 'NOTE-1042-08',
  source_type: 'csm_notes',
  subtype: 'QBR',
  account_id: 'ACC-1042',
  doc_date: '2026-07-02',
  excerpt:
    'The team confirmed budget for the next term and asked about seat expansion.',
  retrieval_score: 0.81,
  signal: 'favorable',
  sub_goal: 'relationship',
}

export const counterCitation: Citation = {
  doc_id: 'TICKET-1042-31',
  parent_id: 'TICKET-1042-31',
  source_type: 'support_tickets',
  subtype: 'Escalation',
  account_id: 'ACC-1042',
  doc_date: '2026-07-19',
  excerpt:
    'Third escalation this quarter on the reporting module; the sponsor is unhappy.',
  retrieval_score: 0.77,
  signal: 'adverse',
  sub_goal: 'support',
}

export const guidanceCitation: Citation = {
  doc_id: 'KB-014',
  parent_id: 'KB-014',
  source_type: 'knowledge_base',
  subtype: 'playbook',
  account_id: null,
  doc_date: null,
  excerpt: 'When an executive sponsor leaves, multi-thread within two weeks.',
  retrieval_score: 0.64,
  signal: 'neutral',
  sub_goal: 'playbook_guidance',
}

export const forecast: ForecastDecision = {
  account_id: 'ACC-1042',
  cutoff: '2026-08-01',
  outcome: 'Renewed',
  distribution: {
    Renewed: 0.52,
    Churned: 0.24,
    Contracted: 0.16,
    Expanded: 0.08,
  },
  confidence: 0.69,
  confidence_breakdown: {
    calibrated_probability: 0.52,
    coverage_score: 0.88,
    agreement_score: 0.6,
    raw_confidence: 0.586,
    applied_caps: ['persistent_tie'],
    confidence: 0.69,
  },
  rationale:
    'Adoption held steady through the last quarter while support escalations rose. The two signals offset, so the calibrated distribution is close between Renewed and Churned.',
  drivers: [
    {
      feature: 'adoption_level_last_q',
      direction: 'supports',
      contribution: 0.21,
      value: 74.2,
    },
    {
      feature: 'escalation_rate_26w',
      direction: 'opposes',
      contribution: -0.18,
      value: 0.31,
    },
  ],
  citations: [supportingCitation, guidanceCitation],
  counterevidence: [counterCitation],
  cited_doc_ids: ['NOTE-1042-08', 'TICKET-1042-31'],
  limitations: ['The executive sponsor changed during the window.'],
  recommended_action:
    'Multi-thread into the new sponsor before the renewal conversation.',
  route: 'red',
  route_reason: 'the top two outcomes are within 0.28',
  narrative_source: 'deterministic',
  selected_by: 'linear',
  model_name: '',
}

/** No `outcome` key at all: the shape is what prevents a label being shown. */
export const abstention: InsufficientEvidenceDecision = {
  account_id: 'ACC-1096',
  cutoff: '2026-08-01',
  verified_metrics: [
    {
      name: 'adoption_level_last_q',
      value: 41.5,
      window: 'the 13 weeks before the cutoff',
      source: 'usage_weekly',
      coverage: 13,
      calculation_version: 'features_v1',
    },
  ],
  gaps: [
    'No qualitative evidence could be retrieved for this account at the cutoff.',
  ],
  requested_data: [
    {
      source: 'csm_notes and support_tickets',
      detail: 'documented account activity to corroborate the telemetry',
      window: 'the 26 weeks before the cutoff',
    },
  ],
  citations: [],
  limitations: ['No outcome label is reported.'],
  recommended_action: 'Supply the requested sources and re-run the assessment.',
  route: 'red',
  route_reason: 'critical coverage is missing',
  reason_code: 'RETRIEVAL_EXHAUSTED',
}

export function traceEvent(
  event: string,
  sequence: number,
  latency = 12.5,
): TraceEvent {
  return {
    run_id: 'RUN-test',
    thread_id: 'RUN-test',
    sequence,
    timestamp: '2026-09-01T10:00:00.000Z',
    node: 'node',
    event,
    payload: {},
    latency_ms: latency,
    prompt_tokens: 0,
    completion_tokens: 0,
  }
}

export const runState: AssessmentState = {
  run_id: 'RUN-test',
  account_id: 'ACC-1042',
  question: 'What is the renewal outlook for this account?',
  status: 'completed',
  started_at: '2026-09-01T10:00:00Z',
  finished_at: '2026-09-01T10:00:03Z',
  events_emitted: 3,
  last_event: 'run_completed',
  route: 'red',
  error: null,
  blocked: null,
  decision: forecast,
  guardrails: [
    {
      stage: 'intake',
      outcome: 'pass',
      rule_ids: [],
      reason_codes: [],
      message: 'ok',
    },
  ],
  trace: [traceEvent('run_started', 1), traceEvent('run_completed', 2)],
  assessment_id: 'ASMT-ACC-1042-0001',
  review_case_id: 'CASE-ACC-1042-0001-01',
  total_tokens: 0,
  model_calls: 0,
}

export const accountDetail: AccountDetail = {
  profile: {
    account_id: 'ACC-1042',
    account_name: 'Northwind Freight',
    segment: 'Strategic',
    industry: 'Logistics',
    region: 'NA',
    country: 'United States',
    employees: 4200,
    licensed_seats: 900,
    acv_usd: 1_250_000,
    contract_term_months: 12,
    contract_start_date: '2025-12-01',
    renewal_date: '2026-11-30',
    forecast_as_of_date: '2026-08-08',
    products_owned: ['Core', 'Analytics'],
    num_products: 2,
    primary_product: 'Core',
    csm_name: 'A. Rivera',
    exec_sponsor_name: 'J. Okafor',
    sponsor_status: 'lost',
    onboarding_completed: true,
  },
  effective_cutoff: '2026-08-01',
  high_value: true,
  high_value_reason: 'segment Strategic',
  indicators: {
    weeks_observed: 104,
    active_users_last_week: 612,
    adoption_trend_13w: -8.4,
    open_tickets: 3,
    escalations_26w: 2,
    average_ticket_sentiment: -0.21,
    external_events_26w: 1,
    sponsor_status: 'lost',
    onboarding_completed: true,
  },
  usage: Array.from({ length: 104 }, (_, index) => ({
    week_start: `2024-${String((index % 12) + 1).padStart(2, '0')}-0${(index % 7) + 1}`,
    active_users: 500 + index,
    sessions: 1200 + index * 3,
    feature_events: 8000 + index * 11,
    advanced_feature_adoption_pct: 30 + (index % 20),
  })),
  recent: [
    {
      kind: 'ticket',
      item_date: '2026-07-19',
      label: 'Reporting module timing out',
      detail: 'Bug · Urgent · Open',
      signal: 'negative',
    },
    {
      kind: 'note',
      item_date: '2026-07-02',
      label: 'QBR',
      detail: 'logged by A. Rivera',
      signal: 'positive',
    },
  ],
  prior_assessments: [
    {
      assessment_id: 'ASMT-ACC-1042-0001',
      created_at: '2026-08-20T09:00:00Z',
      cutoff: '2026-08-01',
      predicted_outcome: 'Renewed',
      confidence: 0.69,
      route: 'red',
      summary: 'Adoption held while escalations rose.',
    },
  ],
}

export const reviewCase: ReviewCase = {
  case_id: 'CASE-ACC-1042-0001-01',
  assessment_id: 'ASMT-ACC-1042-0001',
  account_id: 'ACC-1042',
  created_at: '2026-08-20T09:00:00Z',
  reason: 'the top two outcomes are within 0.28',
  status: 'open',
  route: 'red',
  reason_codes: ['route_red'],
  resolved_at: null,
  reviewer: null,
  action: null,
  reason_code: null,
  note: null,
  corrected_outcome: null,
}

export const reviewCard: ReviewCard = {
  case: reviewCase,
  question: 'What is the renewal outlook for this account?',
  cutoff: '2026-08-01',
  kind: 'forecast',
  proposed_outcome: 'Renewed',
  confidence: 0.69,
  decision: forecast,
}

export const scan: ScanView = {
  scan_id: 'SCAN-test',
  status: 'completed',
  started_at: '2026-09-01T10:00:00Z',
  finished_at: '2026-09-01T10:00:20Z',
  requested_accounts: 2,
  concurrency_limit: 4,
  model_call_budget: 200,
  summary: {
    scanned: 2,
    completed: 2,
    failed: 0,
    blocked: 0,
    auto_released: 0,
    queued_for_review: 2,
    abstentions: 1,
    risk_accounts: ['ACC-1042'],
    expansion_candidates: [],
    review_load: { red: 2 },
    total_model_calls: 0,
    total_tokens: 0,
    budget_exhausted: false,
    concurrency_observed: 2,
  },
  runs: [
    {
      account_id: 'ACC-1042',
      status: 'completed',
      route: 'red',
      outcome: 'Churned',
      confidence: 0.61,
      abstained: false,
      review_case_id: 'CASE-ACC-1042-0001-01',
      assessment_id: 'ASMT-ACC-1042-0001',
      model_calls: 0,
      tokens: 0,
      latency_ms: 2100,
      error: null,
    },
    {
      account_id: 'ACC-1096',
      status: 'completed',
      route: 'red',
      outcome: null,
      confidence: null,
      abstained: true,
      review_case_id: 'CASE-ACC-1096-0001-01',
      assessment_id: 'ASMT-ACC-1096-0001',
      model_calls: 0,
      tokens: 0,
      latency_ms: 1900,
      error: null,
    },
  ],
  skipped: [],
  error: null,
}

/**
 * Resolve the URL from whatever `fetch` was handed.
 *
 * `fetch` accepts a string, a `URL`, or a `Request`, and `String(request)`
 * yields `[object Request]` rather than the URL. A stub that matched on that
 * would silently fall through to its default for every request made through a
 * `Request` object.
 */
export function urlOf(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.toString()
  return input.url
}
