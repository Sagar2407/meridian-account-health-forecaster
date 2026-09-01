/**
 * The decision card, including the two states it must never confuse.
 *
 * The abstention test is the important one. `InsufficientEvidenceDecision` has
 * no outcome field, and the assertion here is negative -- no outcome word
 * anywhere in the rendered card -- because that is the property the plan asks
 * for and a positive assertion about the abstention text would still pass if a
 * label leaked in beside it.
 */

import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DecisionCard } from '../src/components/DecisionCard'
import {
  abstention,
  counterCitation,
  forecast,
  supportingCitation,
} from './fixtures'

describe('DecisionCard', () => {
  it('shows the outcome, the whole distribution, and the review route', () => {
    render(<DecisionCard decision={forecast} />)

    expect(screen.getByRole('heading', { name: 'Renewed' })).toBeInTheDocument()

    // "Renewed" is both the headline and a row in the distribution, so the
    // distribution is scoped rather than searched for across the whole card.
    const distribution = screen.getByLabelText(
      'Calibrated outcome distribution',
    )
    for (const outcome of ['Renewed', 'Churned', 'Contracted', 'Expanded']) {
      expect(within(distribution).getByText(outcome)).toBeInTheDocument()
    }
    // The badge appears twice by design: once in the header, once beside the
    // reason it was assigned.
    expect(screen.getAllByLabelText(/Human review route: red/)).toHaveLength(2)
    expect(
      screen.getByText(/the top two outcomes are within/),
    ).toBeInTheDocument()
  })

  it('says when confidence was capped rather than showing only the number', () => {
    render(<DecisionCard decision={forecast} />)

    expect(
      screen.getByText(/Confidence was capped: persistent tie/),
    ).toBeInTheDocument()
  })

  it('names where the outcome and the narrative each came from', () => {
    render(<DecisionCard decision={forecast} />)

    expect(
      screen.getByText(/Outcome from the calibrated forecaster/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/composed from verified values/),
    ).toBeInTheDocument()
  })

  it('separates supporting evidence from counterevidence', () => {
    render(<DecisionCard decision={forecast} />)

    const supporting = screen.getByRole('heading', {
      name: 'Supporting evidence',
    }).parentElement as HTMLElement
    const counter = screen.getByRole('heading', { name: 'Counterevidence' })
      .parentElement as HTMLElement

    expect(within(supporting).getByText('NOTE-1042-08')).toBeInTheDocument()
    expect(within(counter).getByText('TICKET-1042-31')).toBeInTheDocument()
  })

  it('opens a citation in a dialog with its id, type, date, and excerpt', () => {
    render(<DecisionCard decision={forecast} />)

    fireEvent.click(screen.getByText('TICKET-1042-31'))

    const dialog = screen.getByRole('dialog')
    expect(
      within(dialog).getByRole('heading', { name: 'TICKET-1042-31' }),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('support_tickets')).toBeInTheDocument()
    expect(within(dialog).getByText('2026-07-19')).toBeInTheDocument()
    expect(
      within(dialog).getByText(/Third escalation this quarter/),
    ).toBeInTheDocument()
  })

  it('closes the drawer on Escape', () => {
    render(<DecisionCard decision={forecast} />)

    fireEvent.click(screen.getByText('NOTE-1042-08'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('labels knowledge-base guidance as having no account', () => {
    render(<DecisionCard decision={forecast} />)

    fireEvent.click(screen.getByText('KB-014'))

    expect(screen.getByText('Knowledge base (no account)')).toBeInTheDocument()
    expect(screen.getByText('Undated guidance')).toBeInTheDocument()
  })

  it('renders an abstention with no outcome label anywhere', () => {
    render(<DecisionCard decision={abstention} />)

    expect(
      screen.getByRole('heading', { name: 'No categorical forecast' }),
    ).toBeInTheDocument()

    for (const outcome of ['Renewed', 'Churned', 'Contracted', 'Expanded']) {
      expect(screen.queryByText(outcome)).not.toBeInTheDocument()
    }
    expect(screen.queryByText(/Confidence was capped/)).not.toBeInTheDocument()
  })

  it('shows an abstention its verified telemetry and what would unblock it', () => {
    render(<DecisionCard decision={abstention} />)

    expect(screen.getByText('adoption_level_last_q')).toBeInTheDocument()
    expect(screen.getByText('41.5')).toBeInTheDocument()
    expect(
      screen.getByText(/csm_notes and support_tickets/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/No qualitative evidence could be retrieved/),
    ).toBeInTheDocument()
  })
})

describe('DecisionCard with the sparsest data the API can send', () => {
  it('omits every optional section rather than rendering empty headings', () => {
    render(
      <DecisionCard
        decision={{
          ...abstention,
          verified_metrics: [],
          requested_data: [],
          limitations: [],
        }}
      />,
    )

    expect(
      screen.getByRole('heading', { name: 'No categorical forecast' }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Verified telemetry' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'What would unblock this' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'Coverage and limitations' }),
    ).not.toBeInTheDocument()
  })

  it('says so when a forecast has no drivers and nothing contradicts it', () => {
    render(
      <DecisionCard
        decision={{
          ...forecast,
          drivers: [],
          citations: [],
          counterevidence: [],
          confidence_breakdown: {
            ...forecast.confidence_breakdown,
            applied_caps: [],
          },
        }}
      />,
    )

    expect(
      screen.queryByRole('heading', { name: 'Drivers' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/Confidence was capped/)).not.toBeInTheDocument()
    expect(
      screen.getByText('No citation in the retrieved set points this way.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Nothing retrieved contradicts this outcome.'),
    ).toBeInTheDocument()
  })

  it('credits a model narrative to the model that wrote it', () => {
    render(
      <DecisionCard
        decision={{
          ...forecast,
          narrative_source: 'model',
          model_name: 'anthropic/claude-sonnet-4.5',
          selected_by: 'tree_of_thought',
        }}
      />,
    )

    expect(
      screen.getByText(
        /written by anthropic\/claude-sonnet-4.5 and replayed against the evidence/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/bounded Tree-of-Thought search/),
    ).toBeInTheDocument()
  })
})

describe('an abstention still shows what it read', () => {
  it('lists the evidence retrieved before it declined to label', () => {
    render(
      <DecisionCard
        decision={{
          ...abstention,
          citations: [supportingCitation, counterCitation],
        }}
      />,
    )

    expect(
      screen.getByRole('heading', {
        name: 'Evidence retrieved before abstaining',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('NOTE-1042-08')).toBeInTheDocument()
    expect(screen.getByText('TICKET-1042-31')).toBeInTheDocument()
  })

  it('opens that evidence in the same drawer a forecast uses', () => {
    render(
      <DecisionCard
        decision={{ ...abstention, citations: [counterCitation] }}
      />,
    )

    fireEvent.click(screen.getByText('TICKET-1042-31'))

    const dialog = screen.getByRole('dialog')
    expect(
      within(dialog).getByText(/Third escalation this quarter/),
    ).toBeInTheDocument()
  })

  it('says plainly when it retrieved nothing at all', () => {
    render(<DecisionCard decision={{ ...abstention, citations: [] }} />)

    expect(
      screen.getByText(
        'No evidence could be retrieved for this account at this cutoff.',
      ),
    ).toBeInTheDocument()
  })
})
