import {
  createSession,
  destroySession,
  fetchControls,
  fetchNavigation,
  fetchOverview,
  parseControls,
  parseNavigation,
  parseOverview,
} from '../src/api'

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
  [{ ...validOverview(), diagnostics: { ...validOverview().diagnostics, status: 'broken' } }, 'diagnostics status'],
  [{ ...validOverview(), diagnostics: { ...validOverview().diagnostics, observed_at: 3 } }, 'diagnostics timestamp'],
  [{ ...validOverview(), diagnostics: { ...validOverview().diagnostics, checks: 'nope' } }, 'diagnostic checks'],
  [{ ...validOverview(), diagnostics: { ...validOverview().diagnostics, checks: [{ ...validOverview().diagnostics.checks[0], status: 'weird' }] } }, 'diagnostic check status'],
  [{ ...validOverview(), diagnostics: { ...validOverview().diagnostics, checks: [{ ...validOverview().diagnostics.checks[0], freshness: 'odd' }] } }, 'diagnostic freshness'],
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

test('fetch uses an HttpOnly cookie session and parses a successful response', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(validOverview()), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  await expect(fetchOverview()).resolves.toMatchObject({ observed_at: validOverview().observed_at })
  expect(fetchMock).toHaveBeenCalledWith(
    'http://127.0.0.1:7400/api/v1/overview',
    expect.objectContaining({ credentials: 'include' }),
  )
})

test('session setup sends the access key once and logout sends the CSRF token', async () => {
  document.cookie = 'morpheus_csrf=csrf-token; path=/'
  const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)

  await createSession('secret-token')
  await destroySession()

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    'http://127.0.0.1:7400/api/v1/session',
    expect.objectContaining({
      method: 'POST', credentials: 'include', body: JSON.stringify({ api_key: 'secret-token' }),
    }),
  )
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    'http://127.0.0.1:7400/api/v1/session',
    expect.objectContaining({
      method: 'DELETE', credentials: 'include', headers: { 'X-CSRF-Token': 'csrf-token' },
    }),
  )
})

test.each([
  [401, 'Authentication failed'],
  [503, 'HTTP 503'],
])('fetch maps HTTP %i to a safe error', async (status, message) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status })))
  await expect(fetchOverview()).rejects.toThrow(message)
})

function validNavigation() {
  return {
    schema_version: 1,
    observed_at: '2026-07-15T12:00:00+00:00',
    workspaces: [
      { id: 'overview', label: 'Overview', state: 'ready', query_model: { schema: 'overview', version: 1 } },
      { id: 'engines', label: 'Engines', state: 'empty', query_model: null },
    ],
  }
}

function validControls() {
  return {
    schema_version: 1,
    observed_at: '2026-07-15T12:00:00+00:00',
    core_ready: true,
    controls: [
      { control: 'core', state: 'usable', configured: true, running: true, healthy: true, usable: true, blockers: [] },
    ],
  }
}

test('parses the navigation manifest with nullable query models', () => {
  const result = parseNavigation(validNavigation())
  expect(result.schema_version).toBe(1)
  expect(result.workspaces[0]).toEqual({
    id: 'overview', label: 'Overview', state: 'ready', query_model: { schema: 'overview', version: 1 },
  })
  expect(result.workspaces[1]?.query_model).toBeNull()
})

test.each([
  [null, 'incompatible response'],
  [[], 'incompatible response'],
  [{ ...validNavigation(), schema_version: '1' }, 'navigation schema version'],
  [{ ...validNavigation(), observed_at: 3 }, 'navigation timestamp'],
  [{ ...validNavigation(), workspaces: {} }, 'workspace list'],
  [{ ...validNavigation(), workspaces: [{ id: 'x', label: 'X', state: 'broken', query_model: null }] }, 'workspace state'],
  [{ ...validNavigation(), workspaces: [{ id: 2, label: 'X', state: 'ready', query_model: null }] }, 'workspace id'],
  [{ ...validNavigation(), workspaces: [{ id: 'x', label: 'X', state: 'ready', query_model: { schema: 3, version: 1 } }] }, 'query model schema'],
  [{ ...validNavigation(), workspaces: [{ id: 'x', label: 'X', state: 'ready', query_model: { schema: 's', version: '1' } }] }, 'query model version'],
])('rejects incompatible navigation shape %#', (payload, message) => {
  expect(() => parseNavigation(payload)).toThrow(message)
})

test('parses the controls report with boolean ladder flags', () => {
  const result = parseControls(validControls())
  expect(result.core_ready).toBe(true)
  expect(result.controls[0]).toEqual(validControls().controls[0])
})

test.each([
  [null, 'incompatible response'],
  [[], 'incompatible response'],
  [{ ...validControls(), schema_version: '1' }, 'controls schema version'],
  [{ ...validControls(), observed_at: 3 }, 'controls timestamp'],
  [{ ...validControls(), core_ready: 'yes' }, 'core readiness'],
  [{ ...validControls(), controls: {} }, 'control list'],
  [{ ...validControls(), controls: [{ control: 'core', state: 'broken', configured: true, running: true, healthy: true, usable: true, blockers: [] }] }, 'control state'],
  [{ ...validControls(), controls: [{ control: 7, state: 'usable', configured: true, running: true, healthy: true, usable: true, blockers: [] }] }, 'control name'],
  [{ ...validControls(), controls: [{ control: 'core', state: 'usable', configured: 'yes', running: true, healthy: true, usable: true, blockers: [] }] }, 'control configured'],
  [{ ...validControls(), controls: [{ control: 'core', state: 'usable', configured: true, running: true, healthy: true, usable: true, blockers: [2] }] }, 'control blockers'],
])('rejects incompatible controls shape %#', (payload, message) => {
  expect(() => parseControls(payload)).toThrow(message)
})

test('fetchNavigation and fetchControls use the session cookie', async () => {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    const payload = url.includes('/operations/navigation') ? validNavigation() : validControls()
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }))
  })
  vi.stubGlobal('fetch', fetchMock)
  await expect(fetchNavigation()).resolves.toMatchObject({ schema_version: 1 })
  await expect(fetchControls()).resolves.toMatchObject({ core_ready: true })
  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    'http://127.0.0.1:7400/api/v1/operations/navigation',
    expect.objectContaining({ credentials: 'include' }),
  )
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    'http://127.0.0.1:7400/api/v1/operations/controls',
    expect.objectContaining({ credentials: 'include' }),
  )
})
