import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'

const artifactRoot = path.resolve(process.env.BROWSER_ARTIFACT_ROOT ?? '../artifacts/browser-dev')
const port = Number(process.env.BROWSER_WEB_PORT ?? '17401')
const baseURL = `http://127.0.0.1:${String(port)}`

export default defineConfig({
  testDir: './e2e',
  outputDir: path.join(artifactRoot, 'test-results'),
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [
    ['line'],
    ['json', { outputFile: path.join(artifactRoot, 'playwright-report.json') }],
  ],
  expect: { timeout: 5_000 },
  use: {
    baseURL,
    colorScheme: 'light',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: `npm exec vite build && npm exec vite preview -- --host 127.0.0.1 --port ${String(port)} --strictPort`,
    env: {
      BROWSER_DIST_ROOT: '/tmp/morpheus-browser-dist',
      VITE_CACHE_DIR: '/tmp/morpheus-vite-cache',
    },
    reuseExistingServer: false,
    timeout: 30_000,
    url: baseURL,
  },
  projects: [
    {
      name: 'chromium-desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'firefox-desktop',
      use: { ...devices['Desktop Firefox'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'webkit-desktop',
      use: { ...devices['Desktop Safari'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'chromium-mobile',
      use: { ...devices['Pixel 5'] },
    },
  ],
})
