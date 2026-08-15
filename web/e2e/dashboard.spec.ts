import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page, type TestInfo } from '@playwright/test'
import type { Overview } from '../src/api'

const API = 'http://127.0.0.1:7400'

const overview: Overview = {
  observed_at: '2026-07-17T08:00:00+00:00',
  inference: {
    state: 'ready',
    reason_code: 'inference_models_ready',
    summary: 'Inference API returned one or more served models',
    observed_at: '2026-07-17T08:00:00+00:00',
    duration_ms: 2.5,
    source: 'openai_models',
    expires_at: '2099-07-17T08:00:30+00:00',
    next_action: null,
  },
  models: [
    {
      root: 'nvidia/Qwen3.6-27B-NVFP4',
      aliases: ['qwen36-27b-nvfp4'],
      context_window: 131072,
    },
  ],
  capabilities: {
    core: { state: 'available', blockers: [] },
    search: { state: 'disabled', blockers: [] },
    voice: { state: 'blocked', blockers: ['voice_profile_not_enabled'] },
  },
  host: {
    status: 'available',
    gpu: {
      memory_total_mib: 32607,
      memory_used_mib: 12000,
      utilization_percent: 7,
      temperature_c: 42,
    },
    disk: { total_bytes: 500_000_000_000, free_bytes: 107_374_182_400 },
  },
  diagnostics: {
    status: 'degraded',
    observed_at: '2026-07-17T08:00:00+00:00',
    checks: [
      {
        code: 'network_endpoint',
        status: 'pass',
        reason_code: 'inference_models_ready',
        summary: 'Inference API returned one or more served models',
        observed_at: '2026-07-17T08:00:00+00:00',
        freshness: 'current',
        next_action: null,
      },
    ],
  },
  external_controls: [],
}

const navigation = {
  schema_version: 1,
  observed_at: '2026-07-17T08:00:00+00:00',
  workspaces: [
    { id: 'overview', label: 'Overview', state: 'ready', query_model: { schema: 'overview', version: 1 } },
    { id: 'hardware', label: 'Hardware', state: 'partial', query_model: { schema: 'host', version: 1 } },
    { id: 'models', label: 'Models', state: 'ready', query_model: { schema: 'models', version: 1 } },
    { id: 'engines', label: 'Engines', state: 'empty', query_model: null },
    { id: 'runtime', label: 'Runtime', state: 'partial', query_model: { schema: 'runtime', version: 1 } },
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
  observed_at: '2026-07-17T08:00:00+00:00',
  core_ready: true,
  controls: [
    { control: 'core', state: 'usable', configured: true, running: true, healthy: true, usable: true, blockers: [] },
    { control: 'search', state: 'configured', configured: false, running: false, healthy: false, usable: false, blockers: ['feature_disabled'] },
    { control: 'voice', state: 'configured', configured: false, running: false, healthy: false, usable: false, blockers: ['voice_profile_not_enabled'] },
  ],
}

async function mockControl(
  page: Page,
  payload: Overview = overview,
  overviewHandler?: (requestNumber: number) => Promise<{ status: number; body: string }>,
  routes: { navigationStatus?: number; controlsStatus?: number } = {},
): Promise<() => number> {
  let requests = 0
  await page.route(`${API}/api/v1/session`, async (route) => {
    await route.fulfill({
      body: JSON.stringify({ status: 'authenticated' }),
      contentType: 'application/json',
      status: 200,
    })
  })
  await page.route(`${API}/api/v1/operations/navigation`, async (route) => {
    await route.fulfill({
      body: JSON.stringify(navigation),
      contentType: 'application/json',
      status: routes.navigationStatus ?? 200,
    })
  })
  await page.route(`${API}/api/v1/operations/controls`, async (route) => {
    await route.fulfill({
      body: JSON.stringify(controls),
      contentType: 'application/json',
      status: routes.controlsStatus ?? 200,
    })
  })
  await page.route(`${API}/api/v1/recommendations/latest`, async (route) => {
    await route.fulfill({ body: '{}', contentType: 'application/json', status: 404 })
  })
  await page.route(`${API}/api/v1/overview`, async (route) => {
    requests += 1
    const response = overviewHandler
      ? await overviewHandler(requests)
      : { status: 200, body: JSON.stringify(payload) }
    await route.fulfill({
      body: response.body,
      contentType: 'application/json',
      status: response.status,
    })
  })
  return () => requests
}

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('API access key').fill('browser-test-key')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'System overview' })).toBeVisible()
}

