/**
 * An automated WCAG audit of every page (plan section 23.5).
 *
 * The journeys already assert the structural properties a person notices
 * first: a skip link, one `h1` and one `main` per page, accessible names on
 * figures, and no horizontal scroll. Those were written by hand, which means
 * they cover what was thought of. This runs axe-core instead, which covers a
 * published rule set, and fails on any violation of WCAG 2.0/2.1 A or AA.
 *
 * It is a separate spec because it is a different kind of check: a journey
 * asserts that a feature works, and this asserts that the page it works on is
 * usable by someone who is not looking at it.
 */

import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

/** The WCAG levels this project holds itself to. */
const STANDARD = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

/**
 * Every route, with the state each needs to be worth auditing.
 *
 * A page audited before its data arrives is an audit of a spinner, so each
 * entry names something that must be on screen first.
 */
const PAGES: { name: string; path: string; ready: RegExp }[] = [
  { name: 'portfolio', path: '/', ready: /Portfolio/i },
  { name: 'review queue', path: '/review', ready: /review/i },
  { name: 'evaluation', path: '/evaluation', ready: /evaluation/i },
  { name: 'demo run', path: '/demo/conflict', ready: /conflict|recorded/i },
  { name: 'not found', path: '/nope', ready: /not found|no such/i },
]

for (const page_ of PAGES) {
  test(`${page_.name} has no WCAG A or AA violations`, async ({ page }) => {
    await page.goto(page_.path)
    await expect(page.getByRole('heading').first()).toBeVisible()
    await expect(page.locator('main')).toContainText(page_.ready)

    const results = await new AxeBuilder({ page }).withTags(STANDARD).analyze()

    // The default failure is a bare count. Naming the rule and the element is
    // the difference between a report someone can act on and one they have to
    // reproduce first.
    const summary = results.violations.map(
      (violation) =>
        `${violation.id} (${violation.impact}): ${violation.help}\n` +
        violation.nodes
          .map((node) => `    ${node.target.join(' ')}`)
          .join('\n'),
    )
    expect(summary, `axe violations on ${page_.path}`).toEqual([])
  })
}

test('an account page has no WCAG A or AA violations', async ({ page }) => {
  // Reached by clicking rather than by a guessed id, so the audit covers the
  // page as a person arrives at it, with a real account loaded.
  await page.goto('/')
  await page.getByRole('row').nth(1).getByRole('link').click()
  await expect(
    page.getByRole('heading', { name: 'Usage trajectory' }),
  ).toBeVisible()

  const results = await new AxeBuilder({ page }).withTags(STANDARD).analyze()
  const summary = results.violations.map(
    (violation) =>
      `${violation.id} (${violation.impact}): ${violation.help}\n` +
      violation.nodes.map((node) => `    ${node.target.join(' ')}`).join('\n'),
  )
  expect(summary, 'axe violations on the account page').toEqual([])
})
