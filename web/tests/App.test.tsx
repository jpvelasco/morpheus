import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import App from '../src/App'


// MORPHEUS_OWNED_REQUIREMENTS: ["PERF-003", "UI-005"]
const overview = {
  observed_at: '2026-07-15T12:00:00+00:00',
  inference: {
    state: 'ready',
    reason_code: 'inference_models_ready',
    summary: 'Inference API returned one or more served models',
    observed_at: '2026-07-15T12:00:00+00:00',
    duration_ms: 2.5,
    source: 'openai_models',
    expires_at: '2099-07-15T12:00:30+00:00',
    next_action: null,
  },
  models: [{ root: 'nvidia/Qwen3.6-27B-NVFP4', aliases: ['qwen36-27b-nvfp4'], context_window: 131072 }],
  capabilities: {
    core: { state: 'available', blockers: [] },
    search: { state: 'disabled', blockers: [] },
  },
  host: { status: 'unavailable', reason: 'runtime_agent_not_configured' },
  diagnostics: {
    status: 'degraded',
    observed_at: '2026-07-15T12:00:00+00:00',
    checks: [{
      code: 'network_endpoint',
      status: 'pass',
      reason_code: 'inference_models_ready',
      summary: 'Inference API returned one or more served models',
      observed_at: '2026-07-15T12:00:00+00:00',
      freshness: 'current',
      next_action: null,
    }],
  },
  external_controls: [],
}

const navigation = {
  schema_version: 1,
  observed_at: '2026-07-15T12:00:00+00:00',
  workspaces: [
    { id: 'overview', label: 'Overview', state: 'ready', query_model: { schema: 'overview', version: 1 } },
    { id: 'hardware', label: 'Hardware', state: 'unavailable', query_model: { schema: 'host', version: 1 } },
    { id: 'models', label: 'Models', state: 'ready', query_model: { schema: 'models', version: 1 } },
    { id: 'engines', label: 'Engines', state: 'empty', query_model: null },
    { id: 'runtime', label: 'Runtime', state: 'unavailable', query_model: { schema: 'runtime', version: 1 } },
    { id: 'benchmarks', label: 'Benchmarks', state: 'empty', query_model: null },
    { id: 'analytics', label: 'Analytics', state: 'empty', query_model: null },
    { id: 'logs_events', label: 'Logs & Events', state: 'empty', query_model: null },
    { id: 'diagnostics', label: 'Diagnostics', state: 'ready', query_model: { schema: 'diagnostics', version: 1 } },
    { id: 'settings', label: 'Settings', state: 'empty', query_model: null },
    { id: 'recovery', label: 'Recovery', state: 'empty', query_model: null },
  ],
}

const controls = {
  schema_version: 1,
  observed_at: '2026-07-15T12:00:00+00:00',
  core_ready: true,
  controls: [
    { control: 'core', state: 'usable', configured: true, running: true, healthy: true, usable: true, blockers: [] },
    { control: 'search', state: 'configured', configured: false, running: false, healthy: false, usable: false, blockers: [] },
  ],
}

function validSettings() {
  return {
    schema_version: 1,
    observed_at: '2026-08-15T12:00:00+00:00',
    settings: [
      {
        key: 'api_port', kind: 'port', label: 'API port', description: 'Port the control API binds',
        current: 7400, configured: true, value_redacted: false, editable: true,
        source: 'default', default: 7400, restart_required: true, validation: '1-65535',
      },
      {
        key: 'llm_base_url', kind: 'url', label: 'Inference base URL', description: 'Upstream OpenAI-compatible endpoint',
        current: 'http://127.0.0.1:8000/v1', configured: true, value_redacted: false, editable: true,
        source: 'environment', default: '', restart_required: true, validation: '',
      },
      {
        key: 'enable_search', kind: 'bool', label: 'Enable search', description: 'Turns the search control on',
        current: false, configured: true, value_redacted: false, editable: true,
        source: 'env_file', default: false, restart_required: true, validation: '',
      },
      {
        key: 'api_key', kind: 'secret', label: 'API key', description: 'Operator access key',
        current: null, configured: true, value_redacted: true, editable: false,
        source: 'env_file', default: null, restart_required: true, validation: '',
      },
    ],
    restart_required: true,
    journal: { applied_at: null, applied: [], rollback_available: false },
  }
}

function validWorkflows() {
  return {
    schema_version: 1,
    observed_at: '2026-08-15T12:00:00+00:00',
    workflows: [
      {
        workflow_id: 'benchmark', label: 'Benchmark', description: 'Run a benchmark campaign',
        steps: [{
          id: 'preflight', label: 'Preflight', description: 'Check evidence', preflight: 'Store owned',
          recovery: 'Resolve issues', confirm_required: false,
        }],
      },
      {
        workflow_id: 'remove', label: 'Remove', description: 'Remove a model from the store',
        steps: [{
          id: 'confirm', label: 'Confirmation', description: 'Explicit removal consent', preflight: '',
          recovery: '', confirm_required: true,
        }],
      },
    ],
    sessions: [{
      schema_version: 1, session_id: 's1', workflow_id: 'benchmark', label: 'Benchmark',
      state: 'running', current_step_id: 'preflight', current_step_label: 'Preflight',
      progress_percent: 40, cancel_requested: false, error: null,
      recovery_instruction: null, started_at: '2026-08-15T12:00:00+00:00',
      steps: [{ id: 'preflight', label: 'Preflight', description: 'Check evidence', preflight: 'Store owned', recovery: 'Resolve issues', confirm_required: false, outcome: null }],
    }],
    audit_events: [
      { recorded_at: '2026-08-15T12:00:00+00:00', session_id: 's1', workflow_id: 'benchmark', event: 'started', step_id: null, message: null },
    ],
  }
}

