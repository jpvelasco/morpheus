import {
  createSession,
  destroySession,
  fetchAnalytics,
  fetchBenchmarks,
  fetchControls,
  fetchEvents,
  fetchMetricsTrend,
  fetchNavigation,
  fetchOverview,
  parseAnalyticsReport,
  parseBenchmarksReport,
  parseControls,
  parseEventsReport,
  parseMetricsTrend,
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

function validMetricsTrend() {
  return {
    schema_version: 1,
    observed_at: '2026-08-01T12:00:00+00:00',
    signal: 'gpu_cache_usage',
    unit: 'percent',
    freshness: { state: 'stale', latest_observed_at: '2026-08-01T08:10:00+00:00', age_seconds: 13800 },
    sources: [
      { source: 'engine', state: 'unavailable', reason: 'metrics_url_not_configured' },
      { source: 'host', state: 'available', reason: null },
    ],
    buckets: [
      { start: '2026-08-01T08:00:00+00:00', end: '2026-08-01T09:00:00+00:00', count: 3, min: 10, max: 30, mean: 20, p50: 20, p95: 28 },
    ],
    gaps: [{ start: '2026-08-01T09:00:00+00:00', end: '2026-08-01T11:00:00+00:00' }],
    sample_count: 3,
  }
}

test('parses metrics trend with units, freshness, sources, and gaps', () => {
  const result = parseMetricsTrend(validMetricsTrend())
  expect(result.schema_version).toBe(1)
  expect(result.unit).toBe('percent')
  expect(result.freshness).toEqual({ state: 'stale', latest_observed_at: '2026-08-01T08:10:00+00:00', age_seconds: 13800 })
  expect(result.sources[1]).toEqual({ source: 'host', state: 'available', reason: null })
  expect(result.buckets[0]).toMatchObject({ count: 3, min: 10, max: 30, mean: 20 })
  expect(result.gaps).toEqual([{ start: '2026-08-01T09:00:00+00:00', end: '2026-08-01T11:00:00+00:00' }])
  expect(result.sample_count).toBe(3)
})

test.each([
  [null, 'incompatible response'],
  [[], 'incompatible response'],
  [{ ...validMetricsTrend(), unit: 3 }, 'metrics unit'],
  [{ ...validMetricsTrend(), freshness: { state: 'weird', latest_observed_at: null, age_seconds: null } }, 'freshness state'],
  [{ ...validMetricsTrend(), sources: [{ source: 'engine', state: 'broken', reason: null }] }, 'source state'],
  [{ ...validMetricsTrend(), buckets: [{ start: 'a', end: 'b', count: '3', min: 1, max: 2, mean: 1, p50: 1, p95: 2 }] }, 'bucket count'],
  [{ ...validMetricsTrend(), gaps: [{ start: 3, end: 'x' }] }, 'gap start'],
  [{ ...validMetricsTrend(), sample_count: '3' }, 'sample count'],
])('rejects incompatible metrics trend shape %#', (payload, message) => {
  expect(() => parseMetricsTrend(payload)).toThrow(message)
})

function validEventsReport() {
  return {
    schema_version: 1,
    observed_at: '2026-08-01T12:00:00+00:00',
    count: 2,
    events: [
      { recorded_at: '2026-08-01T11:00:00+00:00', source: 'api', severity: 'info', message: 'heartbeat', correlation_id: null, deployment_id: null, campaign_id: null },
      { recorded_at: '2026-08-01T10:00:00+00:00', source: 'engine', severity: 'warn', message: 'latency spike', correlation_id: 'corr-9', deployment_id: null, campaign_id: null },
    ],
  }
}

test('parses the redacted events report', () => {
  const result = parseEventsReport(validEventsReport())
  expect(result.count).toBe(2)
  expect(result.events[1]).toMatchObject({ severity: 'warn', correlation_id: 'corr-9' })
})

test.each([
  [{ ...validEventsReport(), events: [{ ...validEventsReport().events[0], severity: 'fatal' }] }, 'event severity'],
  [{ ...validEventsReport(), events: [{ ...validEventsReport().events[0], message: 3 }] }, 'event message'],
  [{ ...validEventsReport(), events: [{ ...validEventsReport().events[0], recorded_at: 3 }] }, 'event timestamp'],
  [{ ...validEventsReport(), count: '2' }, 'event count'],
])('rejects incompatible events shape %#', (payload, message) => {
  expect(() => parseEventsReport(payload)).toThrow(message)
})

function validBenchmarks() {
  return {
    schema_version: 1,
    observed_at: '2026-08-01T12:00:00+00:00',
    count: 1,
    runs: [{
      run_id: 'run-1',
      declaration: { name: 'contract-campaign' },
      identity: { model_id: 'qwen2.5-7b-instruct', engine_id: 'llama.cpp', quantization: 'q8_0' },
      started_at: '2026-08-01T12:00:00+00:00',
      ended_at: '2026-08-01T12:02:00+00:00',
      status: 'completed',
      errors: [],
      checkpoint: [],
    }],
  }
}

test('parses benchmark run history', () => {
  const result = parseBenchmarksReport(validBenchmarks())
  expect(result.count).toBe(1)
  expect(result.runs[0]).toMatchObject({ run_id: 'run-1', status: 'completed' })
  expect(result.runs[0]?.identity.model_id).toBe('qwen2.5-7b-instruct')
})

test.each([
  [{ ...validBenchmarks(), runs: [{ ...validBenchmarks().runs[0], status: 2 }] }, 'run status'],
  [{ ...validBenchmarks(), runs: [{ ...validBenchmarks().runs[0], errors: 'nope' }] }, 'run errors'],
  [{ ...validBenchmarks(), runs: [{ ...validBenchmarks().runs[0], started_at: 3 }] }, 'run start'],
  [{ ...validBenchmarks(), count: '1' }, 'run count'],
])('rejects incompatible benchmarks shape %#', (payload, message) => {
  expect(() => parseBenchmarksReport(payload)).toThrow(message)
})

function validAnalytics() {
  return {
    schema_version: 1,
    observed_at: '2026-08-01T12:00:00+00:00',
    usage: { requests: 120, successes: 118, cancellations: 1, errors: 1, prompt_tokens: 9000, completion_tokens: 12000, window_days: 30 },
    scorecards: [{ run_id: 'run-1', model_id: 'm', engine_id: 'e', quantization: 'q8_0', statistic: 'p50', sample_count: 4, ttft_seconds: 0.2, tokens_per_second: 11.5 }],
    comparisons: [{
      baseline_run_id: 'run-1', candidate_run_id: 'run-2', classification: 'COMPARABLE', classification_note: '',
      metric: 'ttft_seconds', statistic: 'p50',
      baseline: { value: 0.2, sample_count: 4, run_variation: 0.05 },
      candidate: { value: 0.3, sample_count: 4, run_variation: 0.06 },
      percent_change: 50,
    }],
    regressions: [{ metric: 'ttft_seconds', baseline_value: 0.2, candidate_value: 0.3, threshold_pct: 5, change_pct: 50 }],
  }
}

test('parses analytics usage, scorecards, comparisons, and regressions', () => {
  const result = parseAnalyticsReport(validAnalytics())
  expect(result.usage).toMatchObject({ requests: 120, errors: 1 })
  expect(result.scorecards[0]?.ttft_seconds).toBe(0.2)
  expect(result.comparisons[0]?.classification).toBe('COMPARABLE')
  expect(result.regressions[0]).toMatchObject({ metric: 'ttft_seconds', change_pct: 50 })
})

test.each([
  [{ ...validAnalytics(), usage: { ...validAnalytics().usage, requests: '120' } }, 'usage requests'],
  [{ ...validAnalytics(), scorecards: [{ ...validAnalytics().scorecards[0], sample_count: '4' }] }, 'scorecard samples'],
  [{ ...validAnalytics(), comparisons: [{ ...validAnalytics().comparisons[0], percent_change: '50' }] }, 'percent change'],
  [{ ...validAnalytics(), comparisons: [{ ...validAnalytics().comparisons[0], baseline: { value: '0.2', sample_count: 4, run_variation: 0.05 } }] }, 'baseline value'],
  [{ ...validAnalytics(), regressions: [{ ...validAnalytics().regressions[0], change_pct: '50' }] }, 'regression change'],
])('rejects incompatible analytics shape %#', (payload, message) => {
  expect(() => parseAnalyticsReport(payload)).toThrow(message)
})

test('data fetchers pass query parameters and use the session cookie', async () => {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    const payload = url.includes('/operations/metrics') ? validMetricsTrend()
      : url.includes('/operations/events') ? validEventsReport()
      : url.includes('/operations/benchmarks') ? validBenchmarks()
      : validAnalytics()
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }))
  })
  vi.stubGlobal('fetch', fetchMock)
  await expect(fetchMetricsTrend(new AbortController().signal, 'gpu_cache_usage')).resolves.toMatchObject({ signal: 'gpu_cache_usage' })
  await expect(fetchEvents()).resolves.toMatchObject({ count: 2 })
  await expect(fetchBenchmarks()).resolves.toMatchObject({ count: 1 })
  await expect(fetchAnalytics()).resolves.toMatchObject({ schema_version: 1 })
  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    'http://127.0.0.1:7400/api/v1/operations/metrics?signal=gpu_cache_usage&window_seconds=3600&hours=6',
    expect.objectContaining({ credentials: 'include' }),
  )
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    'http://127.0.0.1:7400/api/v1/operations/events?limit=200',
    expect.objectContaining({ credentials: 'include' }),
  )
  expect(fetchMock).toHaveBeenNthCalledWith(
    3,
    'http://127.0.0.1:7400/api/v1/operations/benchmarks?limit=20',
    expect.objectContaining({ credentials: 'include' }),
  )
  expect(fetchMock).toHaveBeenNthCalledWith(
    4,
    'http://127.0.0.1:7400/api/v1/operations/analytics',
    expect.objectContaining({ credentials: 'include' }),
  )
})
