/**
 * The clickable evidence drawer (plan section 20.4).
 *
 * Section 20.4 asks that a citation be inspectable by source id, type, date,
 * and excerpt. The drawer shows exactly those four and nothing else: the
 * excerpt is what retrieval selected and what output verification replayed, so
 * a reader is looking at the evidence the decision was checked against rather
 * than at a summary of it.
 *
 * It is a dialog because it takes focus and must be dismissible: Escape closes
 * it, focus moves to the close button on open, and the trigger keeps its own
 * focus ring so a keyboard reader can tell what they opened.
 */

import { useEffect, useRef } from 'react'

import type { Citation } from '../api'

const signalLabel: Record<Citation['signal'], string> = {
  favorable: 'Points toward a favourable outcome',
  adverse: 'Points toward an adverse outcome',
  neutral: 'Context; points neither way',
}

export function EvidenceDrawer({
  citation,
  onClose,
}: {
  citation: Citation | null
  onClose: () => void
}) {
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!citation) return undefined
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [citation, onClose])

  if (!citation) return null

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="drawer__header">
          <h2 id="drawer-title">{citation.doc_id}</h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="button button--ghost"
          >
            Close
          </button>
        </header>

        <dl className="drawer__meta">
          <div>
            <dt>Source type</dt>
            <dd>{citation.source_type}</dd>
          </div>
          <div>
            <dt>Subtype</dt>
            <dd>{citation.subtype}</dd>
          </div>
          <div>
            <dt>Account</dt>
            <dd>{citation.account_id ?? 'Knowledge base (no account)'}</dd>
          </div>
          <div>
            <dt>Date</dt>
            <dd>{citation.doc_date ?? 'Undated guidance'}</dd>
          </div>
          <div>
            <dt>Signal</dt>
            <dd>{signalLabel[citation.signal]}</dd>
          </div>
          <div>
            <dt>Retrieval score</dt>
            <dd>{citation.retrieval_score.toFixed(3)}</dd>
          </div>
        </dl>

        <h3>Excerpt</h3>
        <blockquote className="drawer__excerpt">{citation.excerpt}</blockquote>
        <p className="drawer__note">
          This is the passage retrieval selected and output verification
          replayed the decision&rsquo;s claims against.
        </p>
      </aside>
    </div>
  )
}

export function CitationList({
  citations,
  onSelect,
  emptyLabel,
}: {
  citations: Citation[]
  onSelect: (citation: Citation) => void
  emptyLabel: string
}) {
  if (citations.length === 0) {
    return <p className="empty-note">{emptyLabel}</p>
  }
  return (
    <ul className="citation-list">
      {citations.map((citation) => (
        <li key={citation.doc_id}>
          <button
            type="button"
            className={`citation citation--${citation.signal}`}
            onClick={() => onSelect(citation)}
          >
            <span className="citation__id">{citation.doc_id}</span>
            <span className="citation__meta">
              {citation.subtype}
              {citation.doc_date ? ` · ${citation.doc_date}` : ''}
            </span>
            <span className="citation__excerpt">
              {citation.excerpt.slice(0, 120)}…
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