function validPlan(valid: boolean) {
  return valid
    ? {
        schema_version: 1, valid: true, restart_required: true, description: 'Review the diff',
        changes: [{ key: 'api_port', before: 7400, after: 7411, restart_required: true, kind: 'port' }],
        issues: [],
      }
    : {
        schema_version: 1, valid: false, restart_required: false, description: 'Review the issues',
        changes: [],
        issues: [{ key: 'api_port', code: 'validation_failed', message: 'Port out of range' }],
      }
}

function mockFetch(
  payload: unknown = overview,
  status = 200,
  routes: {
    navigation?: unknown
    controls?: unknown
    recommendation?: unknown
    metrics?: unknown
    events?: unknown
    benchmarks?: unknown
    analytics?: unknown
    settings?: unknown
    workflows?: unknown
    plan?: unknown
    rejectPaths?: string[]
  } = {},
) {
  const navigationPayload = routes.navigation ?? navigation
  const controlsPayload = routes.controls ?? controls
  const recommendationPayload = routes.recommendation === undefined ? null : routes.recommendation
  const settingsPayload = routes.settings ?? validSettings()
  const workflowsPayload = (routes.workflows ?? validWorkflows()) as ReturnType<typeof validWorkflows>
  const rejectPaths = new Set(routes.rejectPaths ?? [])
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
    const path = new URL(url).pathname
    const method = options?.method ?? 'GET'
    if (rejectPaths.has(path)) throw new DOMException('network unreachable', 'NetworkError')
    const respond = (body: unknown, responseStatus: number) =>
      Promise.resolve(new Response(JSON.stringify(body), {
        status: responseStatus,
        headers: { 'Content-Type': 'application/json' },
      }))
    if (path === '/api/v1/session' && method !== 'GET') {
      return respond({ status: 'authenticated' }, 200)
    }
    if (path === '/api/v1/operations/navigation') return respond(navigationPayload, status)
    if (path === '/api/v1/operations/controls') return respond(controlsPayload, status)
    if (path === '/api/v1/operations/metrics') {
      const signalName = new URL(url).searchParams.get('signal')
      const trend = signalName !== null && signalName !== 'gpu_cache_usage'
        ? { ...validMetrics(), signal: signalName, unit: 'bytes' }
        : routes.metrics ?? validMetrics()
      return respond(trend, status)
    }
    if (path === '/api/v1/operations/events') return respond(routes.events ?? validEvents(), status)
    if (path === '/api/v1/operations/benchmarks') return respond(routes.benchmarks ?? validBenchmarks(), status)
    if (path === '/api/v1/operations/analytics') return respond(routes.analytics ?? validAnalytics(), status)
    if (path === '/api/v1/recommendations/latest') {
      return respond(recommendationPayload, recommendationPayload === null ? 404 : 200)
    }
    if (path === '/api/v1/operations/settings' && method === 'GET') return respond(settingsPayload, status)
    if (path === '/api/v1/operations/settings/plan') return respond(routes.plan ?? validPlan(true), 200)
    if (path === '/api/v1/operations/settings/apply') {
      return respond({ schema_version: 1, applied: { api_port: '7411' }, restart_required: true }, 200)
    }
    if (path === '/api/v1/operations/settings/rollback') {
      return respond({ schema_version: 1, rolled_back: true }, 200)
    }
    if (path === '/api/v1/operations/workflows' && method === 'GET') return respond(workflowsPayload, status)
    if (path.endsWith('/operations/workflows/remove/start')) {
      return respond({ schema_version: 1, started: true, session: workflowsPayload.sessions[0] }, 200)
    }
    if (path.endsWith('/operations/workflows/benchmark/cancel')) {
      return respond({ schema_version: 1, cancelled: true }, 200)
    }
    if (path.includes('/operations/workflows/') && method === 'POST') {
      return respond({ schema_version: 1, cancelled: true }, 200)
    }
    return respond(payload, status)
  }))
}

function validMetrics() {
  return {
    schema_version: 1,
    observed_at: '2026-08-01T12:00:00+00:00',
    signal: 'gpu_cache_usage',
    unit: 'percent',
    freshness: { state: 'fresh', latest_observed_at: '2026-08-01T11:59:00+00:00', age_seconds: 60 },
    sources: [
      { source: 'engine', state: 'available', reason: null },
      { source: 'host', state: 'available', reason: null },
    ],
    buckets: [
      { start: '2026-08-01T10:00:00+00:00', end: '2026-08-01T11:00:00+00:00', count: 12, min: 20, max: 60, mean: 40, p50: 40, p95: 55 },
      { start: '2026-08-01T11:00:00+00:00', end: '2026-08-01T12:00:00+00:00', count: 12, min: 40, max: 80, mean: 60, p50: 60, p95: 75 },
    ],
    gaps: [{ start: '2026-08-01T11:00:00+00:00', end: '2026-08-01T12:00:00+00:00' }],
    sample_count: 24,
  }
}