async function expectNoBlockingAccessibilityViolations(page: Page): Promise<void> {
  const result = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22a', 'wcag22aa'])
    .analyze()
  const blocking = result.violations.filter(
    (violation) => violation.impact === 'critical' || violation.impact === 'serious',
  )
  expect(blocking).toEqual([])
}

async function captureResponsiveEvidence(page: Page, testInfo: TestInfo): Promise<void> {
  await page.screenshot({
    animations: 'disabled',
    fullPage: true,
    path: testInfo.outputPath('responsive-dashboard.png'),
  })
}

test('BROW-002 core login, refresh, diagnostics, and logout flow', async ({ page }, testInfo) => {
  const requestCount = await mockControl(page)
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Morpheus' })).toBeVisible()
  await expectNoBlockingAccessibilityViolations(page)
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('API access key')).toBeFocused()
  await page.getByLabel('API access key').fill('browser-test-key')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeFocused()
  await page.keyboard.press('Enter')

  await expect(page.getByRole('heading', { name: 'System overview' })).toBeVisible()
  await expect(page.getByText('qwen36-27b-nvfp4')).toBeVisible()
  await expect(page.locator('main').getByText('Ready')).toBeVisible()
  await expect(page.getByText('Disabled')).toBeVisible()
  await expect(page.getByText('Blocked')).toBeVisible()
  await expect(page.getByText('Voice Profile Not Enabled')).toBeVisible()
  const workspaceNav = page.getByRole('navigation', { name: 'Operator workspaces' })
  await expect(workspaceNav.getByRole('button')).toHaveCount(11)
  await expect(workspaceNav.getByRole('button', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
  await expect(workspaceNav.getByRole('button', { name: 'Engines' }).locator('.nav-state')).toHaveText('Empty')
  await expectNoBlockingAccessibilityViolations(page)

  await page.getByRole('button', { name: 'Refresh overview' }).click()
  await expect.poll(requestCount).toBe(2)
  await page.getByRole('button', { name: 'Diagnostics' }).click()
  await expect(page.getByText('Current evidence')).toBeVisible()
  await expect(page.getByText('No action required')).toBeVisible()
  await expectNoBlockingAccessibilityViolations(page)

  await page.getByRole('button', { name: 'Runtime' }).click()
  await expect(page.getByRole('heading', { name: 'Feature controls' })).toBeVisible()
  await expect(page.getByText('Core runtime ready')).toBeVisible()
  await expect(page.getByText('Feature Disabled')).toBeVisible()
  await expect(page.locator('main').getByText('Usable')).toHaveCount(4)
  await expectNoBlockingAccessibilityViolations(page)

await page.getByRole('button', { name: 'Hardware' }).click()
  await expect(page.getByRole('heading', { name: 'Hardware', exact: true })).toBeVisible()
await expect(page.getByText('12,000 MiB')).toBeVisible()
  await expect(page.getByText('Available', { exact: true })).toBeVisible()
  await expect(page.getByText('All probes passed')).toBeVisible()
  await expectNoBlockingAccessibilityViolations(page)

  await page.getByRole('button', { name: 'Engines' }).click()
  await expect(page.getByRole('heading', { name: 'Engines' })).toBeVisible()
  await expect(page.getByText('Engines has no query model in this release yet.')).toBeVisible()
  await expectNoBlockingAccessibilityViolations(page)
  await captureResponsiveEvidence(page, testInfo)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByLabel('API access key')).toBeVisible()
  await expect
    .poll(() => page.evaluate(() => sessionStorage.getItem('morpheus.session.active')))
    .toBeNull()
})

