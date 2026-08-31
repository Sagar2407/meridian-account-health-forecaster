import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchHealth } from '../src/api'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
})

describe('fetchHealth', () => {
  it('returns the typed health payload', async () => {
    const payload = {
      status: 'ok' as const,
      service: 'meridian-api',
      version: '0.1.0',
      environment: 'test',
      data_mode: 'synthetic' as const,
    }
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(payload), { status: 200 }),
    )

    await expect(fetchHealth()).resolves.toEqual(payload)
  })

  it('rejects a non-success response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(null, { status: 503 }),
    )

    await expect(fetchHealth()).rejects.toThrow(
      'Health request failed with status 503',
    )
  })

  it('targets the configured API base URL', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://meridian.example.test')
    vi.resetModules()
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 200 }))

    const { fetchHealth: fetchConfiguredHealth } = await import('../src/api')
    await fetchConfiguredHealth()

    expect(fetchSpy).toHaveBeenCalledWith(
      'https://meridian.example.test/api/health',
      expect.anything(),
    )
  })

  it('falls back to the local API when no base URL is configured', async () => {
    vi.stubEnv('VITE_API_BASE_URL', undefined)
    vi.resetModules()
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 200 }))

    const { fetchHealth: fetchDefaultHealth } = await import('../src/api')
    await fetchDefaultHealth()

    expect(fetchSpy).toHaveBeenCalledWith(
      'http://localhost:8000/api/health',
      expect.anything(),
    )
  })
})
