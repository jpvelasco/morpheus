import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import App from '../src/App'

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

function mockFetch(
  payload: unknown = overview,
  status = 200,
  routes: {
    navigation?: unknown
    controls?: unknown
    recommendation?: unknown
    rejectPaths?: string[]
  } = {},
) {
  const navigationPayload = routes.navigation ?? navigation
  const controlsPayload = routes.controls ?? controls
  const recommendationPayload = routes.recommendation === undefined ? null : routes.recommendation
  const rejectPaths = new Set(routes.rejectPaths ?? [])
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
    const sessionRequest = options?.method === 'POST' || options?.method === 'DELETE'
    if (sessionRequest) {
      return new Response(JSON.stringify({ status: 'authenticated' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    const path = new URL(url).pathname
    if (rejectPaths.has(path)) throw new DOMException('network unreachable', 'NetworkError')
    const respond = (body: unknown, responseStatus: number) =>
      Promise.resolve(new Response(JSON.stringify(body), {
        status: responseStatus,
        headers: { 'Content-Type': 'application/json' },
      }))
    if (path === '/api/v1/operations/navigation') return respond(navigationPayload, status)
    if (path === '/api/v1/operations/controls') return respond(controlsPayload, status)
    if (path === '/api/v1/recommendations/latest') {
      return respond(recommendationPayload, recommendationPayload === null ? 404 : 200)
    }
    return respond(payload, status)
  }))
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
        workspace.id === 'engines' ? { ...workspace, state: 'partial' } : workspace.id === 'benchmarks' ? { ...workspace, state: 'ready' } : workspace,
      ),
      { id: 'bogus', label: 'Bogus', state: 'unavailable', query_model: null },
    ],
  }
  mockFetch(overview, 200, { navigation: customNav })
  render(<App />)
  await signIn()
  await userEvent.click(screen.getByRole('button', { name: 'Engines' }))
  expect(await screen.findByText(/Only partial evidence is available for Engines/)).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Benchmarks' }))
  expect(await screen.findByText('Benchmarks is ready.')).toBeVisible()
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
