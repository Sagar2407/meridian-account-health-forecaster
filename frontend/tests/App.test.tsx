import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../src/App'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('App', () => {
  it('reports the healthy foundation and its safety boundary', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          status: 'ok',
          service: 'meridian-api',
          version: '0.1.0',
          environment: 'test',
          data_mode: 'synthetic',
        }),
        { status: 200 },
      ),
    )

    render(<App />)

    expect(
      screen.getByRole('heading', { name: 'Meridian' }),
    ).toBeInTheDocument()
    expect(await screen.findByText('Foundation online')).toBeInTheDocument()
    expect(screen.getByText(/meridian-api · v0.1.0 · test/)).toBeInTheDocument()
    expect(screen.getByText('Synthetic data only')).toBeInTheDocument()
  })

  it('shows a useful offline state when the API cannot be reached', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(
      new Error('connection refused'),
    )

    render(<App />)

    expect(await screen.findByText('API unavailable')).toBeInTheDocument()
    expect(
      screen.getByText('Start the backend to complete the health check.'),
    ).toBeInTheDocument()
  })

  it('aborts the in-flight health check when it unmounts', () => {
    let healthSignal: AbortSignal | undefined
    vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => {
      healthSignal = init?.signal ?? undefined
      return new Promise<Response>(() => {})
    })

    const { unmount } = render(<App />)
    expect(screen.getByText('Checking API')).toBeInTheDocument()
    expect(healthSignal?.aborted).toBe(false)

    unmount()

    expect(healthSignal?.aborted).toBe(true)
  })
})
