/**
 * End-to-end configuration (plan sections 9 and 23.5).
 *
 * The tests run against the real stack -- the compose backend with the real
 * dataset, the real graph, and the real frontend build -- because the exit gate
 * is about user journeys, and a journey against a mocked API would prove only
 * that the mock matches the test.
 *
 * One browser and one worker. The backend runs assessments through a bounded
 * thread pool, and two suites racing for it would make failures depend on
 * timing rather than on behaviour.
 */

import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173'

export default defineConfig({
  testDir: './e2e',
  // A full assessment runs the whole graph: two evidence lanes, retrieval, and
  // adjudication. Seconds, not milliseconds.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['json', { outputFile: 'e2e-results.json' }]],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  // Two kinds of run, kept apart by project rather than by a flag inside the
  // specs. `PLAYWRIGHT_SCREENSHOTS=1` selects the capture project; anything
  // else runs the journeys. A gate should never write files, and a capture
  // should never run in both viewports and overwrite its own desktop images
  // with narrow ones -- which is exactly what happened the first time.
  projects: process.env.PLAYWRIGHT_SCREENSHOTS
    ? [
        {
          name: 'screenshots',
          testMatch: /screenshots\.spec\.ts/,
          use: {
            ...devices['Desktop Chrome'],
            viewport: { width: 1440, height: 900 },
          },
        },
      ]
    : [
        {
          name: 'chromium',
          testIgnore: /screenshots\.spec\.ts/,
          use: { ...devices['Desktop Chrome'] },
        },
        // Section 20.7 asks for responsive behaviour at desktop *and* tablet
        // widths, so the tablet viewport is a project rather than a note.
        {
          name: 'tablet',
          testIgnore: /screenshots\.spec\.ts/,
          use: { ...devices['iPad Pro 11'] },
        },
      ],
})
