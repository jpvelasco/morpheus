import { fetchOverview, parseOverview } from '../src/api'

function validOverview() {
  return {
    observed_at: '2026-07-15T12:00:00+00:00',
    inference: {
      state: 'ready',
      reason_code: 'inference_models_ready',
      summary: 'ready',
      observed_at: '2026-07-15T12:00:00+00:00',
      duration_ms: 2,
      source: 'openai_models',
      expires_at: '2026-07-15T12:00:30+00:00',
      next_action: null,
    },
    models: [{ root: null, aliases: ['model-a'], context_window: null }],
    capabilities: { core: { state: 'available', blockers: [] } },
    host: { status: 'unavailable', reason: 'agent_offline' },
    diagnostics: {
      status: 'degraded',
      observed_at: '2026-07-15T12:00:00+00:00',
      checks: [{
        code: 'runtime_agent',
        status: 'unavailable',
        reason_code: 'runtime_agent_unreachable',
        summary: 'Runtime agent is unavailable',
        observed_at: '2026-07-15T12:00:00+00:00',
        freshness: 'current',
        next_action: 'Start the runtime agent',
      }],
    },
    external_controls: [],
  }
}

test('parses nullable model and evidence fields', () => {
  const payload = validOverview()
  payload.inference.duration_ms = null as unknown as number
  const result = parseOverview(payload)
  expect(result.models[0]).toEqual({ root: null, aliases: ['model-a'], context_window: null })
  expect(result.inference.duration_ms).toBe(0)
  expect(result.inference.next_action).toBeNull()
})

test.each([
  [null, 'incompatible response'],
  [[], 'incompatible response'],
  [{ ...validOverview(), observed_at: 12 }, 'overview timestamp'],
  [{ ...validOverview(), inference: { ...validOverview().inference, state: 'broken' } }, 'health state'],
  [{ ...validOverview(), inference: { ...validOverview().inference, summary: 2 } }, 'health summary'],
  [{ ...validOverview(), inference: { ...validOverview().inference, duration_ms: Number.NaN } }, 'probe duration'],
  [{ ...validOverview(), inference: { ...validOverview().inference, next_action: 7 } }, 'next action'],
  [{ ...validOverview(), models: {} }, 'model list'],
  [{ ...validOverview(), models: [{ root: null, aliases: {}, context_window: null }] }, 'model aliases'],
  [{ ...validOverview(), models: [{ root: null, aliases: [3], context_window: null }] }, 'model aliases'],
  [{ ...validOverview(), models: [{ root: 2, aliases: ['a'], context_window: null }] }, 'root model'],
  [{ ...validOverview(), models: [{ root: null, aliases: ['a'], context_window: 'large' }] }, 'context window'],
  [{ ...validOverview(), capabilities: [] }, 'incompatible response'],
  [{ ...validOverview(), capabilities: { core: null } }, 'incompatible response'],
  [{ ...validOverview(), capabilities: { core: { state: 'broken', blockers: [] } } }, 'capability state'],
  [{ ...validOverview(), capabilities: { core: { state: 'blocked', blockers: [2] } } }, 'capability blockers'],
  [{ ...validOverview(), host: { status: 'invented' } }, 'host status'],
])('rejects incompatible API shape %#', (payload, message) => {
  expect(() => parseOverview(payload)).toThrow(message)
})

test('accepts available host telemetry and a non-null next action', () => {
  const base = validOverview()
  const payload = {
    ...base,
    inference: { ...base.inference, next_action: 'Check runtime agent' },
    host: {
      status: 'available',
      gpu: { memory_total_mib: 32607, memory_used_mib: 12000, utilization_percent: 7, temperature_c: 42 },
    },
  }
  expect(parseOverview(payload).host.status).toBe('available')
  expect(parseOverview(payload).inference.next_action).toBe('Check runtime agent')
})

test('fetch sends bearer authentication and parses a successful response', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(validOverview()), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  await expect(fetchOverview('secret-token')).resolves.toMatchObject({ observed_at: validOverview().observed_at })
  expect(fetchMock).toHaveBeenCalledWith(
    'http://127.0.0.1:7400/api/v1/overview',
    expect.objectContaining({ headers: { Authorization: 'Bearer secret-token' } }),
  )
})

test.each([
  [401, 'Authentication failed'],
  [503, 'HTTP 503'],
])('fetch maps HTTP %i to a safe error', async (status, message) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status })))
  await expect(fetchOverview('token')).rejects.toThrow(message)
})
