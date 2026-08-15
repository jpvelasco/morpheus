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

export type MetricSourceState = 'available' | 'unavailable'

export interface MetricSourceStatus {
  source: string
  state: MetricSourceState
  reason: string | null
}

export interface MetricBucket {
  start: string
  end: string
  count: number
  min: number | null
  max: number | null
  mean: number | null
  p50: number | null
  p95: number | null
}

export interface MetricGap {
  start: string
  end: string
}

export type FreshnessState = 'fresh' | 'stale' | 'unavailable'

export interface MetricsFreshness {
  state: FreshnessState
  latest_observed_at: string | null
  age_seconds: number | null
}

export interface MetricsTrend {
  schema_version: number
  observed_at: string
  signal: string
  unit: string
  freshness: MetricsFreshness
  sources: MetricSourceStatus[]
  buckets: MetricBucket[]
  gaps: MetricGap[]
  sample_count: number
}

export type EventSeverity = 'info' | 'warn' | 'error'

export interface EventRecord {
  recorded_at: string
  source: string
  severity: EventSeverity
  message: string
  correlation_id: string | null
  deployment_id: string | null
  campaign_id: string | null
}

export interface EventsReport {
  schema_version: number
  observed_at: string
  count: number
  events: EventRecord[]
}

export interface BenchmarkRun {
  run_id: string
  declaration: Record<string, unknown>
  identity: Record<string, unknown>
  started_at: string
  ended_at: string | null
  status: string
  errors: string[]
  checkpoint: unknown[]
}

export interface BenchmarksReport {
  schema_version: number
  observed_at: string
  count: number
  runs: BenchmarkRun[]
}

export interface UsageSummary {
  requests: number
  successes: number
  cancellations: number
  errors: number
  prompt_tokens: number
  completion_tokens: number
  window_days: number
}

export interface Scorecard {
  run_id: string
  model_id: string
  engine_id: string
  quantization: string
  statistic: string
  sample_count: number
  ttft_seconds: number | null
  tokens_per_second: number | null
}

export interface ComparisonSide {
  value: number | null
  sample_count: number
  run_variation: number | null
}

export interface Comparison {
  baseline_run_id: string
  candidate_run_id: string
  classification: string
  classification_note: string
  metric: string
  statistic: string
  baseline: ComparisonSide
  candidate: ComparisonSide
  percent_change: number | null
}

export interface Regression {
  metric: string
  baseline_value: number
  candidate_value: number
  threshold_pct: number
  change_pct: number
}

export interface AnalyticsReport {
  schema_version: number
  observed_at: string
  usage: UsageSummary
  scorecards: Scorecard[]
  comparisons: Comparison[]
  regressions: Regression[]
}

export type SettingsKind = 'str' | 'int' | 'float' | 'bool' | 'path' | 'url' | 'port' | 'secret'

export interface SettingsEntry {
  key: string
  kind: SettingsKind
  label: string
  description: string
  current: unknown
  configured: boolean
  value_redacted: boolean
  editable: boolean
  source: string
  default: unknown
  restart_required: boolean
  validation: string
}

export interface SettingsJournal {
  applied_at: string | null
  applied: Record<string, string> | never[]
  rollback_available: boolean
}

export interface SettingsPayload {
  schema_version: number
  observed_at: string
  settings: SettingsEntry[]
  restart_required: boolean
  journal: SettingsJournal
}

export interface SettingsPlanIssue {
  key: string
  code: string
  message: string
}

export interface SettingsPlanChange {
  key: string
  before: unknown
  after: unknown
  restart_required: boolean
  kind: SettingsKind
}

export interface SettingsPlan {
  schema_version: number
  valid: boolean
  changes: SettingsPlanChange[]
  issues: SettingsPlanIssue[]
  restart_required: boolean
  description: string
}

export interface SettingsApplyResult {
  schema_version: number
  applied: Record<string, string>
  restart_required: boolean
}

export interface WorkflowStep {
  id: string
  label: string
  description: string
  preflight: string
  recovery: string
  confirm_required: boolean
}

export interface WorkflowDefinition {
  workflow_id: string
  label: string
  description: string
  steps: WorkflowStep[]
}

