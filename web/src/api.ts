export type HealthState =
  | 'unknown'
  | 'starting'
  | 'ready'
  | 'degraded'
  | 'unreachable'
  | 'incompatible'

export interface Evidence {
  state: HealthState
  reason_code: string
  summary: string
  observed_at: string
  duration_ms: number
  source: string
  expires_at: string
  next_action: string | null
}

export interface ModelIdentity {
  root: string | null
  aliases: string[]
  context_window: number | null
}

export type CapabilityState = 'available' | 'disabled' | 'unhealthy' | 'blocked'

export interface CapabilityStatus {
  state: CapabilityState
  blockers: string[]
}

export interface HostUnavailable {
  status: 'unavailable'
  reason: string
}

export interface HostAvailable {
  status: 'available' | 'degraded'
  gpu?: {
    memory_total_mib: number
    memory_used_mib: number
    utilization_percent: number
    temperature_c: number
  }
  memory?: { total_bytes: number; available_bytes: number }
  disk?: { total_bytes: number; free_bytes: number }
}

export type DiagnosticStatus = 'pass' | 'fail' | 'unavailable'

export interface DiagnosticCheck {
  code: string
  status: DiagnosticStatus
  reason_code: string
  summary: string
  observed_at: string
  freshness: 'current' | 'stale'
  next_action: string | null
}

export interface Diagnostics {
  status: 'ready' | 'degraded' | 'unhealthy'
  observed_at: string
  checks: DiagnosticCheck[]
}

export interface Overview {
  observed_at: string
  inference: Evidence
  models: ModelIdentity[]
  capabilities: Record<string, CapabilityStatus>
  host: HostUnavailable | HostAvailable
  diagnostics: Diagnostics
  external_controls: never[]
}

export type WorkspaceState = 'ready' | 'partial' | 'empty' | 'unavailable'

export interface QueryModel {
  schema: string
  version: number
}

export interface Workspace {
  id: string
  label: string
  state: WorkspaceState
  query_model: QueryModel | null
}

export interface NavigationManifest {
  schema_version: number
  observed_at: string
  workspaces: Workspace[]
}

export type ControlState = 'configured' | 'running' | 'healthy' | 'usable'

export interface ControlStatus {
  control: string
  state: ControlState
  configured: boolean
  running: boolean
  healthy: boolean
  usable: boolean
  blockers: string[]
}

export interface ControlsReport {
  schema_version: number
  observed_at: string
  core_ready: boolean
  controls: ControlStatus[]
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:7400'

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('The control API returned an incompatible response')
  }
  return value as Record<string, unknown>
}

function string(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new Error(`Invalid ${field}`)
  return value
}

function number(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`Invalid ${field}`)
  return value
}

function numberOrNull(value: unknown, field: string): number | null {
  if (value === null) return null
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`Invalid ${field}`)
  return value
}

function parseEvidence(value: unknown): Evidence {
  const item = record(value)
  const state = string(item.state, 'health state')
  if (!['unknown', 'starting', 'ready', 'degraded', 'unreachable', 'incompatible'].includes(state)) {
    throw new Error('Invalid health state')
  }
  return {
    state: state as HealthState,
    reason_code: string(item.reason_code, 'reason code'),
    summary: string(item.summary, 'health summary'),
    observed_at: string(item.observed_at, 'observed timestamp'),
    duration_ms: numberOrNull(item.duration_ms, 'probe duration') ?? 0,
    source: string(item.source, 'evidence source'),
    expires_at: string(item.expires_at, 'expiry timestamp'),
    next_action: item.next_action === null ? null : string(item.next_action, 'next action'),
  }
}

function parseModels(value: unknown): ModelIdentity[] {
  if (!Array.isArray(value)) throw new Error('Invalid model list')
  return value.map((candidate) => {
    const item = record(candidate)
    if (!Array.isArray(item.aliases) || !item.aliases.every((alias) => typeof alias === 'string')) {
      throw new Error('Invalid model aliases')
    }
    return {
      root: item.root === null ? null : string(item.root, 'root model'),
      aliases: item.aliases,
      context_window: numberOrNull(item.context_window, 'context window'),
    }
  })
}

