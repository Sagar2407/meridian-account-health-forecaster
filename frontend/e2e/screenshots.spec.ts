/**
 * Capture the screenshots the README and the final report use.
 *
 * A Playwright spec rather than a manual pass, so the images are always of the
 * current build and always at the same widths. It is excluded from the normal
 * run by its own project name -- `make screenshots` selects it -- because
 * writing files is not something a test gate should do.
 */

import { expect, test } from '@playwright/test'

const OUTPUT = '../docs/screenshots'

// Desktop only, and only under `PLAYWRIGHT_SCREENSHOTS=1`: the viewport and
// the project selection both live in `playwright.config.ts`.
//
// `fullPage` is deliberately not used. On a long table it produces a
// several-megabyte strip nobody reads past the first screen of, and these
// images are committed for the README.
test.describe('screenshots', () => {
  test('portfolio', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('table')).toBeVisible()
    await page.screenshot({ path: `${OUTPUT}/portfolio.png` })
  })

  test('account', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('row').nth(1).getByRole('link').click()
    await expect(
      page.getByRole('heading', { name: 'Usage trajectory' }),
    ).toBeVisible()
    await page.screenshot({ path: `${OUTPUT}/account.png` })
  })

  test('assessment result and evidence drawer', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('row').nth(1).getByRole('link').click()
    await page.getByRole('button', { name: 'Assess this account' }).click()
    await expect(
      page.getByRole('heading', { name: 'Assessment result' }),
    ).toBeVisible({ timeout: 60_000 })
    await page.screenshot({ path: `${OUTPUT}/decision.png` })

    await page.locator('.citation').first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.screenshot({ path: `${OUTPUT}/evidence-drawer.png` })
  })

  test('review queue', async ({ page }) => {
    await page.goto('/review')
    await expect(
      page.getByRole('heading', { name: 'Review queue' }),
    ).toBeVisible()
    const firstCase = page.locator('.queue-item').first()
    if ((await firstCase.count()) > 0) {
      await firstCase.click()
      await expect(
        page.getByRole('heading', { name: 'Your decision' }),
      ).toBeVisible()
    }
    await page.screenshot({
      path: `${OUTPUT}/review-queue.png`,
      fullPage: true,
    })
  })

  test('evaluation', async ({ page }) => {
    await page.goto('/evaluation')
    await expect(
      page.getByRole('heading', { name: 'Evaluation' }),
    ).toBeVisible()
    await page.screenshot({ path: `${OUTPUT}/evaluation.png` })
  })
})