for (const state of ['starting', 'degraded', 'unreachable', 'incompatible'] as const) {
  test(`BROW-002 renders ${state} and stale/empty evidence honestly`, async ({ page }) => {
    const payload: Overview = {
      ...overview,
      inference: {
        ...overview.inference,
        state,
        expires_at: '2000-01-01T00:00:00Z',
        next_action: 'Inspect the inference dependency',
      },
      models: [],
      diagnostics: {
        ...overview.diagnostics,
        status: 'unhealthy',
        checks: overview.diagnostics.checks.map((check) => ({
          ...check,
          freshness: 'stale',
          status: 'unavailable',
        })),
      },
    }
    await mockControl(page, payload)
    await signIn(page)

    await expect(page.getByText(state.charAt(0).toUpperCase() + state.slice(1))).toBeVisible()
    await expect(page.getByText('Not reported')).toBeVisible()
    await page.getByRole('button', { name: 'Diagnostics' }).click()
    await expect(page.getByText('Stale evidence')).toBeVisible()
    await expect(page.getByText('Unavailable')).toBeVisible()
  })
}

test('BROW-002 navigation and controls failures fall back honestly', async ({ page }) => {
  await mockControl(page, overview, undefined, { navigationStatus: 500, controlsStatus: 500 })
  await signIn(page)

  const workspaceNav = page.getByRole('navigation', { name: 'Operator workspaces' })
  await expect(workspaceNav.getByRole('button')).toHaveCount(11)
  await page.getByRole('button', { name: 'Engines' }).click()
  await expect(
    page.getByText('The evidence source for Engines is unavailable right now.'),
  ).toBeVisible()
  await expectNoBlockingAccessibilityViolations(page)
})

test('BROW-002 controls failure keeps the runtime workspace honest', async ({ page }) => {
  await mockControl(page, overview, undefined, { controlsStatus: 500 })
  await signIn(page)

  await page.getByRole('button', { name: 'Runtime' }).click()
  await expect(
    page.getByText('Controls are unavailable. The control API did not return a valid report.'),
  ).toBeVisible()
  await expectNoBlockingAccessibilityViolations(page)
})

