/**
 * The forecast-correctness, calibration, and routing tables (plan section 20.6).
 *
 * Section 20.6 asks for a confusion matrix, a calibration view, and the
 * grounding and operational numbers. Those are scalars and small tables inside
 * one summary artifact rather than a scalar each, so they get a renderer of
 * their own instead of the generic definition list the other evaluations use.
 *
 * Everything here is read from the artifact. Nothing is computed in the
 * browser: a number the harness did not measure must not appear on the page
 * because a component could derive it.
 */

import { useState } from 'react'

import { formatMetric } from './formatMetric'

/** One split's entry in `artifacts/evaluation/summary.json`. */
export type SplitSummary = {
  directory?: string
  commit?: string
  generated_at?: string
  per_class?: Record<
    string,
    { precision: number; recall: number; f1: number; support: number }
  >
  confusion_matrix?: { classes: string[]; rows: number[][] }
  routing_quality?: Record<
    string,
    {
      count: number
      errors: number
      error_rate: number
      auto_released: boolean
    }
  >
  release_targets?: {
    metric: string
    target: number
    measured: number | null
    met: boolean | null
  }[]
  [key: string]: unknown
}

type Props = {
  metrics: Record<string, unknown>
}

/** Human labels for the split names the harness writes. */
const SPLIT_LABELS: Record<string, string> = {
  test: 'Held out',
  development: 'Development',
}

function targetState(met: boolean | null): string {
  if (met === null) return 'not measured'
  return met ? 'met' : 'NOT MET'
}

export function SystemEvaluation({ metrics }: Props) {
  const splits = (metrics.splits ?? {}) as Record<string, SplitSummary>
  const names = Object.keys(splits).sort()
  // `metrics` is whatever the artifact held, so the split name is narrowed
  // rather than coerced: `String()` on an unexpected object would silently
  // produce '[object Object]' and select no split at all.
  const declared = metrics.headline_split
  const headline = typeof declared === 'string' ? declared : (names[0] ?? '')
  const [selected, setSelected] = useState(headline)
  const split = splits[selected] ?? splits[headline]

  if (!split) return null

  const perClass = split.per_class ?? {}
  const confusion = split.confusion_matrix
  const routing = split.routing_quality ?? {}
  const targets = split.release_targets ?? []

  return (
    <div className="eval-system">
      {names.length > 1 ? (
        <div
          className="eval-system__splits"
          role="group"
          aria-label="Evaluation split"
        >
          {names.map((name) => (
            <button
              key={name}
              type="button"
              className="eval-system__split"
              aria-pressed={name === selected}
              onClick={() => setSelected(name)}
            >
              {SPLIT_LABELS[name] ?? name}
            </button>
          ))}
        </div>
      ) : null}

      <p className="eval-system__provenance">
        {SPLIT_LABELS[selected] ?? selected} split, measured at commit{' '}
        <code>{split.commit ?? 'unknown'}</code>
        {split.directory ? (
          <>
            {' '}
            in <code>artifacts/evaluation/{split.directory}/</code>
          </>
        ) : null}
        .
      </p>

      {targets.length ? (
        <table className="eval-table">
          <caption>Release targets — measured against the frozen bands</caption>
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col">Target</th>
              <th scope="col">Measured</th>
              <th scope="col">Result</th>
            </tr>
          </thead>
          <tbody>
            {targets.map((row) => (
              <tr key={row.metric} data-met={targetState(row.met)}>
                <th scope="row">{row.metric}</th>
                <td>{formatMetric(row.target)}</td>
                <td>{formatMetric(row.measured)}</td>
                <td>{targetState(row.met)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {Object.keys(perClass).length ? (
        <table className="eval-table">
          <caption>Per class</caption>
          <thead>
            <tr>
              <th scope="col">Class</th>
              <th scope="col">Precision</th>
              <th scope="col">Recall</th>
              <th scope="col">F1</th>
              <th scope="col">Support</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(perClass).map(([name, row]) => (
              <tr key={name}>
                <th scope="row">{name}</th>
                <td>{formatMetric(row.precision)}</td>
                <td>{formatMetric(row.recall)}</td>
                <td>{formatMetric(row.f1)}</td>
                <td>{row.support}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {confusion && confusion.classes?.length ? (
        <table className="eval-table">
          <caption>
            Confusion matrix — rows are truth, columns prediction
          </caption>
          <thead>
            <tr>
              <th scope="col">Truth</th>
              {confusion.classes.map((name) => (
                <th scope="col" key={name}>
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {confusion.rows.map((row, index) => (
              <tr key={confusion.classes[index] ?? index}>
                <th scope="row">{confusion.classes[index]}</th>
                {row.map((value, column) => (
                  <td
                    key={confusion.classes[column] ?? column}
                    data-diagonal={index === column}
                  >
                    {value}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {Object.keys(routing).length ? (
        <table className="eval-table">
          <caption>
            Error rate inside each review band — what a reviewer is promised
          </caption>
          <thead>
            <tr>
              <th scope="col">Band</th>
              <th scope="col">Runs</th>
              <th scope="col">Errors</th>
              <th scope="col">Error rate</th>
              <th scope="col">Auto released</th>
            </tr>
          </thead>
          <tbody>
            {['green', 'amber', 'red']
              .filter((band) => routing[band])
              .map((band) => (
                <tr key={band}>
                  <th scope="row" data-route={band}>
                    {band}
                  </th>
                  <td>{routing[band].count}</td>
                  <td>{routing[band].errors}</td>
                  <td>{formatMetric(routing[band].error_rate)}</td>
                  <td>{routing[band].auto_released ? 'yes' : 'no'}</td>
                </tr>
              ))}
          </tbody>
        </table>
      ) : null}
    </div>
  )
}