function validEvents() {
  return {
    schema_version: 1,
    observed_at: '2026-08-01T12:00:00+00:00',
    count: 2,
    events: [
      { recorded_at: '2026-08-01T11:00:00+00:00', source: 'api', severity: 'info', message: 'heartbeat', correlation_id: null, deployment_id: null, campaign_id: null },
      { recorded_at: '2026-08-01T10:00:00+00:00', source: 'engine', severity: 'error', message: 'auth failed Bearer [REDACTED]', correlation_id: 'corr-9', deployment_id: null, campaign_id: null },
    ],
  }
}

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

function validAnalytics() {
  return {
    schema_version: 1,
    observed_at: '2026-08-01T12:00:00+00:00',
    usage: { requests: 120, successes: 118, cancellations: 1, errors: 1, prompt_tokens: 9000, completion_tokens: 12000, window_days: 30 },
    scorecards: [
      { run_id: 'run-1', model_id: 'm', engine_id: 'e', quantization: 'q8_0', statistic: 'p50', sample_count: 4, ttft_seconds: 0.2, tokens_per_second: 11.5 },
      { run_id: 'run-2', model_id: 'm', engine_id: 'e', quantization: 'q8_0', statistic: 'p50', sample_count: 4, ttft_seconds: 0.3, tokens_per_second: 10.2 },
    ],
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

async function signIn() {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('API access key'), 'test-key')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

test('UI-005 login is keyboard and label accessible', async () => {
  mockFetch()
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Morpheus' })).toBeVisible()
  const input = screen.getByLabelText('API access key')
  input.focus()
  fireEvent.change(input, { target: { value: 'test-key' } })
  const form = input.closest('form')
  expect(form).not.toBeNull()
  if (form === null) throw new Error('Login form is missing')
  fireEvent.submit(form)
  await screen.findByRole('heading', { name: 'System overview' })
  expect(sessionStorage.getItem('morpheus.session.active')).toBe('1')
  expect(sessionStorage.getItem('morpheus.session.api-key')).toBeNull()
})

test('UI-001 renders model status and honest unavailable host telemetry', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  expect(await screen.findByText('qwen36-27b-nvfp4')).toBeVisible()
  expect(screen.getByText('131,072')).toBeVisible()
  expect(screen.getAllByText('Unavailable')).toHaveLength(4)
  expect(screen.getByText('Runtime agent offline')).toBeVisible()
  expect(screen.getByText('Available')).toBeVisible()
  expect(screen.getByText('Disabled')).toBeVisible()
})

test('UI-002 diagnostics exposes evidence and freshness', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Diagnostics' }))
  expect(await screen.findByRole('heading', { name: 'Diagnostics' })).toBeVisible()
  expect(screen.getByText('Inference Models Ready')).toBeVisible()
  expect(screen.getByText('Current evidence')).toBeVisible()
  expect(screen.getByText('No action required')).toBeVisible()
})

test('UI-004 retains layout and reports a partial API failure', async () => {
  mockFetch({}, 503)
  render(<App />)
  await signIn()
  expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 503')
  expect(screen.getByRole('button', { name: 'Refresh overview' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Sign out' })).toBeVisible()
})

test('session sign out removes only the browser session marker', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))
  await waitFor(() => expect(screen.getByLabelText('API access key')).toBeVisible())
  expect(sessionStorage.getItem('morpheus.session.active')).toBeNull()
  expect(sessionStorage.getItem('morpheus.session.api-key')).toBeNull()
})

test('blank credentials do not create a dashboard session', () => {
  mockFetch()
  render(<App />)
  const input = screen.getByLabelText('API access key')
  const form = input.closest('form')
  if (form === null) throw new Error('Login form is missing')
  fireEvent.submit(form)
  expect(screen.getByLabelText('API access key')).toBeVisible()
  expect(sessionStorage.getItem('morpheus.session.active')).toBeNull()
})

test('available host metrics, blockers, and alternate feature icons render', async () => {
  mockFetch({
    ...overview,
    capabilities: {
      core: { state: 'available', blockers: [] },
      voice: { state: 'unhealthy', blockers: ['tts_unreachable'] },
      workflows: { state: 'blocked', blockers: ['gateway_not_configured'] },
    },
    host: {
      status: 'available',
      gpu: { memory_total_mib: 32607, memory_used_mib: 12000, utilization_percent: 7, temperature_c: 42 },
      disk: { total_bytes: 500_000_000_000, free_bytes: 107_374_182_400 },
    },
  })
  render(<App />)
  await signIn()
  expect(await screen.findByText('12,000 MiB')).toBeVisible()
  expect(screen.getByText('7% utilization')).toBeVisible()
  expect(screen.getByText('100 GiB')).toBeVisible()
  expect(screen.getByText('Tts Unreachable')).toBeVisible()
  expect(screen.getByText('Gateway Not Configured')).toBeVisible()
  expect(screen.getByText('Unhealthy')).toBeVisible()
  expect(screen.getByText('Blocked')).toBeVisible()
})

