/**
 * Visual regression over the pages whose content does not move (section 20.7).
 *
 * The screenshots in `docs/screenshots/` are a deliverable: they are captured
 * on request and nothing fails if the layout shifts. This is the gate that was
 * missing. It compares rendered pixels against committed baselines, so an
 * accidental change to a shared style -- a token, a grid, a spacing scale --
 * fails here instead of being noticed in a screenshot months later.
 *
 * Only pages with fixed content are covered, and that restriction is the whole
 * design. The review queue grows every time an assessment runs and the
 * evaluation page renders whatever the last evaluation wrote, so a baseline of
 * either would fail on correct changes -- and a suite that cries wolf gets
 * ignored, which is worse than not having it. What is left is the layout, the
 * type scale, and the colour system, which is what this is for.
 *
 * The captures are the viewport rather than the full page. A full-page capture
 * of a two-hundred-row table is a megabyte of PNG that changes whenever the
 * data does, which buys length rather than coverage; the viewport holds the
 * shared layout, type scale, and colour tokens, which is what a regression here
 * would actually be.
 *
 * Baselines are per-project and per-platform. They are generated inside the
 * pinned Playwright image the suite always runs in, so they are reproducible;
 * regenerate them with `./scripts/run_e2e.sh --update-snapshots` after an
 * intended visual change.
 */

import { expect, test } from '@playwright/test'

/** Rounding in font rasterisation should not fail a build. */
const TOLERANCE = { maxDiffPixelRatio: 0.01, animations: 'disabled' } as const

test('the portfolio layout is unchanged', async ({ page }) => {
  await page.goto('/')
  // The table, not just the shell: a baseline captured mid-load would encode a
  // spinner and pass forever afterwards without checking anything.
  await expect(page.getByRole('table')).toBeVisible()
  await expect(page.getByRole('row').nth(1)).toBeVisible()

  await expect(page).toHaveScreenshot('portfolio.png', TOLERANCE)
})

test('a curated demo run is unchanged', async ({ page }) => {
  // Read from `config/demo_cache.json`, which is committed, so this page is
  // the same on every machine and every run.
  await page.goto('/demo/conflict')
  await expect(page.getByRole('heading').first()).toBeVisible()
  await expect(page.locator('main')).toContainText(/recorded|cached/i)

  await expect(page).toHaveScreenshot('demo-conflict.png', TOLERANCE)
})

test('the not-found page is unchanged', async ({ page }) => {
  await page.goto('/nope')
  await expect(page.locator('main')).toContainText(/not found|no such/i)

  await expect(page).toHaveScreenshot('not-found.png', TOLERANCE)
})
