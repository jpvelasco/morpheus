import http from 'k6/http'
import { check } from 'k6'
import exec from 'k6/execution'
import { Counter, Rate, Trend } from 'k6/metrics'

const workload = JSON.parse(open('/scripts/workload.json'))
const profileName = __ENV.WORKLOAD_PROFILE || 'dev'
const profile = workload.profiles[profileName]
if (!profile) throw new Error('Unknown fixed workload profile')

const targets = {
  direct: 'http://fixture:8000',
  proxied: 'http://telemetry:7410',
}
const target = targets[__ENV.LOAD_PHASE]
if (!target) throw new Error('LOAD_PHASE must select a fixed internal target')
const summaryPath = __ENV.SUMMARY_PATH
if (!/^\/artifacts\/(direct|proxied)\.json$/.test(summaryPath)) {
  throw new Error('SUMMARY_PATH must be the fixed phase evidence path')
}
const apiKey = open('/run/secrets/load-api-key').trim()
if (!apiKey) throw new Error('Synthetic load credential file is empty')

const waiting = new Trend('morpheus_waiting_ms', true)
const iterations = new Counter('morpheus_iterations')
const requests = new Counter('morpheus_requests')
const checks = new Rate('morpheus_checks')
const failed = new Rate('morpheus_failed')

export const options = {
  discardResponseBodies: false,
  scenarios: {
    warmup: {
      executor: 'constant-vus',
      exec: 'warmup',
      vus: profile.vus,
      duration: profile.warmup_duration,
      gracefulStop: profile.graceful_stop,
    },
    measurement: {
      executor: 'constant-vus',
      exec: 'measurement',
      vus: profile.vus,
      startTime: profile.warmup_duration,
      duration: profile.measurement_duration,
      gracefulStop: profile.graceful_stop,
    },
  },
  thresholds: {
    morpheus_checks: [{ threshold: 'rate==1', abortOnFail: true, delayAbortEval: '2s' }],
    morpheus_failed: [{ threshold: 'rate==0', abortOnFail: true, delayAbortEval: '2s' }],
    morpheus_waiting_ms: [
      { threshold: `p(99)<${String(profile.max_p99_ms)}`, abortOnFail: true, delayAbortEval: '2s' },
    ],
  },
}

function request(record) {
  const stream = exec.scenario.iterationInTest % 10 < workload.request_mix.stream * 10
  const payload = {
    model: workload.model,
    messages: [{ role: 'user', content: workload.payload_shape.prompt }],
    max_tokens: workload.payload_shape.max_tokens,
    stream,
    morpheus_fixture_mode: stream ? 'slow_stream' : 'slow',
    morpheus_fixture_delay_ms: workload.fixture_delay_ms,
  }
  const response = http.post(`${target}/v1/chat/completions`, JSON.stringify(payload), {
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    tags: { request_kind: stream ? 'stream' : 'nonstream' },
    timeout: '5s',
  })
  const valid = check(response, {
    'status is 200': (item) => item.status === 200,
    'fixture body is complete': (item) =>
      stream ? item.body.includes('data: [DONE]') : item.body.includes('fixture-response'),
  })
  if (record) {
    waiting.add(response.timings.waiting)
    iterations.add(1)
    requests.add(1)
    checks.add(valid)
    failed.add(response.status !== 200)
  }
}

export function warmup() {
  request(false)
}

export function measurement() {
  request(true)
}

export function handleSummary(data) {
  const metric = (name) => {
    if (!data.metrics[name]) throw new Error(`Missing measurement metric: ${name}`)
    return data.metrics[name]
  }
  const evidence = {
    schema_version: 1,
    workload_id: workload.workload_id,
    workload_profile: profileName,
    phase: __ENV.LOAD_PHASE,
    metrics: {
      http_req_waiting: metric('morpheus_waiting_ms'),
      iterations: metric('morpheus_iterations'),
      checks: metric('morpheus_checks'),
      http_req_failed: metric('morpheus_failed'),
      http_reqs: metric('morpheus_requests'),
    },
  }
  return { [summaryPath]: JSON.stringify(evidence, null, 2) }
}