function parseCapabilities(value: unknown): Record<string, CapabilityStatus> {
  const items = record(value)
  return Object.fromEntries(
    Object.entries(items).map(([name, candidate]) => {
      const item = record(candidate)
      const state = string(item.state, 'capability state')
      if (!['available', 'disabled', 'unhealthy', 'blocked'].includes(state)) {
        throw new Error('Invalid capability state')
      }
      if (!Array.isArray(item.blockers) || !item.blockers.every((entry) => typeof entry === 'string')) {
        throw new Error('Invalid capability blockers')
      }
      return [name, { state: state as CapabilityState, blockers: item.blockers }]
    }),
  )
}

function parseDiagnostics(value: unknown): Diagnostics {
  const item = record(value)
  const status = string(item.status, 'diagnostics status')
  if (!['ready', 'degraded', 'unhealthy'].includes(status)) {
    throw new Error('Invalid diagnostics status')
  }
  if (!Array.isArray(item.checks)) throw new Error('Invalid diagnostic checks')
  const checks = item.checks.map((candidate): DiagnosticCheck => {
    const check = record(candidate)
    const checkStatus = string(check.status, 'diagnostic check status')
    if (!['pass', 'fail', 'unavailable'].includes(checkStatus)) {
      throw new Error('Invalid diagnostic check status')
    }
    const freshness = string(check.freshness, 'diagnostic freshness')
    if (freshness !== 'current' && freshness !== 'stale') {
      throw new Error('Invalid diagnostic freshness')
    }
    return {
      code: string(check.code, 'diagnostic code'),
      status: checkStatus as DiagnosticStatus,
      reason_code: string(check.reason_code, 'diagnostic reason'),
      summary: string(check.summary, 'diagnostic summary'),
      observed_at: string(check.observed_at, 'diagnostic timestamp'),
      freshness,
      next_action: check.next_action === null ? null : string(check.next_action, 'diagnostic next action'),
    }
  })
  return {
    status: status as Diagnostics['status'],
    observed_at: string(item.observed_at, 'diagnostics timestamp'),
    checks,
  }
}

export function parseOverview(value: unknown): Overview {
  const item = record(value)
  const host = record(item.host)
  if (host.status !== 'unavailable' && host.status !== 'available' && host.status !== 'degraded') {
    throw new Error('Invalid host status')
  }
  return {
    observed_at: string(item.observed_at, 'overview timestamp'),
    inference: parseEvidence(item.inference),
    models: parseModels(item.models),
    capabilities: parseCapabilities(item.capabilities),
    host: host as unknown as HostUnavailable | HostAvailable,
    diagnostics: parseDiagnostics(item.diagnostics),
    external_controls: [],
  }
}

function parseWorkspaces(value: unknown): Workspace[] {
  if (!Array.isArray(value)) throw new Error('Invalid workspace list')
  return value.map((candidate) => {
    const item = record(candidate)
    const state = string(item.state, 'workspace state')
    if (!['ready', 'partial', 'empty', 'unavailable'].includes(state)) {
      throw new Error('Invalid workspace state')
    }
    const queryModel = item.query_model
    if (queryModel !== null) {
      const model = record(queryModel)
      return {
        id: string(item.id, 'workspace id'),
        label: string(item.label, 'workspace label'),
        state: state as WorkspaceState,
        query_model: {
          schema: string(model.schema, 'query model schema'),
          version: number(model.version, 'query model version'),
        },
      }
    }
    return {
      id: string(item.id, 'workspace id'),
      label: string(item.label, 'workspace label'),
      state: state as WorkspaceState,
      query_model: null,
    }
  })
}

export function parseNavigation(value: unknown): NavigationManifest {
  const item = record(value)
  return {
    schema_version: number(item.schema_version, 'navigation schema version'),
    observed_at: string(item.observed_at, 'navigation timestamp'),
    workspaces: parseWorkspaces(item.workspaces),
  }
}

