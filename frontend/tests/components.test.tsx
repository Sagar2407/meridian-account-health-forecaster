/** The chart, gauge, badge, and timeline, including their accessible names. */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  ConfidenceGauge,
  DistributionBars,
  RouteBadge,
} from '../src/components/Primitives'
import { TraceTimeline } from '../src/components/TraceTimeline'
import { UsageChart } from '../src/components/UsageChart'
import { accountDetail, traceEvent } from './fixtures'

describe('RouteBadge', () => {
  it('gives every band a name a screen reader can read, not just a colour', () => {
    render(<RouteBadge route="amber" />)

    expect(
      screen.getByLabelText(
        'Human review route: amber. Provisional; queued for asynchronous review',
      ),
    ).toBeInTheDocument()
  })

  it('falls back to the most conservative band for an unknown route', () => {
    render(<RouteBadge route="something-else" />)

    expect(screen.getByText('blocked')).toBeInTheDocument()
  })
})

describe('ConfidenceGauge', () => {
  it('states the confidence as a percentage in its accessible name', () => {
    render(<ConfidenceGauge confidence={0.69} route="red" />)

    expect(
      screen.getByRole('img', { name: 'Confidence 69 percent' }),
    ).toBeInTheDocument()
    expect(screen.getByText('0.69')).toBeInTheDocument()
  })

  it('clamps a value outside zero to one rather than drawing past the arc', () => {
    render(<ConfidenceGauge confidence={1.8} route="green" />)

    expect(
      screen.getByRole('img', { name: 'Confidence 100 percent' }),
    ).toBeInTheDocument()
  })
})

describe('DistributionBars', () => {
  it('orders classes by probability and marks the selected outcome', () => {
    render(
      <DistributionBars
        distribution={{
          Renewed: 0.52,
          Churned: 0.24,
          Contracted: 0.16,
          Expanded: 0.08,
        }}
        outcome="Renewed"
      />,
    )

    const items = screen.getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Renewed')
    expect(items[0]).toHaveClass('is-selected')
    expect(items[3]).toHaveTextContent('Expanded')
  })
})

describe('UsageChart', () => {
  it('names the cutoff in the figure a screen reader hears', () => {
    render(
      <UsageChart
        usage={accountDetail.usage}
        cutoff={accountDetail.effective_cutoff}
      />,
    )

    const figure = screen.getByRole('img', { name: /Weekly active users/ })
    expect(figure).toHaveAccessibleName(
      /ends at the effective cutoff 2026-08-01/,
    )
    expect(screen.getByText(/cutoff 2026-08-01/)).toBeInTheDocument()
  })

  it('says so plainly when there is no telemetry rather than drawing an empty axis', () => {
    render(<UsageChart usage={[]} cutoff="2026-08-01" />)

    expect(
      screen.getByText(
        /No telemetry was observed for this account at or before 2026-08-01/,
      ),
    ).toBeInTheDocument()
  })
})

describe('TraceTimeline', () => {
  it('translates each event into a line a reader can act on', () => {
    render(
      <TraceTimeline
        events={[
          traceEvent('run_started', 1),
          traceEvent('evidence_screened', 2),
        ]}
      />,
    )

    expect(screen.getByText('Request received')).toBeInTheDocument()
    expect(
      screen.getByText('Evidence screened for account, cutoff, and provenance'),
    ).toBeInTheDocument()
  })

  it('badges Tree-of-Thought only when the search actually ran', () => {
    const { rerender } = render(
      <TraceTimeline events={[traceEvent('run_started', 1)]} />,
    )
    expect(screen.queryByText('Tree-of-Thought')).not.toBeInTheDocument()

    rerender(
      <TraceTimeline
        events={[
          traceEvent('run_started', 1),
          traceEvent('conflict_detected', 2),
          traceEvent('tot_started', 3),
        ]}
      />,
    )
    expect(screen.getByText('Tree-of-Thought')).toBeInTheDocument()
    expect(screen.getByText('conflict')).toBeInTheDocument()
  })

  it('flags a retrieval retry, which is otherwise invisible in the list', () => {
    render(
      <TraceTimeline
        events={[
          traceEvent('retrieval_attempted', 1),
          traceEvent('retrieval_retried', 2),
        ]}
      />,
    )

    expect(screen.getByText('retrieval retry')).toBeInTheDocument()
  })

  it('waits rather than showing an empty list before the first event', () => {
    render(<TraceTimeline events={[]} />)

    expect(screen.getByText('Waiting for the first event…')).toBeInTheDocument()
  })
})