test('missing model and stale evidence remain explicit', async () => {
  mockFetch({
    ...overview,
    inference: { ...overview.inference, state: 'degraded', expires_at: '2000-01-01T00:00:00Z' },
    diagnostics: {
      ...overview.diagnostics,
      status: 'unhealthy',
      checks: overview.diagnostics.checks.map((check) => ({ ...check, freshness: 'stale' })),
    },
    models: [],
  })
  render(<App />)
  await signIn()
  expect(await screen.findByText('Not reported')).toBeVisible()
  expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(1)
  await userEvent.click(screen.getByRole('button', { name: 'Diagnostics' }))
  expect(await screen.findByText('Stale evidence')).toBeVisible()
  expect(screen.getByText('Unhealthy')).toBeVisible()
})

test('REC-001 recommendations tab shows exclusions and tradeoffs', async () => {
  const recommendation = {
    recommendation: {
      record_id: 'a'.repeat(64),
      created_at: '2026-08-01T12:00:00+00:00',
      profile: { id: 'developer-default', version: '2026.2', name: 'Developer default' },
      reference_machine_id: 'ubuntu-1',
      ranked: [{
        candidate: { model_id: 'qwen2.5-7b-instruct', quantization: 'awq', engine_id: 'vllm', context_window: 8192, concurrency: 1 },
        score: 0.42,
        contributions: [
          { metric: 'memory_headroom', weight: 0.05, calibrated: 0.9, effective_confidence: 0.5, contribution: 0.45, comparability: 'comparable' },
        ],
        summary: 'strongest: memory_headroom',
      }],
      excluded: [{
        candidate: { model_id: 'llama-3.1-8b-instruct', quantization: 'q4_k_m', engine_id: 'llama.cpp', context_window: 8192, concurrency: 1 },
        violations: [{ code: 'accelerator', detail: 'engine llama.cpp requires cpu' }],
      }],
      summary: 'top: qwen2.5-7b-instruct/awq vllm (score 0.420); excluded: 1 tuples',
    },
  }
  mockFetch(overview, 200, { recommendation })
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Models' }))
  expect(await screen.findByText(/Developer default/)).toBeVisible()
  expect(screen.getByText(/qwen2.5-7b-instruct · awq · vllm/)).toBeVisible()
  expect(screen.getByText(/Accelerator: engine llama.cpp requires cpu/)).toBeVisible()
})

test('REC-002 recommendations tab without a record shows empty state', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Models' }))
  expect(await screen.findByText(/No recommendation recorded yet/)).toBeVisible()
})