function parseControlsReport(value: unknown): ControlStatus[] {
  if (!Array.isArray(value)) throw new Error('Invalid control list')
  return value.map((candidate) => {
      const item = record(candidate)
      const state = string(item.state, 'control state')
      if (!['configured', 'running', 'healthy', 'usable'].includes(state)) {
        throw new Error('Invalid control state')
      }
      const booleanFlag = (flag: unknown, field: string): boolean => {
        if (typeof flag !== 'boolean') throw new Error(`Invalid ${field}`)
        return flag
      }
      if (!Array.isArray(item.blockers) || !item.blockers.every((entry) => typeof entry === 'string')) {
        throw new Error('Invalid control blockers')
      }
      return {
        control: string(item.control, 'control name'),
        state: state as ControlState,
        configured: booleanFlag(item.configured, 'control configured'),
        running: booleanFlag(item.running, 'control running'),
        healthy: booleanFlag(item.healthy, 'control healthy'),
        usable: booleanFlag(item.usable, 'control usable'),
        blockers: item.blockers,
      }
    })
}

export function parseControls(value: unknown): ControlsReport {
  const item = record(value)
  const coreReady = item.core_ready
  if (typeof coreReady !== 'boolean') throw new Error('Invalid core readiness')
  return {
    schema_version: number(item.schema_version, 'controls schema version'),
    observed_at: string(item.observed_at, 'controls timestamp'),
    core_ready: coreReady,
    controls: parseControlsReport(item.controls),
  }
}

function csrfToken(): string {
  const item = document.cookie.split('; ').find((value) => value.startsWith('morpheus_csrf='))
  return item ? decodeURIComponent(item.slice('morpheus_csrf='.length)) : ''
}

function requireSuccess(response: Response): void {
  if (response.status === 401) throw new Error('Authentication failed')
  if (!response.ok) throw new Error(`Control API failed with HTTP ${String(response.status)}`)
}

export async function createSession(apiKey: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/session`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key: apiKey }),
  })
  requireSuccess(response)
}

export async function destroySession(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/session`, {
    method: 'DELETE',
    credentials: 'include',
    headers: { 'X-CSRF-Token': csrfToken() },
  })
  requireSuccess(response)
}

export async function fetchOverview(signal?: AbortSignal): Promise<Overview> {
  const response = await fetch(`${API_BASE}/api/v1/overview`, {
    credentials: 'include',
    signal,
  })
  requireSuccess(response)
  return parseOverview(await response.json())
}

export async function fetchNavigation(signal?: AbortSignal): Promise<NavigationManifest> {
  const response = await fetch(`${API_BASE}/api/v1/operations/navigation`, {
    credentials: 'include',
    signal,
  })
  requireSuccess(response)
  return parseNavigation(await response.json())
}

export async function fetchControls(signal?: AbortSignal): Promise<ControlsReport> {
  const response = await fetch(`${API_BASE}/api/v1/operations/controls`, {
    credentials: 'include',
    signal,
  })
  requireSuccess(response)
  return parseControls(await response.json())
}

export interface RecommendationContribution {
  metric: string
  weight: number
  calibrated: number
  effective_confidence: number
  contribution: number
  comparability: 'comparable' | 'incomparable' | 'missing'
}

export interface RecommendationTuple {
  candidate: {
    model_id: string
    quantization: string
    engine_id: string
    context_window: number
    concurrency: number
  }
  score: number
  contributions: RecommendationContribution[]
  summary: string
}

export interface RecommendationRecord {
  record_id: string
  created_at: string
  profile: { id: string; version: string; name: string }
  reference_machine_id: string
  ranked: RecommendationTuple[]
  excluded: Array<{
    candidate: RecommendationTuple['candidate']
    violations: Array<{ code: string; detail: string }>
  }>
  summary: string
}

export interface RecommendationPayload {
  recommendation: RecommendationRecord
}

export async function fetchLatestRecommendation(signal?: AbortSignal): Promise<RecommendationRecord | null> {
  const response = await fetch(`${API_BASE}/api/v1/recommendations/latest`, {
    credentials: 'include',
    signal,
  })
  if (response.status === 404) return null
  requireSuccess(response)
  const payload = (await response.json()) as RecommendationPayload
  return payload.recommendation
}
