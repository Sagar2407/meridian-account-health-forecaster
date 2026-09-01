/**
 * The 104-week usage trajectory with its effective-cutoff marker (section 20.2).
 *
 * The cutoff marker is the point of the chart. Every series here already ends
 * at the cutoff, because the API filters there, and drawing the boundary makes
 * that visible rather than something a reader has to take on trust.
 *
 * Hand-drawn SVG, and deliberately not interactive: a tooltip that follows a
 * pointer is unusable on a keyboard, so the numbers a reader needs are in the
 * indicator strip beside it and in the table below.
 */

import type { UsagePoint } from '../api'

const WIDTH = 720
const HEIGHT = 200
const PADDING = { top: 12, right: 16, bottom: 26, left: 44 }

type Series = 'active_users' | 'sessions' | 'feature_events'

export function UsageChart({
  usage,
  cutoff,
  series = 'active_users',
}: {
  usage: UsagePoint[]
  cutoff: string
  series?: Series
}) {
  if (usage.length === 0) {
    return (
      <p className="empty-note">
        No telemetry was observed for this account at or before {cutoff}.
      </p>
    )
  }

  const values = usage.map((point) => point[series])
  const maximum = Math.max(...values, 1)
  const innerWidth = WIDTH - PADDING.left - PADDING.right
  const innerHeight = HEIGHT - PADDING.top - PADDING.bottom
  const step = usage.length > 1 ? innerWidth / (usage.length - 1) : 0

  const points = usage.map((point, index) => {
    const x = PADDING.left + index * step
    const y =
      PADDING.top + innerHeight - (point[series] / maximum) * innerHeight
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })

  const area = `M ${PADDING.left},${PADDING.top + innerHeight} L ${points.join(
    ' L ',
  )} L ${(PADDING.left + (usage.length - 1) * step).toFixed(1)},${
    PADDING.top + innerHeight
  } Z`

  const first = usage[0].week_start
  const last = usage[usage.length - 1].week_start
  const label = series.replace(/_/g, ' ')

  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`Weekly ${label} from ${first} to ${last}, peaking at ${maximum}. The series ends at the effective cutoff ${cutoff}.`}
        preserveAspectRatio="xMidYMid meet"
      >
        {[0, 0.5, 1].map((fraction) => {
          const y = PADDING.top + innerHeight * fraction
          return (
            <g key={fraction}>
              <line
                x1={PADDING.left}
                y1={y}
                x2={WIDTH - PADDING.right}
                y2={y}
                className="chart__grid"
              />
              <text
                x={PADDING.left - 8}
                y={y + 4}
                className="chart__tick"
                textAnchor="end"
              >
                {Math.round(maximum * (1 - fraction))}
              </text>
            </g>
          )
        })}

        <path d={area} className="chart__area" />
        <polyline
          points={points.join(' ')}
          className="chart__line"
          fill="none"
        />

        {/* The effective cutoff: the last week any evidence may come from. */}
        <line
          x1={WIDTH - PADDING.right}
          y1={PADDING.top}
          x2={WIDTH - PADDING.right}
          y2={PADDING.top + innerHeight}
          className="chart__cutoff"
        />
        <text
          x={WIDTH - PADDING.right - 6}
          y={PADDING.top + 12}
          className="chart__cutoff-label"
          textAnchor="end"
        >
          cutoff {cutoff}
        </text>

        <text x={PADDING.left} y={HEIGHT - 6} className="chart__tick">
          {first}
        </text>
        <text
          x={WIDTH - PADDING.right}
          y={HEIGHT - 6}
          className="chart__tick"
          textAnchor="end"
        >
          {last}
        </text>
      </svg>
      <figcaption>
        Weekly {label}, summed across products, over the {usage.length} observed
        weeks. Nothing after the effective cutoff is charted, because nothing
        after it was available to the assessment.
      </figcaption>
    </figure>
  )
}