export type WorkflowState = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface WorkflowSessionStep extends WorkflowStep {
  outcome: 'succeeded' | 'failed' | 'skipped' | 'cancelled' | null
}

export interface WorkflowSession {
  session_id: string
  workflow_id: string
  label: string
  state: WorkflowState
  current_step_id: string | null
  current_step_label: string
  progress_percent: number
  cancel_requested: boolean
  error: string | null
  recovery_instruction: string | null
  started_at: string
  steps: WorkflowSessionStep[]
}

export interface WorkflowAuditEvent {
  recorded_at: string
  session_id: string
  workflow_id: string
  event: string
  step_id: string | null
  message: string | null
}

export interface WorkflowsPayload {
  schema_version: number
  observed_at: string
  workflows: WorkflowDefinition[]
  sessions: WorkflowSession[]
  audit_events: WorkflowAuditEvent[]
}

export interface WorkflowStartResult {
  schema_version: number
  started: boolean
  session: WorkflowSession
}

export interface WorkflowSessionResult {
  schema_version: number
  session: WorkflowSession
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

function parseSources(value: unknown): MetricSourceStatus[] {
  if (!Array.isArray(value)) throw new Error('Invalid source list')
  return value.map((candidate) => {
    const item = record(candidate)
    const state = string(item.state, 'source state')
    if (state !== 'available' && state !== 'unavailable') {
      throw new Error('Invalid source state')
    }
    return {
      source: string(item.source, 'source name'),
      state: state as MetricSourceState,
      reason: item.reason === null ? null : string(item.reason, 'source reason'),
    }
  })
}

function parseBuckets(value: unknown): MetricBucket[] {
  if (!Array.isArray(value)) throw new Error('Invalid bucket list')
  return value.map((candidate) => {
    const item = record(candidate)
    return {
      start: string(item.start, 'bucket start'),
      end: string(item.end, 'bucket end'),
      count: number(item.count, 'bucket count'),
      min: numberOrNull(item.min, 'bucket minimum'),
      max: numberOrNull(item.max, 'bucket maximum'),
      mean: numberOrNull(item.mean, 'bucket mean'),
      p50: numberOrNull(item.p50, 'bucket median'),
      p95: numberOrNull(item.p95, 'bucket p95'),
    }
  })
}

function parseGaps(value: unknown): MetricGap[] {
  if (!Array.isArray(value)) throw new Error('Invalid gap list')
  return value.map((candidate) => {
    const item = record(candidate)
    return { start: string(item.start, 'gap start'), end: string(item.end, 'gap end') }
  })
}

export function parseMetricsTrend(value: unknown): MetricsTrend {
  const item = record(value)
  const freshness = record(item.freshness)
  const freshnessState = string(freshness.state, 'freshness state')
  if (!['fresh', 'stale', 'unavailable'].includes(freshnessState)) {
    throw new Error('Invalid freshness state')
  }
  return {
    schema_version: number(item.schema_version, 'metrics schema version'),
    observed_at: string(item.observed_at, 'metrics timestamp'),
    signal: string(item.signal, 'metrics signal'),
    unit: string(item.unit, 'metrics unit'),
    freshness: {
      state: freshnessState as FreshnessState,
      latest_observed_at: freshness.latest_observed_at === null
        ? null
        : string(freshness.latest_observed_at, 'latest sample timestamp'),
      age_seconds: numberOrNull(freshness.age_seconds, 'sample age'),
    },
    sources: parseSources(item.sources),
    buckets: parseBuckets(item.buckets),
    gaps: parseGaps(item.gaps),
    sample_count: number(item.sample_count, 'sample count'),
  }
}

function parseEvents(value: unknown): EventRecord[] {
  if (!Array.isArray(value)) throw new Error('Invalid event list')
  return value.map((candidate) => {
    const item = record(candidate)
    const severity = string(item.severity, 'event severity')
    if (!['info', 'warn', 'error'].includes(severity)) throw new Error('Invalid event severity')
    return {
      recorded_at: string(item.recorded_at, 'event timestamp'),
      source: string(item.source, 'event source'),
      severity: severity as EventSeverity,
      message: string(item.message, 'event message'),
      correlation_id: item.correlation_id === null ? null : string(item.correlation_id, 'correlation id'),
      deployment_id: item.deployment_id === null ? null : string(item.deployment_id, 'deployment id'),
      campaign_id: item.campaign_id === null ? null : string(item.campaign_id, 'campaign id'),
    }
  })
}

export function parseEventsReport(value: unknown): EventsReport {
  const item = record(value)
  return {
    schema_version: number(item.schema_version, 'events schema version'),
    observed_at: string(item.observed_at, 'events timestamp'),
    count: number(item.count, 'event count'),
    events: parseEvents(item.events),
  }
}

function parseRuns(value: unknown): BenchmarkRun[] {
  if (!Array.isArray(value)) throw new Error('Invalid run list')
  return value.map((candidate) => {
    const item = record(candidate)
    if (!Array.isArray(item.errors) || !item.errors.every((entry) => typeof entry === 'string')) {
      throw new Error('Invalid run errors')
    }
    if (!Array.isArray(item.checkpoint)) throw new Error('Invalid run checkpoint')
    return {
      run_id: string(item.run_id, 'run id'),
      declaration: record(item.declaration),
      identity: record(item.identity),
      started_at: string(item.started_at, 'run start'),
      ended_at: item.ended_at === null ? null : string(item.ended_at, 'run end'),
      status: string(item.status, 'run status'),
      errors: item.errors,
      checkpoint: item.checkpoint,
    }
  })
}

export function parseBenchmarksReport(value: unknown): BenchmarksReport {
  const item = record(value)
  return {
    schema_version: number(item.schema_version, 'benchmarks schema version'),
    observed_at: string(item.observed_at, 'benchmarks timestamp'),
    count: number(item.count, 'run count'),
    runs: parseRuns(item.runs),
  }
}

function parseScorecards(value: unknown): Scorecard[] {
  if (!Array.isArray(value)) throw new Error('Invalid scorecard list')
  return value.map((candidate) => {
    const item = record(candidate)
    return {
      run_id: string(item.run_id, 'scorecard run id'),
      model_id: string(item.model_id, 'scorecard model'),
      engine_id: string(item.engine_id, 'scorecard engine'),
      quantization: string(item.quantization, 'scorecard quantization'),
      statistic: string(item.statistic, 'scorecard statistic'),
      sample_count: number(item.sample_count, 'scorecard samples'),
      ttft_seconds: numberOrNull(item.ttft_seconds, 'scorecard ttft'),
      tokens_per_second: numberOrNull(item.tokens_per_second, 'scorecard throughput'),
    }
  })
}

function parseComparisons(value: unknown): Comparison[] {
  if (!Array.isArray(value)) throw new Error('Invalid comparison list')
  return value.map((candidate) => {
    const item = record(candidate)
    const baseline = record(item.baseline)
    const candidateSide = record(item.candidate)
    return {
      baseline_run_id: string(item.baseline_run_id, 'baseline run id'),
      candidate_run_id: string(item.candidate_run_id, 'candidate run id'),
      classification: string(item.classification, 'comparison classification'),
      classification_note: string(item.classification_note, 'comparison note'),
      metric: string(item.metric, 'comparison metric'),
      statistic: string(item.statistic, 'comparison statistic'),
      baseline: {
        value: numberOrNull(baseline.value, 'baseline value'),
        sample_count: number(baseline.sample_count, 'baseline samples'),
        run_variation: numberOrNull(baseline.run_variation, 'baseline variation'),
      },
      candidate: {
        value: numberOrNull(candidateSide.value, 'candidate value'),
        sample_count: number(candidateSide.sample_count, 'candidate samples'),
        run_variation: numberOrNull(candidateSide.run_variation, 'candidate variation'),
      },
      percent_change: numberOrNull(item.percent_change, 'percent change'),
    }
  })
}

function parseRegressions(value: unknown): Regression[] {
  if (!Array.isArray(value)) throw new Error('Invalid regression list')
  return value.map((candidate) => {
    const item = record(candidate)
    return {
      metric: string(item.metric, 'regression metric'),
      baseline_value: number(item.baseline_value, 'regression baseline'),
      candidate_value: number(item.candidate_value, 'regression candidate'),
      threshold_pct: number(item.threshold_pct, 'regression threshold'),
      change_pct: number(item.change_pct, 'regression change'),
    }
  })
}

export function parseAnalyticsReport(value: unknown): AnalyticsReport {
  const item = record(value)
  const usage = record(item.usage)
  return {
    schema_version: number(item.schema_version, 'analytics schema version'),
    observed_at: string(item.observed_at, 'analytics timestamp'),
    usage: {
      requests: number(usage.requests, 'usage requests'),
      successes: number(usage.successes, 'usage successes'),
      cancellations: number(usage.cancellations, 'usage cancellations'),
      errors: number(usage.errors, 'usage errors'),
      prompt_tokens: number(usage.prompt_tokens, 'usage prompt tokens'),
      completion_tokens: number(usage.completion_tokens, 'usage completion tokens'),
      window_days: number(usage.window_days, 'usage window'),
    },
    scorecards: parseScorecards(item.scorecards),
    comparisons: parseComparisons(item.comparisons),
    regressions: parseRegressions(item.regressions),
  }
}

function csrfToken(): string {
  const item = document.cookie.split('; ').find((value) => value.startsWith('morpheus_csrf='))
  return item ? decodeURIComponent(item.slice('morpheus_csrf='.length)) : ''
}

function boolean(value: unknown, field: string): boolean {
  if (typeof value !== 'boolean') throw new Error(`Invalid ${field}`)
  return value
}

const SETTINGS_KINDS = ['str', 'int', 'float', 'bool', 'path', 'url', 'port', 'secret']

export function parseSettingsPayload(value: unknown): SettingsPayload {
  const item = record(value)
  if (!Array.isArray(item.settings)) throw new Error('Invalid settings list')
  const journal = record(item.journal)
  const applied = journal.applied
  if (!Array.isArray(applied) && (typeof applied !== 'object' || applied === null)) {
    throw new Error('Invalid settings journal')
  }
  return {
    schema_version: number(item.schema_version, 'settings schema version'),
    observed_at: string(item.observed_at, 'settings timestamp'),
    settings: item.settings.map((candidate): SettingsEntry => {
      const entry = record(candidate)
      const kind = string(entry.kind, 'settings kind')
      if (!SETTINGS_KINDS.includes(kind)) throw new Error('Invalid settings kind')
      return {
        key: string(entry.key, 'settings key'),
        kind: kind as SettingsKind,
        label: string(entry.label, 'settings label'),
        description: string(entry.description, 'settings description'),
        current: entry.current,
        configured: boolean(entry.configured, 'settings configured'),
        value_redacted: boolean(entry.value_redacted, 'settings redaction'),
        editable: boolean(entry.editable, 'settings editable'),
        source: string(entry.source, 'settings source'),
        default: entry.default,
        restart_required: boolean(entry.restart_required, 'settings restart'),
        validation: string(entry.validation, 'settings validation'),
      }
    }),
    restart_required: boolean(item.restart_required, 'settings restart required'),
    journal: {
      applied_at: journal.applied_at === null ? null : string(journal.applied_at, 'settings applied at'),
      applied: applied as Record<string, string> | never[],
      rollback_available: boolean(journal.rollback_available, 'settings rollback available'),
    },
  }
}

export function parseSettingsPlan(value: unknown): SettingsPlan {
  const item = record(value)
  const parseIssue = (candidate: unknown): SettingsPlanIssue => {
    const issue = record(candidate)
    return {
      key: string(issue.key, 'plan issue key'),
      code: string(issue.code, 'plan issue code'),
      message: string(issue.message, 'plan issue message'),
    }
  }
  if (!Array.isArray(item.issues) || !Array.isArray(item.changes)) {
    throw new Error('Invalid settings plan')
  }
  return {
    schema_version: number(item.schema_version, 'plan schema version'),
    valid: boolean(item.valid, 'plan validity'),
    changes: item.changes.map((candidate): SettingsPlanChange => {
      const change = record(candidate)
      const kind = string(change.kind, 'change kind')
      if (!SETTINGS_KINDS.includes(kind)) throw new Error('Invalid change kind')
      return {
        key: string(change.key, 'change key'),
        before: change.before,
        after: change.after,
        restart_required: boolean(change.restart_required, 'change restart'),
        kind: kind as SettingsKind,
      }
    }),
    issues: item.issues.map(parseIssue),
    restart_required: boolean(item.restart_required, 'plan restart'),
    description: string(item.description, 'plan description'),
  }
}

const WORKFLOW_STATES = ['pending', 'running', 'succeeded', 'failed', 'cancelled']
const STEP_OUTCOMES = ['succeeded', 'failed', 'skipped', 'cancelled']

function parseWorkflowSteps(value: unknown): WorkflowSessionStep[] {
  if (!Array.isArray(value)) throw new Error('Invalid workflow steps')
  return value.map((candidate) => {
    const step = record(candidate)
    const outcome = step.outcome ?? null
    if (outcome !== null && (typeof outcome !== 'string' || !STEP_OUTCOMES.includes(outcome))) {
      throw new Error('Invalid step outcome')
    }
    return {
      id: string(step.id, 'step id'),
      label: string(step.label, 'step label'),
      description: string(step.description, 'step description'),
      preflight: string(step.preflight, 'step preflight'),
      recovery: string(step.recovery, 'step recovery'),
      confirm_required: boolean(step.confirm_required, 'step confirmation'),
      outcome: outcome === null ? null : (outcome as WorkflowSessionStep['outcome']),
    }
  })
}

function parseWorkflowSession(value: unknown): WorkflowSession {
  const item = record(value)
  const state = string(item.state, 'workflow state')
  if (!WORKFLOW_STATES.includes(state)) throw new Error('Invalid workflow state')
  return {
    session_id: string(item.session_id, 'session id'),
    workflow_id: string(item.workflow_id, 'workflow id'),
    label: string(item.label, 'workflow label'),
    state: state as WorkflowState,
    current_step_id: item.current_step_id === null ? null : string(item.current_step_id, 'current step'),
    current_step_label: string(item.current_step_label, 'current step label'),
    progress_percent: number(item.progress_percent, 'workflow progress'),
    cancel_requested: boolean(item.cancel_requested, 'cancel requested'),
    error: item.error === null ? null : string(item.error, 'workflow error'),
    recovery_instruction: item.recovery_instruction === null
      ? null
      : string(item.recovery_instruction, 'recovery instruction'),
    started_at: string(item.started_at, 'workflow start'),
    steps: parseWorkflowSteps(item.steps),
  }
}

function parseWorkflowDefinitions(value: unknown): WorkflowDefinition[] {
  if (!Array.isArray(value)) throw new Error('Invalid workflow list')
  return value.map((candidate) => {
    const item = record(candidate)
    return {
      workflow_id: string(item.workflow_id, 'workflow id'),
      label: string(item.label, 'workflow label'),
      description: string(item.description, 'workflow description'),
      steps: parseWorkflowSteps(item.steps),
    }
  })
}

function parseAuditEvents(value: unknown): WorkflowAuditEvent[] {
  if (!Array.isArray(value)) throw new Error('Invalid audit list')
  return value.map((candidate) => {
    const item = record(candidate)
    return {
      recorded_at: string(item.recorded_at, 'audit timestamp'),
      session_id: string(item.session_id, 'audit session'),
      workflow_id: string(item.workflow_id, 'audit workflow'),
      event: string(item.event, 'audit event'),
      step_id: item.step_id === null ? null : string(item.step_id, 'audit step'),
      message: item.message === null ? null : string(item.message, 'audit message'),
    }
  })
}

export function parseWorkflowsPayload(value: unknown): WorkflowsPayload {
  const item = record(value)
  if (!Array.isArray(item.sessions)) throw new Error('Invalid workflow session list')
  return {
    schema_version: number(item.schema_version, 'workflows schema version'),
    observed_at: string(item.observed_at, 'workflows timestamp'),
    workflows: parseWorkflowDefinitions(item.workflows),
    sessions: item.sessions.map(parseWorkflowSession),
    audit_events: parseAuditEvents(item.audit_events),
  }
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

export async function fetchMetricsTrend(
  signal: AbortSignal,
  signalName: string,
  windowSeconds = 3600,
  hours = 6,
): Promise<MetricsTrend> {
  const query = new URLSearchParams({
    signal: signalName,
    window_seconds: String(windowSeconds),
    hours: String(hours),
  })
  const response = await fetch(`${API_BASE}/api/v1/operations/metrics?${query.toString()}`, {
    credentials: 'include',
    signal,
  })
  requireSuccess(response)
  return parseMetricsTrend(await response.json())
}

export async function fetchEvents(limit = 200, signal?: AbortSignal): Promise<EventsReport> {
  const response = await fetch(`${API_BASE}/api/v1/operations/events?limit=${String(limit)}`, {
    credentials: 'include',
    signal,
  })
  requireSuccess(response)
  return parseEventsReport(await response.json())
}

export async function fetchBenchmarks(limit = 20, signal?: AbortSignal): Promise<BenchmarksReport> {
  const response = await fetch(`${API_BASE}/api/v1/operations/benchmarks?limit=${String(limit)}`, {
    credentials: 'include',
    signal,
  })
  requireSuccess(response)
  return parseBenchmarksReport(await response.json())
}

export async function fetchAnalytics(signal?: AbortSignal): Promise<AnalyticsReport> {
  const response = await fetch(`${API_BASE}/api/v1/operations/analytics`, {
    credentials: 'include',
    signal,
  })
  requireSuccess(response)
  return parseAnalyticsReport(await response.json())
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

export async function fetchSettings(signal?: AbortSignal): Promise<SettingsPayload> {
  const response = await fetch(`${API_BASE}/api/v1/operations/settings`, {
    credentials: 'include',
    signal,
  })
  requireSuccess(response)
  return parseSettingsPayload(await response.json())
}

export async function planSettings(changes: Record<string, unknown>): Promise<SettingsPlan> {
  const response = await fetch(`${API_BASE}/api/v1/operations/settings/plan`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() },
    body: JSON.stringify({ changes }),
  })
  requireSuccess(response)
  return parseSettingsPlan(await response.json())
}

export async function applySettings(changes: Record<string, unknown>): Promise<SettingsApplyResult> {
  const response = await fetch(`${API_BASE}/api/v1/operations/settings/apply`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() },
    body: JSON.stringify({ changes }),
  })
  requireSuccess(response)
  return (await response.json()) as SettingsApplyResult
}

