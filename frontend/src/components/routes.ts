/**
 * Route colours and meanings, kept out of the component module.
 *
 * Its own file so `Primitives.tsx` exports only components: a module that mixes
 * components with constants breaks React Fast Refresh, which is a development
 * annoyance rather than a bug, but the lint rule that catches it is worth
 * keeping on for the cases where it matters.
 */

import type { Route } from '../api'

/** Semantic status colours. Named once so a badge and a bar cannot disagree. */
export const routeColour: Record<Route, string> = {
  green: 'var(--status-green)',
  amber: 'var(--status-amber)',
  red: 'var(--status-red)',
  blocked: 'var(--status-blocked)',
}

export const routeMeaning: Record<Route, string> = {
  green: 'Auto-released as advisory output',
  amber: 'Provisional; queued for asynchronous review',
  red: 'Held for immediate human review',
  blocked: 'Refused by an intake guardrail',
}

/**
 * Narrow an arbitrary route string from the API to a known band.
 *
 * The server's `Route` is a closed set, but a stored review case carries its
 * route as free text, so an unrecognised value is possible and is shown as
 * `blocked` -- the most conservative of the four -- rather than rendered with
 * no styling at all.
 */
export function toRoute(value: string | null | undefined): Route {
  return value === 'green' || value === 'amber' || value === 'red'
    ? value
    : 'blocked'
}
