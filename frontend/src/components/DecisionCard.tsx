/**
 * The forecast decision card (plan section 20.4).
 *
 * Section 20.4 lists nine things a card must carry, and the shape of the data
 * decides which of two cards is rendered: a `ForecastDecision` has an outcome,
 * an `InsufficientEvidenceDecision` does not have the field at all. That is why
 * the abstention path here cannot accidentally show a label -- there is nothing
 * to read it from, not a flag someone remembered to check.
 */

import { useState } from 'react'

import type { Citation, Decision } from '../api'
import { isForecast } from '../api'
import { CitationList, EvidenceDrawer } from './EvidenceDrawer'
import { ConfidenceGauge, DistributionBars, RouteBadge } from './Primitives'

function Limitations({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return (
    <section className="card__section">
      <h3>Coverage and limitations</h3>
      <ul className="plain-list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  )
}

export function DecisionCard({ decision }: { decision: Decision }) {
  const [selected, setSelected] = useState<Citation | null>(null)

  if (!isForecast(decision)) {
    return (
      <article
        className="card card--abstained"
        aria-labelledby="decision-title"
      >
        <header className="card__header">
          <div>
            <p className="card__eyebrow">Assessment · {decision.account_id}</p>
            <h2 id="decision-title">No categorical forecast</h2>
          </div>
          <RouteBadge route={decision.route} />
        </header>

        <p className="card__lede">
          The evidence required to support an outcome was not available at{' '}
          {decision.cutoff}. Rather than guess, the system reports what it did
          verify and what it needs.
        </p>

        {decision.verified_metrics.length > 0 ? (
          <section className="card__section">
            <h3>Verified telemetry</h3>
            <table className="metric-table">
              <thead>
                <tr>
                  <th scope="col">Metric</th>
                  <th scope="col">Value</th>
                  <th scope="col">Window</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {decision.verified_metrics.slice(0, 12).map((metric) => (
                  <tr key={metric.name}>
                    <th scope="row">{metric.name}</th>
                    <td>{metric.value}</td>
                    <td>{metric.window}</td>
                    <td>{metric.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : null}

        <section className="card__section">
          <h3>Evidence gaps</h3>
          <ul className="plain-list">
            {decision.gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </section>

        {decision.requested_data.length > 0 ? (
          <section className="card__section">
            <h3>What would unblock this</h3>
            <ul className="plain-list">
              {decision.requested_data.map((item) => (
                <li key={item.source}>
                  <strong>{item.source}</strong> — {item.detail}
                  {item.window ? ` (${item.window})` : ''}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {/* An abstention still carries the evidence it *was* able to
            retrieve. Dropping it here was a real gap: a reviewer deciding
            whether the system was right to withhold a label needs to see what
            it read, and that is precisely the case where the evidence matters
            most. */}
        <section className="card__section">
          <h3>Evidence retrieved before abstaining</h3>
          <CitationList
            citations={decision.citations}
            onSelect={setSelected}
            emptyLabel="No evidence could be retrieved for this account at this cutoff."
          />
        </section>

        <Limitations items={decision.limitations} />

        <section className="card__section">
          <h3>Recommended next action</h3>
          <p>{decision.recommended_action}</p>
          <p className="card__route-reason">
            <RouteBadge route={decision.route} /> {decision.route_reason}
          </p>
        </section>

        <EvidenceDrawer citation={selected} onClose={() => setSelected(null)} />
      </article>
    )
  }

  const supporting = decision.citations.filter(
    (item) => item.signal === 'favorable',
  )
  const context = decision.citations.filter(
    (item) => item.signal !== 'favorable',
  )

  return (
    <>
      <article className="card" aria-labelledby="decision-title">
        <header className="card__header">
          <div>
            <p className="card__eyebrow">Assessment · {decision.account_id}</p>
            <h2 id="decision-title">{decision.outcome}</h2>
            <p className="card__cutoff">
              Point-in-time cutoff {decision.cutoff}
            </p>
          </div>
          <RouteBadge route={decision.route} />
        </header>

        <div className="card__confidence">
          <ConfidenceGauge
            confidence={decision.confidence}
            route={decision.route}
          />
          <DistributionBars
            distribution={decision.distribution}
            outcome={decision.outcome}
          />
        </div>

        {decision.confidence_breakdown.applied_caps.length > 0 ? (
          <p className="card__caps">
            Confidence was capped:{' '}
            {decision.confidence_breakdown.applied_caps
              .join(', ')
              .replace(/_/g, ' ')}
            .
          </p>
        ) : null}

        <section className="card__section">
          <h3>Why</h3>
          <p>{decision.rationale}</p>
          <p className="card__provenance">
            Outcome from the calibrated forecaster; narrative{' '}
            {decision.narrative_source === 'model'
              ? `written by ${decision.model_name || 'the configured model'} and replayed against the evidence`
              : 'composed from verified values'}
            . Adjudicated by the{' '}
            {decision.selected_by === 'tree_of_thought'
              ? 'bounded Tree-of-Thought search'
              : 'linear path'}
            .
          </p>
        </section>

        {decision.drivers.length > 0 ? (
          <section className="card__section">
            <h3>Drivers</h3>
            <ul className="driver-list">
              {decision.drivers.map((driver) => (
                <li
                  key={driver.feature}
                  className={`driver driver--${driver.direction}`}
                >
                  <span className="driver__name">{driver.feature}</span>
                  <span className="driver__value">{driver.value}</span>
                  <span className="driver__direction">
                    {driver.direction === 'supports'
                      ? 'supports renewal'
                      : 'raises risk'}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <div className="card__evidence">
          <section className="card__section">
            <h3>Supporting evidence</h3>
            <CitationList
              citations={supporting}
              onSelect={setSelected}
              emptyLabel="No citation in the retrieved set points this way."
            />
          </section>
          <section className="card__section">
            <h3>Counterevidence</h3>
            <CitationList
              citations={decision.counterevidence}
              onSelect={setSelected}
              emptyLabel="Nothing retrieved contradicts this outcome."
            />
          </section>
        </div>

        {context.length > 0 ? (
          <section className="card__section">
            <h3>Other retrieved context</h3>
            <CitationList
              citations={context}
              onSelect={setSelected}
              emptyLabel="No further context."
            />
          </section>
        ) : null}

        <Limitations items={decision.limitations} />

        <section className="card__section">
          <h3>Recommended next action</h3>
          <p>{decision.recommended_action}</p>
          <p className="card__route-reason">
            <RouteBadge route={decision.route} /> {decision.route_reason}
          </p>
        </section>
      </article>

      <EvidenceDrawer citation={selected} onClose={() => setSelected(null)} />
    </>
  )
}
