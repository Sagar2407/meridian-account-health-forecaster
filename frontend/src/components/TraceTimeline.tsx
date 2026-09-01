/**
 * The graph progress timeline (plan section 20.3).
 *
 * Section 20.3 asks for a compact timeline, parallel lane status, a retrieval
 * retry notice, a Tree-of-Thought badge only on conflict cases, and "no raw
 * hidden reasoning". The last one is not enforced here by filtering: the events
 * arriving over SSE are `TraceEvent`s, which are redacted where they are built,
 * so there is no prompt in the data for this component to leak.
 *
 * What this does add is meaning. `evidence_screened` and `budget_exhausted` are
 * not self-explanatory to a reader, so each event gets a plain-language line.
 */

import type { TraceEvent } from '../api'

const description: Record<string, string> = {
  run_started: 'Request received',
  request_validated: 'Intake guardrails passed',
  request_blocked: 'Refused by an intake guardrail',
  context_loaded: 'Sanitized profile and prior assessments loaded',
  plan_created: 'Evidence sub-goals planned',
  quantitative_completed: 'Deterministic metrics computed',
  retrieval_attempted: 'Qualitative evidence retrieved',
  retrieval_retried: 'Retrieval retried for uncovered sub-goals',
  evidence_screened: 'Evidence screened for account, cutoff, and provenance',
  evidence_merged: 'Both lanes merged into one evidence bundle',
  coverage_evaluated: 'Coverage assessed',
  evidence_round_started: 'Another evidence round started',
  conflict_detected: 'Material conflict found in the evidence',
  conflict_evaluated: 'Conflict rules evaluated',
  tot_started: 'Tree-of-Thought search started',
  tot_completed: 'Tree-of-Thought search finished',
  tot_pruned: 'Branches pruned by the hard checks',
  degraded_result: 'Degraded to verified telemetry with no label',
  decision_drafted: 'Decision drafted from the evidence',
  output_verified: 'Numeric claims and citations replayed',
  budget_exhausted:
    'Model budget reached; narrative composed deterministically',
  decision_routed: 'Human-review band assigned',
  review_required: 'Routed to a person',
  review_resumed: 'Resumed with a reviewer decision',
  decision_persisted: 'Recorded in application memory',
  node_failed: 'A step failed and was recovered',
  run_completed: 'Run finished',
}

const LANE_EVENTS = new Set(['quantitative_completed', 'retrieval_attempted'])

export function TraceTimeline({ events }: { events: TraceEvent[] }) {
  const retried = events.some((event) => event.event === 'retrieval_retried')
  const conflicted = events.some((event) => event.event === 'conflict_detected')
  const totRan = events.some((event) => event.event === 'tot_started')

  return (
    <div className="timeline-wrap">
      <div className="timeline-badges">
        {conflicted ? (
          <span
            className="badge badge--conflict"
            title="The evidence materially disagreed"
          >
            conflict
          </span>
        ) : null}
        {totRan ? (
          <span
            className="badge badge--tot"
            title="A bounded Tree-of-Thought search ran because the evidence conflicted"
          >
            Tree-of-Thought
          </span>
        ) : null}
        {retried ? (
          <span
            className="badge badge--retry"
            title="Retrieval was retried for uncovered sub-goals"
          >
            retrieval retry
          </span>
        ) : null}
      </div>

      <ol className="timeline">
        {events.map((event) => (
          <li
            key={event.sequence}
            className={`timeline__item${LANE_EVENTS.has(event.event) ? ' timeline__item--lane' : ''}`}
          >
            <span className="timeline__event">{event.event}</span>
            <span className="timeline__description">
              {description[event.event] ?? 'Step completed'}
            </span>
            <span className="timeline__latency">
              {event.latency_ms > 0 ? `${event.latency_ms.toFixed(0)} ms` : ''}
            </span>
          </li>
        ))}
      </ol>
      {events.length === 0 ? (
        <p className="empty-note">Waiting for the first event…</p>
      ) : null}
    </div>
  )
}
