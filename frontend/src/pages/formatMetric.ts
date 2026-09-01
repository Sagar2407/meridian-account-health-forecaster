/**
 * Render one evaluation metric value.
 *
 * Its own module rather than a second export from the page: the artifacts hold
 * numbers, integers, lists of case ids, nulls, and nested objects, each needing
 * a different rendering, and a page that exports a helper as well as a
 * component breaks React Fast Refresh.
 */
export function formatMetric(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(4)
  }
  if (Array.isArray(value))
    return value.length === 0 ? 'none' : value.join(', ')
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  if (typeof value === 'string') return value
  if (typeof value === 'boolean') return String(value)
  return JSON.stringify(value) ?? '—'
}
