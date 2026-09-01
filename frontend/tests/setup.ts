/**
 * Test environment setup.
 *
 * The explicit `cleanup` matters. Testing Library only registers its own
 * automatic cleanup when a test runner exposes `afterEach` as a global, and
 * this project runs Vitest without `globals: true`. Without this hook every
 * render in a file accumulates in the same document, so the first test in a
 * file passes and the rest fail with "found multiple elements" — or worse,
 * pass against the previous test's markup.
 */

import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})