test('BROW-004 slow failed refresh retains the last valid observation', async ({ page }) => {
  const requestCount = await mockControl(page, overview, async (number) => {
    if (number === 1) return { status: 200, body: JSON.stringify(overview) }
    await new Promise((resolve) => setTimeout(resolve, 250))
    return { status: 503, body: '{}' }
  })
  await signIn(page)

  await page.getByRole('button', { name: 'Refresh overview' }).click()
  await expect(page.getByRole('heading', { name: 'System overview' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('HTTP 503')
  await expect(page.getByText('qwen36-27b-nvfp4')).toBeVisible()
  expect(requestCount()).toBe(2)
})

test('BROW-004 overlapping refresh cannot replace newer evidence with a stale response', async ({
  page,
}) => {
  const stale: Overview = {
    ...overview,
    models: [{ root: 'stale/model', aliases: ['stale-response'], context_window: 4096 }],
  }
  const latest: Overview = {
    ...overview,
    models: [{ root: 'latest/model', aliases: ['latest-response'], context_window: 8192 }],
  }
  const requestCount = await mockControl(page, overview, async (number) => {
    if (number === 1) return { status: 200, body: JSON.stringify(overview) }
    if (number === 2) {
      await new Promise((resolve) => setTimeout(resolve, 350))
      return { status: 200, body: JSON.stringify(stale) }
    }
    return { status: 200, body: JSON.stringify(latest) }
  })
  await signIn(page)

  await page.getByRole('button', { name: 'Refresh overview' }).click()
  await page.getByRole('button', { name: 'Refresh overview' }).click()
  await expect(page.getByText('latest-response')).toBeVisible()
  await page.waitForTimeout(500)
  await expect(page.getByText('stale-response')).toHaveCount(0)
  expect(requestCount()).toBe(3)
})

test('BROW-003 keyboard focus, reduced motion, and responsive bounds remain usable', async ({
  page,
}, testInfo) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await mockControl(page)
  await signIn(page)

  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth)
  const outOfBounds = await page.locator('button, input, article, [role="row"]').evaluateAll(
    (elements) =>
      elements
        .map((element) => element.getBoundingClientRect())
        .filter(
          (box) =>
            box.left < -1 || box.right > document.documentElement.clientWidth + 1 || box.width <= 0,
        ).length,
  )
  expect(outOfBounds).toBe(0)
  const reducedMotionProbe = page.locator('[data-reduced-motion-probe]')
  await page.evaluate(() => {
    const probe = document.createElement('span')
    probe.className = 'spin'
    probe.dataset.reducedMotionProbe = 'true'
    document.body.append(probe)
  })
  expect(await reducedMotionProbe.evaluate((element) => getComputedStyle(element).animationName))
    .toBe('none')
  await reducedMotionProbe.evaluate((element) => {
    element.remove()
  })

  await page.keyboard.press('Tab')
  const focused = page.locator(':focus')
  await expect(focused).toBeVisible()
  expect(await focused.getAttribute('aria-label')).toBe('Refresh overview')
  await captureResponsiveEvidence(page, testInfo)
})

test('BROW-006 URLs, console, and retained page text contain no credential', async ({ page }) => {
  const consoleMessages: string[] = []
  page.on('console', (message) => consoleMessages.push(message.text()))
  await mockControl(page)
  await signIn(page)

  expect(page.url()).not.toContain('browser-test-key')
  expect(await page.locator('body').innerText()).not.toContain('browser-test-key')
  expect(consoleMessages.join('\n')).not.toContain('browser-test-key')
  expect(
    await page.evaluate(() => ({
      local: Object.values(localStorage),
      session: Object.values(sessionStorage),
    })),
  ).toEqual({ local: [], session: ['1'] })
})

const metricsTrend = {
  schema_version: 1,
  observed_at: '2026-07-17T08:00:00+00:00',
  signal: 'gpu_cache_usage',
  unit: 'percent',
  freshness: { state: 'fresh', latest_observed_at: '2026-07-17T07:59:00+00:00', age_seconds: 60 },
  sources: [
    { source: 'engine', state: 'available', reason: null },
    { source: 'host', state: 'available', reason: null },
  ],
  buckets: [
    { start: '2026-07-17T06:00:00+00:00', end: '2026-07-17T07:00:00+00:00', count: 12, min: 20, max: 60, mean: 40, p50: 40, p95: 55 },
    { start: '2026-07-17T07:00:00+00:00', end: '2026-07-17T08:00:00+00:00', count: 12, min: 40, max: 80, mean: 60, p50: 60, p95: 75 },
  ],
  gaps: [{ start: '2026-07-17T07:00:00+00:00', end: '2026-07-17T08:00:00+00:00' }],
  sample_count: 24,
}

const eventsReport = {
  schema_version: 1,
  observed_at: '2026-07-17T08:00:00+00:00',
  count: 2,
  events: [
    { recorded_at: '2026-07-17T07:00:00+00:00', source: 'api', severity: 'info', message: 'heartbeat', correlation_id: null, deployment_id: null, campaign_id: null },
    { recorded_at: '2026-07-17T06:00:00+00:00', source: 'engine', severity: 'error', message: 'auth failed Bearer [REDACTED]', correlation_id: 'corr-9', deployment_id: null, campaign_id: null },
  ],
}

const benchmarksReport = {
  schema_version: 1,
  observed_at: '2026-07-17T08:00:00+00:00',
  count: 1,
  runs: [{
    run_id: 'run-1',
    declaration: { name: 'contract-campaign' },
    identity: { model_id: 'qwen2.5-7b-instruct', engine_id: 'llama.cpp', quantization: 'q8_0' },
    started_at: '2026-07-17T07:00:00+00:00',
    ended_at: '2026-07-17T07:02:00+00:00',
    status: 'completed',
    errors: [],
    checkpoint: [],
  }],
}

const analyticsReport = {
  schema_version: 1,
  observed_at: '2026-07-17T08:00:00+00:00',
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

async function mockDataRoutes(page: Page): Promise<void> {
  const respond = (body: unknown) => (route: Parameters<Parameters<Page['route']>[1]>[0]) =>
    route.fulfill({ body: JSON.stringify(body), contentType: 'application/json', status: 200 })
  await page.route(`${API}/api/v1/operations/metrics*`, async (route) => {
    const signalName = new URL(route.request().url()).searchParams.get('signal')
    const body = signalName !== null && signalName !== 'gpu_cache_usage'
      ? { ...metricsTrend, signal: signalName, unit: 'bytes' }
      : metricsTrend
    await route.fulfill({ body: JSON.stringify(body), contentType: 'application/json', status: 200 })
  })
  await page.route(`${API}/api/v1/operations/events*`, respond(eventsReport))
  await page.route(`${API}/api/v1/operations/benchmarks*`, respond(benchmarksReport))
  await page.route(`${API}/api/v1/operations/analytics`, respond(analyticsReport))
}

test('OUI-002/003/004 data workspaces render trends, redacted events, history, and analytics', async ({ page }, testInfo) => {
  await mockControl(page)
  await mockDataRoutes(page)
  await signIn(page)

  await page.getByRole('button', { name: 'Hardware' }).click()
  await expect(page.getByRole('heading', { name: 'Hardware trends' })).toBeVisible()
  await expect(page.getByText('Unit: percent')).toBeVisible()
  await expect(page.getByText('Fresh evidence')).toBeVisible()
  await expect(page.getByText('24 samples in window')).toBeVisible()
  await expect(page.getByRole('img', { name: /samples, mean 40%/ })).toBeVisible()
  await expect(page.getByRole('img', { name: 'Missing data interval' })).toBeVisible()
  await page.getByLabel('Signal').selectOption('free_bytes')
  await expect(page.getByText('Unit: bytes')).toBeVisible()
  await expectNoBlockingAccessibilityViolations(page)

  await page.getByRole('button', { name: 'Logs & Events' }).click()
  await expect(page.getByRole('heading', { name: 'Logs & events' })).toBeVisible()
  await expect(page.getByText(/auth failed Bearer \[REDACTED\]/)).toBeVisible()
  await expect(page.getByText(/corr-9/)).toBeVisible()
  await page.getByLabel('Severity').selectOption('info')
  await expect(page.getByText('heartbeat')).toBeVisible()
  await expect(page.getByText(/auth failed/)).toHaveCount(0)
  await expectNoBlockingAccessibilityViolations(page)

  await page.getByRole('button', { name: 'Benchmarks' }).click()
  await expect(page.getByRole('heading', { name: 'Benchmarks' })).toBeVisible()
  await expect(page.getByText('run-1')).toBeVisible()
  await expect(page.getByText('qwen2.5-7b-instruct')).toBeVisible()
  await expect(page.getByText('Completed')).toBeVisible()
  await expectNoBlockingAccessibilityViolations(page)

  await page.getByRole('button', { name: 'Analytics' }).click()
  await expect(page.getByRole('heading', { name: 'Analytics' })).toBeVisible()
  await expect(page.getByText('30-day window')).toBeVisible()
  await expect(page.getByText('120')).toBeVisible()
  await expect(page.getByText('run-1 → run-2')).toBeVisible()
  await expect(page.getByText('COMPARABLE')).toBeVisible()
  await expectNoBlockingAccessibilityViolations(page)
  await captureResponsiveEvidence(page, testInfo)
})