export async function rollbackSettings(): Promise<{ rolled_back: boolean }> {
  const response = await fetch(`${API_BASE}/api/v1/operations/settings/rollback`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'X-CSRF-Token': csrfToken() },
  })
  requireSuccess(response)
  return (await response.json()) as { rolled_back: boolean }
}

export async function fetchWorkflows(signal?: AbortSignal): Promise<WorkflowsPayload> {
  const response = await fetch(`${API_BASE}/api/v1/operations/workflows`, {
    credentials: 'include',
    signal,
  })
  requireSuccess(response)
  return parseWorkflowsPayload(await response.json())
}

export async function startWorkflow(workflowId: string, confirmed: boolean): Promise<WorkflowStartResult> {
  const response = await fetch(`${API_BASE}/api/v1/operations/workflows/${workflowId}/start`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() },
    body: JSON.stringify({ confirmed }),
  })
  requireSuccess(response)
  const payload = record(await response.json())
  return {
    schema_version: number(payload.schema_version, 'workflow start schema version'),
    started: boolean(payload.started, 'workflow started'),
    session: parseWorkflowSession(payload.session),
  }
}

export async function cancelWorkflow(workflowId: string): Promise<{ cancelled: boolean }> {
  const response = await fetch(`${API_BASE}/api/v1/operations/workflows/${workflowId}/cancel`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'X-CSRF-Token': csrfToken() },
  })
  requireSuccess(response)
  return (await response.json()) as { cancelled: boolean }
}

export async function fetchWorkflowSession(
  workflowId: string,
  signal?: AbortSignal,
): Promise<WorkflowSession | null> {
  const response = await fetch(`${API_BASE}/api/v1/operations/workflows/${workflowId}/session`, {
    credentials: 'include',
    signal,
  })
  if (response.status === 400) return null
  requireSuccess(response)
  const payload = record(await response.json())
  return parseWorkflowSession(payload.session)
}
