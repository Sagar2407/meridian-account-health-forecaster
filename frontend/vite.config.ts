import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Vite refuses requests whose Host header it does not recognise, which is
    // the right default. The end-to-end browser runs in its own container and
    // reaches this server by its compose service name, so that name is allowed
    // explicitly rather than by disabling the check.
    allowedHosts: ['localhost', 'frontend'],
  },
  test: {
    environment: 'jsdom',
    setupFiles: './tests/setup.ts',
    // Vitest's default glob matches `*.spec.ts` anywhere, which would pull in
    // the Playwright journeys: they need a browser and a running stack, and
    // under jsdom they fail on the first import. `make e2e` runs those.
    include: ['tests/**/*.{test,spec}.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary'],
      include: ['src/**/*.{ts,tsx}'],
      // `main.tsx` is the browser entry point: three lines that mount the app
      // into a DOM node that does not exist under jsdom. Testing it would mean
      // testing `createRoot`, so it is excluded rather than covered by a test
      // that asserts nothing.
      exclude: ['src/**/*.d.ts', 'src/main.tsx'],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 80,
        statements: 80,
      },
    },
  },
})
