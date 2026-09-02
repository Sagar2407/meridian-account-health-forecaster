/**
 * The evaluation page (plan section 20.6).
 *
 * Section 20.6 lists metrics from every evaluation dimension. What this page
 * shows is what the harnesses have actually written: the system evaluation --
 * correctness, calibration, grounding, and the operational numbers -- plus the
 * safety report, the Tree-of-Thought ablation, and the retrieval benchmark,
 * each read from its published artifact.
 *
 * A dimension whose harness has not been run says so, by name, with the command
 * that produces it. That is the honest rendering: a dashboard that draws an
 * empty chart for an unrun evaluation implies a measurement nobody made.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchEvaluation, type EvaluationResult } from '../api'
import { formatMetric } from './formatMetric'
import { SystemEvaluation } from './SystemEvaluation'
import { EmptyNote, Spinner, SyntheticBanner } from '../components/Primitives'

const EVALUATIONS: { name: string; title: string; blurb: string }[] = [
  {
    name: 'system',
    title: 'Forecast correctness, calibration, and routing',
    blurb:
      'Every assessed account in one split, run through the real graph against the frozen thresholds. The held-out split is the released measurement; the development split is where the bands were chosen.',
  },
  {
    name: 'guardrails',
    title: 'Safety routing',
    blurb:
      'All 36 packaged guardrail cases through the real graph. Hard categories are graded as a binary refusal; behavioural categories against a named check.',
  },
  {
    name: 'tot',
    title: 'Linear versus conflict-gated Tree-of-Thought',
    blurb:
      'Both arms over the same conflicting development accounts, paired on the cases both answered.',
  },
  {
    name: 'guardrail_stack',
    title: 'What each guardrail layer is worth',
    blurb:
      'The same 36 cases through four stacks: no guardrails, intake only, intake plus evidence screening, and the full stack that ships.',
  },
  {
    name: 'retrieval',
    title: 'Retrieval benchmark',
    blurb:
      'Recall, precision, and the chunking ablation over the packaged retrieval set.',
  },
]

/** Metrics worth surfacing first, in the order a reader should meet them. */
const HEADLINE: Record<string, string[]> = {
  guardrails: [
    'hard_false_pass_rate',
    'false_block_rate',
    'disposition_accuracy',
    'disposition_exact_match',
    'behaviour_pass_rate',
    'cases',
    'total_tokens',
  ],
  tot: ['conflict_rate', 'paired_cases', 'agreement_rate'],
  retrieval: ['recall_at_5', 'precision_at_5', 'mrr'],
  guardrail_stack: ['cases'],
  system: [
    'macro_f1',
    'majority_baseline_accuracy',
    'expected_calibration_error',
    'supported_claim_rate',
    'exact_numeric_agreement',
    'auto_release_rate',
    'runs',
    'total_tokens',
  ],
}

export function EvaluationPage() {
  const [results, setResults] = useState<
    Record<string, EvaluationResult | null>
  >({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    void Promise.all(
      EVALUATIONS.map(async (item) => {
        try {
          return [
            item.name,
            await fetchEvaluation(item.name, controller.signal),
          ] as const
        } catch {
          return [item.name, null] as const
        }
      }),
    ).then((entries) => {
      if (controller.signal.aborted) return
      setResults(Object.fromEntries(entries))
      setLoading(false)
    })
    return () => controller.abort()
  }, [])

  return (
    <div className="page">
      <SyntheticBanner />

      <header className="page__header">
        <div>
          <p className="page__eyebrow">
            <Link to="/" className="inline-link">
              Portfolio
            </Link>
          </p>
          <h1>Evaluation</h1>
          <p className="page__lede">
            Published results, read from the artifacts the command-line
            harnesses wrote. Evaluations are never run from the browser: every
            harness reads outcome labels, and no served module may import them.
          </p>
        </div>
      </header>

      {loading ? (
        <Spinner label="Reading published evaluation artifacts…" />
      ) : null}

      {EVALUATIONS.map((item) => {
        const result = results[item.name]
        return (
          <section
            key={item.name}
            className="eval-section"
            aria-labelledby={`eval-${item.name}`}
          >
            <h2 id={`eval-${item.name}`}>{item.title}</h2>
            <p className="eval-section__blurb">{item.blurb}</p>

            {!result ? (
              !loading ? (
                <EmptyNote>This evaluation could not be read.</EmptyNote>
              ) : null
            ) : result.status === 'not_run' ? (
              <div className="eval-unrun">
                <p>
                  <strong>Not run in this checkout.</strong> {result.detail}
                </p>
                <p>
                  Produce it with <code>{result.command}</code>.
                </p>
              </div>
            ) : (
              <>
                <dl className="eval-metrics">
                  {(HEADLINE[item.name] ?? [])
                    .filter((key) => result.metrics?.[key] !== undefined)
                    .map((key) => (
                      <div key={key}>
                        <dt>{key.replace(/_/g, ' ')}</dt>
                        <dd>{formatMetric(result.metrics?.[key])}</dd>
                      </div>
                    ))}
                </dl>
                {item.name === 'system' && result.metrics ? (
                  <SystemEvaluation metrics={result.metrics} />
                ) : null}
                <details className="eval-raw">
                  <summary>Every metric in {result.artifact}</summary>
                  <dl className="eval-metrics eval-metrics--dense">
                    {Object.entries(result.metrics ?? {})
                      .filter(
                        ([, value]) =>
                          typeof value !== 'object' || Array.isArray(value),
                      )
                      .map(([key, value]) => (
                        <div key={key}>
                          <dt>{key.replace(/_/g, ' ')}</dt>
                          <dd>{formatMetric(value)}</dd>
                        </div>
                      ))}
                  </dl>
                </details>
              </>
            )}
          </section>
        )
      })}
    </div>
  )
}
