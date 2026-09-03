/**
 * Small shared pieces: route badges, gauges, bars, and the synthetic banner.
 *
 * The charts are hand-drawn SVG rather than a charting dependency. Three
 * reasons, in order: every one of these is a bar, a line, or an arc; a chart
 * library would add more to the bundle than the whole application currently
 * weighs, on a deployment target where image size affects cold start; and the
 * accessible name and description of each figure matter here (section 20.7
 * asks for verified contrast and responsive behaviour), which is easier to get
 * right when the markup is ours.
 */

import type { ReactNode } from 'react'

import { routeColour, routeMeaning, toRoute } from './routes'

export function RouteBadge({ route }: { route: string | null | undefined }) {
  const known = toRoute(route)
  const meaning = routeMeaning[known]
  return (
    <span
      className={`badge badge--${known}`}
      title={meaning}
      aria-label={`Human review route: ${known}. ${meaning}`}
    >
      {known}
    </span>
  )
}

export function SyntheticBanner() {
  return (
    <div className="synthetic-banner" role="note">
      <strong>Synthetic data.</strong> Every account, ticket, note, and event is
      generated. Nothing here describes a real company, and the system takes no
      action on any customer &mdash; every result is advisory.
    </div>
  )
}

export function Spinner({ label }: { label: string }) {
  return (
    <p className="spinner" role="status" aria-live="polite">
      {label}
    </p>
  )
}

export function ErrorNote({
  message,
  code,
}: {
  message: string
  code?: string
}) {
  return (
    <div className="error-note" role="alert">
      {code ? <span className="error-note__code">{code}</span> : null}
      <span>{message}</span>
    </div>
  )
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="empty-note">{children}</p>
}

/**
 * A confidence gauge as an SVG arc.
 *
 * The band thresholds are drawn on the arc rather than described beside it, so
 * a reader can see how close a number is to the next band. That is the thing a
 * bare percentage hides: 0.79 and 0.80 look almost identical and mean
 * "provisional" and "auto-released".
 *
 * REVIEW_BANDS mirrors `meridian.graph.thresholds`, which is the only source of
 * truth for them. It is duplicated here because the gauge is drawn before any
 * request resolves, and `test_browser_contract.py` fails if the two drift: a
 * gauge whose tick sits at the old band tells a reader a released answer was
 * held back.
 */
export const REVIEW_BANDS = [0.7, 0.8] as const

export function ConfidenceGauge({
  confidence,
  route,
}: {
  confidence: number
  route: string | null | undefined
}) {
  const radius = 52
  const circumference = Math.PI * radius
  const clamped = Math.max(0, Math.min(1, confidence))
  const filled = circumference * clamped
  const colour = routeColour[toRoute(route)]
  const percent = Math.round(clamped * 100)

  return (
    <figure className="gauge">
      <svg
        viewBox="0 0 128 72"
        role="img"
        aria-label={`Confidence ${percent} percent`}
      >
        <path
          d="M 12 64 A 52 52 0 0 1 116 64"
          className="gauge__track"
          fill="none"
          strokeWidth="12"
          strokeLinecap="round"
        />
        <path
          d="M 12 64 A 52 52 0 0 1 116 64"
          fill="none"
          stroke={colour}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
        />
        {REVIEW_BANDS.map((threshold) => {
          const angle = Math.PI * (1 - threshold)
          return (
            <line
              key={threshold}
              x1={64 + Math.cos(angle) * 44}
              y1={64 - Math.sin(angle) * 44}
              x2={64 + Math.cos(angle) * 60}
              y2={64 - Math.sin(angle) * 60}
              className="gauge__threshold"
            />
          )
        })}
        <text x="64" y="58" className="gauge__value" textAnchor="middle">
          {clamped.toFixed(2)}
        </text>
      </svg>
      <figcaption>
        Evidence-aware confidence. Ticks mark the {REVIEW_BANDS[0].toFixed(2)}{' '}
        and {REVIEW_BANDS[1].toFixed(2)} review bands.
      </figcaption>
    </figure>
  )
}

/** The four-class distribution, as labelled bars. */
export function DistributionBars({
  distribution,
  outcome,
}: {
  distribution: Record<string, number>
  outcome?: string
}) {
  const entries = Object.entries(distribution).sort((a, b) => b[1] - a[1])
  return (
    <ul className="distribution" aria-label="Calibrated outcome distribution">
      {entries.map(([name, value]) => (
        <li key={name} className={name === outcome ? 'is-selected' : undefined}>
          <span className="distribution__name">{name}</span>
          <span className="distribution__track" aria-hidden="true">
            <span
              className="distribution__fill"
              style={{ width: `${Math.round(value * 100)}%` }}
            />
          </span>
          <span className="distribution__value">
            {(value * 100).toFixed(1)}%
          </span>
        </li>
      ))}
    </ul>
  )
}