test('OUI-001 navigation lists every operator workspace with its state', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  expect(await screen.findByRole('heading', { name: 'System overview' })).toBeVisible()
  expect(screen.getByRole('navigation', { name: 'Operator workspaces' })).toBeVisible()
  for (const label of ['Overview', 'Hardware', 'Models', 'Engines', 'Runtime', 'Benchmarks', 'Analytics', 'Logs & Events', 'Diagnostics', 'Settings', 'Recovery']) {
    expect(screen.getByRole('button', { name: label })).toBeVisible()
  }
  expect(screen.getByRole('button', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
  expect(screen.getAllByText('Empty')).toHaveLength(6)
})

test('OUI-001 empty and unavailable workspaces stay honest when opened', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Engines' }))
  expect(await screen.findByRole('heading', { name: 'Engines' })).toBeVisible()
  expect(screen.getByText(/has no query model in this release yet/)).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Hardware' }))
  expect(await screen.findByRole('heading', { name: 'Hardware' })).toBeVisible()
  expect(screen.getByText(/Runtime agent offline/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Engines' })).not.toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('button', { name: 'Hardware' })).toHaveAttribute('aria-current', 'page')
})

test('OUI-001 navigation failure falls back to the workspace catalog', async () => {
  mockFetch(overview, 200, { navigation: { error: { code: 'navigation_unavailable' } } })
  render(<App />)
  await signIn()
  expect(await screen.findByRole('heading', { name: 'System overview' })).toBeVisible()
  expect(screen.getByRole('button', { name: 'Engines' })).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Engines' }))
  expect(await screen.findByText(/evidence source for Engines is unavailable/)).toBeVisible()
})

test('UI-003 runtime workspace renders the four-state control ladder', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Runtime' }))
  expect(await screen.findByRole('heading', { name: 'Feature controls' })).toBeVisible()
  expect(screen.getByText('Core runtime ready')).toBeVisible()
  const rows = screen.getAllByRole('row')
  expect(rows).toHaveLength(2)
  expect(screen.getAllByText('Usable')).toHaveLength(3)
  expect(screen.getAllByText('Configured')).toHaveLength(3)
})

test('UI-003 unhealthy core keeps controls running but never usable', async () => {
  const degraded = {
    schema_version: 1,
    observed_at: '2026-07-15T12:00:00+00:00',
    core_ready: false,
    controls: [
      { control: 'core', state: 'running', configured: true, running: true, healthy: false, usable: false, blockers: ['network_endpoint_failed'] },
      { control: 'search', state: 'healthy', configured: true, running: true, healthy: true, usable: false, blockers: [] },
    ],
  }
  mockFetch(overview, 200, { controls: degraded })
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Runtime' }))
  expect(await screen.findByText('Core runtime not ready')).toBeVisible()
  expect(screen.getByText('Network Endpoint Failed')).toBeVisible()
  expect(screen.getAllByText('Healthy')).toHaveLength(3)
  expect(screen.getAllByText('Running')).toHaveLength(3)
  expect(screen.getAllByText('Usable')).toHaveLength(2)
})

test('UI-003 controls failure keeps the runtime workspace honest', async () => {
  mockFetch(overview, 200, { controls: { error: { code: 'controls_unavailable' } } })
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Runtime' }))
  expect(await screen.findByText(/Controls are unavailable/)).toBeVisible()
})

test('OUI-001 partial and ready workspaces and an unknown id stay honest', async () => {
  const customNav = {
    ...navigation,
    workspaces: [
      ...navigation.workspaces.map((workspace) =>
        workspace.id === 'engines' ? { ...workspace, state: 'partial' } : workspace.id === 'analytics' ? { ...workspace, state: 'ready' } : workspace,
      ),
      { id: 'bogus', label: 'Bogus', state: 'unavailable', query_model: null },
    ],
  }
  mockFetch(overview, 200, { navigation: customNav })
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Engines' }))
  expect(await screen.findByText(/Only partial evidence is available for Engines/)).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Analytics' }))
  expect(await screen.findByText('30-day window')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Bogus' }))
  expect(await screen.findByText(/evidence source for Bogus is unavailable/)).toBeVisible()
})

test('UI-003 unknown control and capability names use fallback icons', async () => {
  const unknownControl = { control: 'bogus', state: 'configured', configured: false, running: false, healthy: false, usable: false, blockers: [] }
  mockFetch(
    { ...overview, capabilities: { ...overview.capabilities, bogus: { state: 'blocked', blockers: [] } } },
    200,
    { controls: { ...controls, controls: [...controls.controls, unknownControl] } },
  )
  render(<App />)
  await signIn()
  expect(await screen.findByText('Bogus')).toBeVisible()
  expect(screen.getByText('Blocked')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Runtime' }))
  expect(await screen.findByRole('table', { name: 'Feature controls' })).toBeVisible()
})

test('UI-002 diagnostics with a ready status and failed checks render honestly', async () => {
  mockFetch({
    ...overview,
    diagnostics: {
      ...overview.diagnostics,
      status: 'ready',
      checks: [
        { ...overview.diagnostics.checks[0], status: 'fail', reason_code: 'network_endpoint_failed', next_action: 'Verify the endpoint' },
        { ...overview.diagnostics.checks[0], code: 'storage', status: 'pass', reason_code: 'storage_ready', summary: 'Storage evidence is ready' },
        { ...overview.diagnostics.checks[0], code: 'models', status: 'unavailable', reason_code: 'models_unknown', summary: 'Models evidence unavailable' },
      ],
    },
  })
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Diagnostics' }))
  expect(await screen.findByText('Verify the endpoint')).toBeVisible()
  expect(screen.getByText('Storage Ready')).toBeVisible()
  expect(screen.getAllByText('Ready')).toHaveLength(4)
})

test('OUI-001 hardware workspace renders available and degraded host evidence', async () => {
  const hostAvailable = {
    status: 'available',
    gpu: { memory_total_mib: 32607, memory_used_mib: 12000, utilization_percent: 7, temperature_c: 42 },
    memory: { total_bytes: 32_000_000_000, available_bytes: 16_000_000_000 },
    disk: { total_bytes: 500_000_000_000, free_bytes: 107_374_182_400 },
  }
  mockFetch({ ...overview, host: hostAvailable })
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Hardware' }))
  expect(await screen.findByRole('heading', { name: 'Hardware' })).toBeVisible()
  expect(screen.getByText('12,000 MiB')).toBeVisible()
  expect(screen.getByText('32,607 MiB total · 7% utilized')).toBeVisible()
  expect(screen.getByText('15 GiB')).toBeVisible()
  expect(screen.getByText('15 GiB free')).toBeVisible()
  expect(screen.getByText('100 GiB')).toBeVisible()
  expect(screen.getByText('Available')).toBeVisible()
  expect(screen.getByText('All probes passed')).toBeVisible()
})

test('OUI-001 degraded hardware without accelerator or storage evidence stays honest', async () => {
  mockFetch({
    ...overview,
    host: { status: 'degraded', memory: { total_bytes: 32_000_000_000, available_bytes: 16_000_000_000 } },
  })
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Hardware' }))
  expect(await screen.findByText('No accelerator evidence')).toBeVisible()
  expect(screen.getByText('15 GiB')).toBeVisible()
  expect(screen.getByText('15 GiB free')).toBeVisible()
  expect(screen.getByText('No storage evidence')).toBeVisible()
  expect(screen.getByText('Degraded')).toBeVisible()
  expect(screen.getByText('Partial evidence')).toBeVisible()
})

test('OUI-001 degraded hardware without memory evidence stays honest', async () => {
  mockFetch({
    ...overview,
    host: { status: 'degraded', gpu: { memory_total_mib: 32607, memory_used_mib: 12000, utilization_percent: 7, temperature_c: 42 } },
  })
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Hardware' }))
  expect(await screen.findByText('12,000 MiB')).toBeVisible()
  expect(screen.getByText('No memory evidence')).toBeVisible()
  expect(screen.getByText('No storage evidence')).toBeVisible()
  expect(screen.getByText('Degraded')).toBeVisible()
  expect(screen.getByText('Partial evidence')).toBeVisible()
})

test('OUI-001 hardware workspace stays usable when the overview failed', async () => {
  mockFetch({}, 503)
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Hardware' }))
  expect(await screen.findByText(/Runtime agent offline: Runtime Agent Not Configured/)).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Diagnostics' }))
  expect(screen.queryByRole('heading', { name: 'Diagnostics' })).not.toBeInTheDocument()
})

test('UI-005 a failed session expires back to the login screen', async () => {
  mockFetch(overview, 401)
  render(<App />)
  await signIn()
  expect(await screen.findByLabelText('API access key')).toBeVisible()
  expect(sessionStorage.getItem('morpheus.session.active')).toBeNull()
})

test('UI-004 a non-error rejection surfaces a generic message', async () => {
  mockFetch(overview, 200, { rejectPaths: ['/api/v1/overview'] })
  render(<App />)
  await signIn()
  expect(await screen.findByRole('alert')).toHaveTextContent('Control API request failed')
})

test('REC-002 a failed recommendation fetch shows the empty tab state', async () => {
  mockFetch(overview, 200, { rejectPaths: ['/api/v1/recommendations/latest'] })
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Models' }))
  expect(await screen.findByText(/No recommendation recorded yet/)).toBeVisible()
})

test('BROW-004 an aborted refresh is ignored and the newest refresh wins', async () => {
  const abortError = () => new DOMException('aborted', 'AbortError')
  const fetchMock = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
    const sessionRequest = options?.method === 'POST' || options?.method === 'DELETE'
    if (sessionRequest) {
      return Promise.resolve(new Response(JSON.stringify({ status: 'authenticated' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    }
    const path = new URL(url).pathname
    const signal = options?.signal
    const settle = (): Response => new Response(JSON.stringify(overview), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
    if (path === '/api/v1/recommendations/latest') {
      return new Promise<Response>((resolve, reject) => {
        if (signal?.aborted) { reject(abortError()); return }
        signal?.addEventListener('abort', () => { reject(abortError()) })
        window.setTimeout(() => {
          if (signal?.aborted) { reject(abortError()); return }
          resolve(new Response(JSON.stringify({ error: {} }), {
            status: 404,
            headers: { 'Content-Type': 'application/json' },
          }))
        }, 1000)
      })
    }
    return new Promise<Response>((resolve, reject) => {
      if (signal?.aborted) { reject(abortError()); return }
      signal?.addEventListener('abort', () => { reject(abortError()) })
      window.setTimeout(() => {
        if (signal?.aborted) { reject(abortError()); return }
        resolve(settle())
      }, 80)
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  const input = screen.getByLabelText('API access key')
  fireEvent.change(input, { target: { value: 'test-key' } })
  fireEvent.submit(input.closest('form') as HTMLFormElement)
  await screen.findByRole('heading', { name: 'System overview' })
  const refreshButton = screen.getByRole('button', { name: 'Refresh overview' })
  fireEvent.click(refreshButton)
  await new Promise((resolve) => setTimeout(resolve, 80))
  fireEvent.click(refreshButton)
  fireEvent.click(refreshButton)
  await screen.findByRole('heading', { name: 'System overview' })
  fireEvent.click(refreshButton)
})

test('BROW-004 a hidden tab skips the automatic refresh interval', async () => {
  vi.useFakeTimers()
  try {
    const fetchMock = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      const sessionRequest = options?.method === 'POST' || options?.method === 'DELETE'
      if (sessionRequest) {
        return Promise.resolve(new Response(JSON.stringify({ status: 'authenticated' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }))
      }
      const path = new URL(url).pathname
      if (path === '/api/v1/recommendations/latest') {
        return Promise.resolve(new Response(JSON.stringify({ error: {} }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        }))
      }
      return Promise.resolve(new Response(JSON.stringify(overview), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    const input = screen.getByLabelText('API access key')
    fireEvent.change(input, { target: { value: 'test-key' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)
    for (let i = 0; i < 50 && !screen.queryByRole('heading', { name: 'System overview' }); i++) {
      await vi.advanceTimersByTimeAsync(0)
    }
    expect(screen.getByRole('heading', { name: 'System overview' })).toBeVisible()
    const callsBefore = fetchMock.mock.calls.length
    const hiddenSpy = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(fetchMock.mock.calls.length).toBe(callsBefore)
    hiddenSpy.mockReturnValue(false)
    await vi.advanceTimersByTimeAsync(20_000)
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore)
    hiddenSpy.mockRestore()
  } finally {
    vi.useRealTimers()
  }
})

test('UI-005 signing out while requests are in flight still returns to the login screen', async () => {
  const abortError = () => new DOMException('aborted', 'AbortError')
  const fetchMock = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
    const sessionRequest = options?.method === 'POST' || options?.method === 'DELETE'
    if (sessionRequest) {
      return Promise.resolve(new Response(JSON.stringify({ status: 'authenticated' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    }
    const path = new URL(url).pathname
    if (path === '/api/v1/recommendations/latest') {
      return new Promise<Response>((resolve, reject) => {
        const signal = options?.signal
        if (signal?.aborted) { reject(abortError()); return }
        signal?.addEventListener('abort', () => { reject(abortError()) })
        window.setTimeout(() => {
          if (signal?.aborted) { reject(abortError()); return }
          resolve(new Response(JSON.stringify({ error: {} }), {
            status: 404,
            headers: { 'Content-Type': 'application/json' },
          }))
        }, 1000)
      })
    }
    return new Promise<Response>((resolve, reject) => {
      const signal = options?.signal
      if (signal?.aborted) { reject(abortError()); return }
      signal?.addEventListener('abort', () => { reject(abortError()) })
      window.setTimeout(() => {
        if (signal?.aborted) { reject(abortError()); return }
        resolve(new Response(JSON.stringify(overview), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }))
      }, 80)
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<App />)
  const input = screen.getByLabelText('API access key')
  fireEvent.change(input, { target: { value: 'test-key' } })
  fireEvent.submit(input.closest('form') as HTMLFormElement)
  await screen.findByRole('heading', { name: 'System overview' })
  fireEvent.click(screen.getByRole('button', { name: 'Refresh overview' }))
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
  expect(await screen.findByLabelText('API access key')).toBeVisible()
  expect(sessionStorage.getItem('morpheus.session.active')).toBeNull()
})

test.each([
  [new Error('boom'), 'boom'],
  [new DOMException('network unreachable', 'NetworkError'), 'Authentication failed'],
])('UI-005 login failure surfaces a safe error message', async (rejection, message) => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation((_url: string, options?: RequestInit) => {
    const sessionRequest = options?.method === 'POST' || options?.method === 'DELETE'
    return new Promise<Response>((resolve) => {
      if (sessionRequest) throw rejection
      resolve(new Response('{}', { status: 200 }))
    })
  }))
  render(<App />)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('API access key'), 'test-key')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(message)
  expect(screen.getByLabelText('API access key')).toBeVisible()
  expect(sessionStorage.getItem('morpheus.session.active')).toBeNull()
})

test('OUI-002 hardware trends render units, normalized bars, gaps, and sources', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Hardware' }))
  expect(await screen.findByRole('heading', { name: 'Hardware trends' })).toBeVisible()
  expect(screen.getByText('Unit: percent')).toBeVisible()
  expect(screen.getByText('Fresh evidence')).toBeVisible()
  expect(screen.getByText('24 samples in window')).toBeVisible()
  const bars = screen.getAllByRole('img', { name: /samples, mean 40%/ })
  expect(bars).toHaveLength(1)
  const firstBar = bars[0] as HTMLElement
  expect(Number.parseFloat(firstBar.style.height)).toBeCloseTo(66.6667, 3)
  expect(screen.getAllByRole('img', { name: 'Missing data interval' })).toHaveLength(1)
  expect(screen.getByText(/Sources: engine available · host available/)).toBeVisible()
})

test('OUI-002 signal switch refetches and changes the trend label', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Hardware' }))
  await screen.findByRole('heading', { name: 'Hardware trends' })
  await userEvent.selectOptions(screen.getByLabelText('Signal'), 'free_bytes')
  expect(await screen.findByText('Unit: bytes')).toBeVisible()
})

test('OUI-003 log and events workspace filters by severity and source', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Logs & Events' }))
  expect(await screen.findByRole('heading', { name: 'Logs & events' })).toBeVisible()
  expect(screen.getByText(/auth failed Bearer \[REDACTED\]/)).toBeVisible()
  expect(screen.getByText(/corr-9/)).toBeVisible()
  await userEvent.selectOptions(screen.getByLabelText('Severity'), 'info')
  expect(screen.getByText('heartbeat')).toBeVisible()
  expect(screen.queryByText(/auth failed/)).not.toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Source'), 'api')
  expect(screen.getByText('heartbeat')).toBeVisible()
  expect(screen.queryByText(/auth failed/)).not.toBeInTheDocument()
})

test('OUI-003 event log shows the empty state when no events match', async () => {
  mockFetch(overview, 200, { events: { schema_version: 1, observed_at: '2026-08-01T12:00:00+00:00', count: 0, events: [] } })
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Logs & Events' }))
  expect(await screen.findByText(/No events match the filters/)).toBeVisible()
})

test('OUI-004 benchmarks workspace lists run history most recent first', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Benchmarks' }))
  expect(await screen.findByRole('heading', { name: 'Benchmarks' })).toBeVisible()
  expect(screen.getByText('run-1')).toBeVisible()
  expect(screen.getByText('qwen2.5-7b-instruct')).toBeVisible()
  expect(screen.getByText('Completed')).toBeVisible()
})

test('OUI-004 analytics workspace reports usage, scorecards, comparisons, and regressions', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Analytics' }))
  expect(await screen.findByRole('heading', { name: 'Analytics' })).toBeVisible()
  expect(screen.getByText('30-day window')).toBeVisible()
  expect(screen.getByText('120')).toBeVisible()
  expect(screen.getByText('118')).toBeVisible()
  expect(screen.getByText('21,000')).toBeVisible()
  expect(screen.getByText('200 ms')).toBeVisible()
  expect(screen.getByText('12 tok/s')).toBeVisible()
  expect(screen.getByText('run-1 → run-2')).toBeVisible()
  expect(screen.getByText('COMPARABLE')).toBeVisible()
  expect(screen.getAllByText('+50%')).toHaveLength(2)
})

test('OUI-002 failed metrics fetch keeps the workspace honest', async () => {
  mockFetch(overview, 200, { rejectPaths: ['/api/v1/operations/metrics'] })
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Hardware' }))
  expect(await screen.findByText('Trend data is unavailable right now.')).toBeVisible()
})

test('OUI-005 settings workspace renders catalog, previews a plan, and applies changes', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
  expect(await screen.findByRole('heading', { name: 'Settings' })).toBeVisible()
  expect(screen.getByText('API port')).toBeVisible()
  expect(screen.getByText(/not editable here/i)).toBeVisible()
  expect(screen.getByText('Default')).toBeVisible()
  expect(screen.getByText('Environment')).toBeVisible()

  const input = screen.getByLabelText('New value for API port')
  await userEvent.clear(input)
  await userEvent.type(input, '7411')
  await userEvent.click(screen.getByRole('button', { name: 'Preview plan' }))
  expect(await screen.findByText('Plan is valid')).toBeVisible()
  expect(screen.getByText('Restart required')).toBeVisible()
  expect(screen.getByText('7400 → 7411')).toBeVisible()

  await userEvent.click(screen.getByRole('button', { name: 'Apply changes' }))
  expect(await screen.findByText('Applied 1 change; restart required for them to take effect.')).toBeVisible()
  expect(screen.getByText('No pending overrides. The runtime uses its configured layers with defaults.')).toBeVisible()
})

test('OUI-005 invalid plans surface validation issues instead of applying', async () => {
  mockFetch(overview, 200, { plan: validPlan(false) })
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
  const input = await screen.findByLabelText('New value for API port')
  await userEvent.clear(input)
  await userEvent.type(input, '99999')
  await userEvent.click(screen.getByRole('button', { name: 'Preview plan' }))
  expect(await screen.findByText('Plan needs review')).toBeVisible()
  expect(screen.getByText('api_port: Port out of range')).toBeVisible()
  const applyButton = screen.getByRole('button', { name: 'Apply changes' })
  expect((applyButton as HTMLButtonElement).disabled).toBe(true)
})

test('OUI-005 pending overrides offer a working rollback', async () => {
  mockFetch(overview, 200, {
    settings: {
      ...validSettings(),
      journal: { applied_at: '2026-08-15T11:00:00+00:00', applied: { api_port: '7411' }, rollback_available: true },
    },
  })
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
  expect(await screen.findByText(/Pending overrides applied/)).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Roll back' }))
  expect(await screen.findByText('Rolled back to the previous settings snapshot; restart required.')).toBeVisible()
})

test('OUI-006 recovery workspace starts a confirmed workflow and cancels a running session', async () => {
  mockFetch()
  render(<App />)
  await signIn()
  await screen.findByRole('heading', { name: 'System overview' })
  await userEvent.click(screen.getByRole('button', { name: 'Recovery' }))
  expect(await screen.findByRole('heading', { name: 'Recovery & workflows' })).toBeVisible()
  expect(screen.getAllByText('Benchmark').length).toBeGreaterThan(0)
  expect(screen.getAllByText('Remove').length).toBeGreaterThan(0)
  expect(screen.getByText('2 workflows · 1 session')).toBeVisible()
  expect(screen.getAllByText('Running').length).toBeGreaterThan(0)
  expect(screen.getByText('40%')).toBeVisible()
  expect(screen.getByText('Step: Preflight')).toBeVisible()
  expect(screen.getByText('started')).toBeVisible()

  const removeCard = screen.getAllByText('Remove')[0]?.closest('article')
  if (removeCard === null || removeCard === undefined) throw new Error('Remove workflow card is missing')
  await userEvent.click(within(removeCard).getByRole('button', { name: 'Start workflow' }))
  expect(within(removeCard).getByText('This workflow requires explicit confirmation.')).toBeVisible()
  await userEvent.click(within(removeCard).getByRole('button', { name: 'Confirm start' }))
  expect(await screen.findByText('Remove started; watch the session notes for step progress.')).toBeVisible()

  await userEvent.click(screen.getByRole('button', { name: 'Request cancellation' }))
  expect(await screen.findByText('Cancellation requested for the active session.')).toBeVisible()
})
