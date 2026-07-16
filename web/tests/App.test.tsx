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

function mockFetch(payload: unknown = overview, status = 200) {
  vi.stubGlobal('fetch', vi.fn().mockImplementation((_: string, options?: RequestInit) => {
    const sessionRequest = options?.method === 'POST' || options?.method === 'DELETE'
    return Promise.resolve(new Response(JSON.stringify(sessionRequest ? { status: 'authenticated' } : payload), {
      status: sessionRequest ? 200 : status,
      headers: { 'Content-Type': 'application/json' },
    }))
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
  expect(screen.getAllByText('Unavailable')).toHaveLength(2)
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
