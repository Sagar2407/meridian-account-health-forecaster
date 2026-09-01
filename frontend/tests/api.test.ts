import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchAccount,
  fetchAccounts,
  fetchHealth,
  fetchReviewCard,
  hasDecision,
  isForecast,
  submitReviewDecision,
  subscribeToRun,
} from '../src/api'
import { abstention, forecast, traceEvent, urlOf } from './fixtures'

const traceEventPayload = traceEvent('placeholder', 1)

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
      'Request failed with status 503',
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

describe('the request layer', () => {
  it('carries the API error code through, so a page can branch on it', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'REQUEST_BLOCKED',
          message: 'This request cannot be answered.',
          detail: { retry_after_seconds: 42 },
        }),
        { status: 422 },
      ),
    )

    await expect(fetchAccount('ACC-1042')).rejects.toMatchObject({
      code: 'REQUEST_BLOCKED',
      status: 422,
      detail: { retry_after_seconds: 42 },
    })
  })

  it('falls back to a generic code when the body is not the error contract', async () => {
    // A proxy or a crashed worker returns HTML. Inventing a code from the
    // status would be worse than admitting the failure is unclassified.
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('<html>502 Bad Gateway</html>', { status: 502 }),
    )

    await expect(fetchAccounts()).rejects.toMatchObject({
      code: 'INTERNAL_ERROR',
      status: 502,
    })
  })

  it('builds the account query from only the filters that were set', async () => {
    const seen: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      seen.push(urlOf(input))
      return Promise.resolve(
        new Response(
          JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 }),
          {
            status: 200,
          },
        ),
      )
    })

    await fetchAccounts({
      segment: 'Strategic',
      renewsWithinDays: 90,
      limit: 25,
    })

    expect(seen[0]).toContain('segment=Strategic')
    expect(seen[0]).toContain('renews_within_days=90')
    expect(seen[0]).toContain('limit=25')
    expect(seen[0]).not.toContain('region=')
    expect(seen[0]).not.toContain('offset=')
  })

  it('omits the query string entirely when nothing is filtered', async () => {
    const seen: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      seen.push(urlOf(input))
      return Promise.resolve(
        new Response(
          JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 }),
          {
            status: 200,
          },
        ),
      )
    })

    await fetchAccounts()

    expect(seen[0]).toMatch(/\/api\/accounts$/)
  })

  it('posts a reviewer decision as JSON', async () => {
    let body: string | undefined
    vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => {
      body = init?.body as string
      return Promise.resolve(
        new Response(JSON.stringify({ case: {}, regression: null }), {
          status: 200,
        }),
      )
    })

    await submitReviewDecision('CASE-1', {
      reviewer: 'a@b.test',
      action: 'approve',
      reason_code: 'agrees_with_evidence',
      note: '',
    })

    expect(JSON.parse(body ?? '{}')).toMatchObject({
      reviewer: 'a@b.test',
      action: 'approve',
    })
  })

  it('escapes an identifier rather than pasting it into the path', async () => {
    const seen: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      seen.push(urlOf(input))
      return Promise.resolve(new Response('{}', { status: 200 }))
    })

    await fetchReviewCard('CASE/../secret')

    expect(seen[0]).toContain('CASE%2F..%2Fsecret')
  })
})

describe('isForecast and hasDecision', () => {
  it('separates a forecast from an abstention by the field one cannot have', () => {
    expect(isForecast(forecast)).toBe(true)
    expect(isForecast(abstention)).toBe(false)
  })

  it('recognises a review card stored before decision cards existed', () => {
    expect(hasDecision({})).toBe(false)
    expect(hasDecision(forecast)).toBe(true)
  })
})

describe('subscribeToRun', () => {
  class FakeEventSource {
    static last: FakeEventSource | undefined
    closed = false
    onerror: (() => void) | null = null
    readonly listeners = new Map<
      string,
      (event: MessageEvent<string>) => void
    >()

    constructor(readonly url: string) {
      FakeEventSource.last = this
    }

    addEventListener(
      name: string,
      handler: (event: MessageEvent<string>) => void,
    ) {
      this.listeners.set(name, handler)
    }

    close() {
      this.closed = true
    }

    emit(name: string, data: string) {
      this.listeners.get(name)?.({ data } as MessageEvent<string>)
    }
  }

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('delivers each event and closes itself when the run finishes', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const events: string[] = []
    let finished = false

    subscribeToRun(
      'RUN-1',
      (event) => events.push(event.event),
      () => {
        finished = true
      },
    )

    const source = FakeEventSource.last!
    source.emit(
      'run_started',
      JSON.stringify({ ...traceEventPayload, event: 'run_started' }),
    )
    source.emit(
      'run_completed',
      JSON.stringify({ ...traceEventPayload, event: 'run_completed' }),
    )
    source.emit(
      'run_finished',
      JSON.stringify({ run_id: 'RUN-1', status: 'completed' }),
    )

    expect(events).toEqual(['run_started', 'run_completed'])
    expect(finished).toBe(true)
    expect(source.closed).toBe(true)
  })

  it('drops a malformed frame instead of breaking the timeline', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const events: string[] = []

    subscribeToRun(
      'RUN-1',
      (event) => events.push(event.event),
      () => {},
    )

    FakeEventSource.last!.emit('plan_created', 'not json at all')

    expect(events).toEqual([])
  })

  it('reports an error and closes when the stream drops', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    let errored = false

    subscribeToRun(
      'RUN-1',
      () => {},
      () => {},
      () => {
        errored = true
      },
    )

    FakeEventSource.last!.onerror?.()

    expect(errored).toBe(true)
    expect(FakeEventSource.last!.closed).toBe(true)
  })

  it('closes the connection when the caller unsubscribes', () => {
    vi.stubGlobal('EventSource', FakeEventSource)

    const unsubscribe = subscribeToRun(
      'RUN-1',
      () => {},
      () => {},
    )
    unsubscribe()

    expect(FakeEventSource.last!.closed).toBe(true)
  })
})
