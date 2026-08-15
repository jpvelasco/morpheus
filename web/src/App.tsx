import {
  Activity,
  AlertTriangle,
  BarChart3,
  BookOpen,
  Boxes,
  CheckCircle2,
  Clock3,
  Cog,
  Cpu,
  Database,
  FlaskConical,
  Gauge,
  HeartPulse,
  Image as ImageIcon,
  LifeBuoy,
  LogOut,
  RefreshCw,
  ScrollText,
  Search,
  Server,
  Settings2,
  ShieldCheck,
  Volume2,
  Workflow,
  type LucideIcon,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import {
  createSession,
  destroySession,
  fetchAnalytics,
  fetchBenchmarks,
  fetchControls,
  fetchEvents,
  fetchLatestRecommendation,
  fetchMetricsTrend,
  fetchNavigation,
  fetchOverview,
  type AnalyticsReport,
  type BenchmarksReport,
  type CapabilityState,
  type ControlState,
  type ControlsReport,
  type EventRecord,
  type EventsReport,
  type HealthState,
  type HostAvailable,
  type HostUnavailable,
  type MetricBucket,
  type MetricGap,
  type MetricsTrend,
  type NavigationManifest,
  type Overview,
  type RecommendationRecord,
  type Workspace,
  type WorkspaceState,
} from './api'
import './styles.css'

const SESSION_MARKER = 'morpheus.session.active'

const FALLBACK_WORKSPACES: Workspace[] = [
  'overview',
  'hardware',
  'models',
  'engines',
  'runtime',
  'benchmarks',
  'analytics',
  'logs_events',
  'diagnostics',
  'settings',
  'recovery',
].map((id) => ({ id, label: humanName(id), state: 'unavailable', query_model: null }))

function humanName(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

type StatusState = HealthState | CapabilityState | ControlState | WorkspaceState | 'unavailable'

const STATUS_ICONS: Record<StatusState, LucideIcon> = {
  ready: CheckCircle2,
  available: CheckCircle2,
  usable: CheckCircle2,
  healthy: CheckCircle2,
  starting: Clock3,
  degraded: AlertTriangle,
  blocked: AlertTriangle,
  unreachable: AlertTriangle,
  incompatible: AlertTriangle,
  unhealthy: AlertTriangle,
  unknown: Clock3,
  disabled: Clock3,
  unavailable: Clock3,
  running: Clock3,
  configured: Settings2,
  partial: Clock3,
  empty: Clock3,
}

function Status({ state }: { state: StatusState }) {
  const Icon = STATUS_ICONS[state]
  return (
    <span className={`status status-${state}`}>
      <Icon aria-hidden="true" size={15} />
      {humanName(state)}
    </span>
  )
}

const WORKSPACE_ICONS: Record<string, LucideIcon> = {
  overview: Activity,
  hardware: Cpu,
  models: Boxes,
  engines: Cog,
  runtime: Server,
  benchmarks: Gauge,
  analytics: BarChart3,
  logs_events: ScrollText,
  diagnostics: HeartPulse,
  settings: Settings2,
  recovery: LifeBuoy,
}

const CONTROL_ICONS: Record<string, LucideIcon> = {
  core: Activity,
  search: Search,
  voice: Volume2,
  telemetry: Gauge,
  workflows: Workflow,
  research: FlaskConical,
  rag: BookOpen,
  image_generation: ImageIcon,
}

function Login({ onLogin }: { onLogin: (token: string) => Promise<void> }) {
  const [key, setKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  function submit(event: FormEvent) {
    event.preventDefault()
    const token = key.trim()
    if (!token) return
    void authenticate(token)
  }
  async function authenticate(token: string) {
    try {
      await onLogin(token)
      setKey('')
      setError(null)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Authentication failed')
    }
  }
  return (
    <main className="login-shell">
      <form className="login-panel" onSubmit={submit}>
        <div className="brand-mark" aria-hidden="true"><Activity size={24} /></div>
        <h1>Morpheus</h1>
        <p className="login-subtitle">Operator access</p>
        <label htmlFor="api-key">API access key</label>
        <input
          id="api-key"
          name="api-key"
          type="password"
          autoComplete="current-password"
          value={key}
          onChange={(event) => { setKey(event.target.value) }}
          required
        />
        <button className="primary-command" type="submit"><ShieldCheck size={17} /> Sign in</button>
        {error && <p className="login-error" role="alert">{error}</p>}
      </form>
    </main>
  )
}

function OverviewPage({ overview }: { overview: Overview }) {
  const model = overview.models[0]
  const host = overview.host.status === 'unavailable' ? null : overview.host
  return (
    <div className="page-stack">
      <section className="summary-band" aria-labelledby="system-heading">
        <div>
          <p className="section-label">External inference</p>
          <h2 id="system-heading">System overview</h2>
        </div>
        <Status state={overview.inference.state} />
      </section>

      <section className="metrics-grid" aria-label="Operational metrics">
        <article className="metric-cell">
          <Server aria-hidden="true" />
          <span>Loaded model</span>
          <strong>{model?.aliases[0] ?? 'Not reported'}</strong>
          <small>{model?.root ?? 'Root identity unavailable'}</small>
        </article>
        <article className="metric-cell">
          <Gauge aria-hidden="true" />
          <span>Context window</span>
          <strong>{model?.context_window?.toLocaleString() ?? 'Unavailable'}</strong>
          <small>tokens</small>
        </article>
        <article className="metric-cell">
          <Cpu aria-hidden="true" />
          <span>GPU memory</span>
          <strong>{host?.gpu ? `${host.gpu.memory_used_mib.toLocaleString()} MiB` : 'Unavailable'}</strong>
          <small>{host?.gpu ? `${String(host.gpu.utilization_percent)}% utilization` : 'Runtime agent offline'}</small>
        </article>
        <article className="metric-cell">
          <Database aria-hidden="true" />
          <span>Storage</span>
          <strong>{host?.disk ? `${String(Math.round(host.disk.free_bytes / 1_073_741_824))} GiB` : 'Unavailable'}</strong>
          <small>free space</small>
        </article>
      </section>

      <section className="feature-section" aria-labelledby="features-heading">
        <div className="section-heading">
          <div>
            <p className="section-label">Morpheus-owned capabilities</p>
            <h2 id="features-heading">Feature status</h2>
          </div>
          <span>{Object.keys(overview.capabilities).length} capabilities</span>
        </div>
        <div className="feature-table" role="table" aria-label="Feature status">
          {Object.entries(overview.capabilities).map(([name, capability]) => {
            const Icon = CONTROL_ICONS[name] ?? Settings2
            return (
              <div className="feature-row" role="row" key={name}>
                <div className="feature-name" role="cell"><Icon aria-hidden="true" size={17} />{humanName(name)}</div>
                <div role="cell"><Status state={capability.state} /></div>
                <div className="feature-blocker" role="cell">{capability.blockers.map(humanName).join(', ') || 'No blockers reported'}</div>
              </div>
            )
          })}
        </div>
      </section>
    </div>
  )
}

function DiagnosticsPage({ overview }: { overview: Overview }) {  return (
    <section className="diagnostics-section" aria-labelledby="diagnostics-heading">
      <div className="section-heading">
        <div>
          <p className="section-label">Read-only evidence</p>
          <h2 id="diagnostics-heading">Diagnostics</h2>
        </div>
        <Status state={overview.diagnostics.status === 'ready' ? 'ready' : overview.diagnostics.status === 'degraded' ? 'degraded' : 'unhealthy'} />
      </div>
      <div className="diagnostic-checks">
        {overview.diagnostics.checks.map((check) => (
          <article className="diagnostic-check" key={check.code}>
            <div className="diagnostic-title">
              <h3>{humanName(check.code)}</h3>
              <Status state={check.status === 'pass' ? 'available' : check.status === 'fail' ? 'unhealthy' : 'unavailable'} />
            </div>
            <dl className="evidence-list">
              <div><dt>Evidence</dt><dd>{check.summary}</dd></div>
              <div><dt>Reason</dt><dd>{humanName(check.reason_code)}</dd></div>
              <div><dt>Observed</dt><dd>{new Date(check.observed_at).toLocaleString()}</dd></div>
              <div><dt>Freshness</dt><dd>{check.freshness === 'current' ? 'Current evidence' : 'Stale evidence'}</dd></div>
              <div><dt>Next action</dt><dd>{check.next_action ?? 'No action required'}</dd></div>
            </dl>
          </article>
        ))}
      </div>
    </section>
  )
}

function RecommendationsPage({ record }: { record: RecommendationRecord | null | undefined }) {
  if (!record) {
    return (
      <section className="diagnostics-section" aria-labelledby="recommendations-heading">
        <div className="section-heading">
          <div>
            <p className="section-label">Evidence-ranked selection</p>
            <h2 id="recommendations-heading">Recommendations</h2>
          </div>
        </div>
        <p className="empty-state">No recommendation recorded yet. Generate one from the operator CLI or API.</p>
      </section>
    )
  }
  return (
    <section className="diagnostics-section" aria-labelledby="recommendations-heading">
      <div className="section-heading">
        <div>
          <p className="section-label">Evidence-ranked selection</p>
          <h2 id="recommendations-heading">Recommendations</h2>
        </div>
        <span>{record.profile.name} · {new Date(record.created_at).toLocaleString()}</span>
      </div>
      <p className="recommendation-summary">{record.summary}</p>
      <div className="ranking-list">
        {record.ranked.slice(0, 3).map((tuple, index) => (
          <article className="diagnostic-check" key={`${tuple.candidate.model_id}-${tuple.candidate.quantization}-${tuple.candidate.engine_id}`}>
            <div className="diagnostic-title">
              <h3>{index + 1}. {tuple.candidate.model_id} · {tuple.candidate.quantization} · {tuple.candidate.engine_id}</h3>
              <span className="score-badge">{(tuple.score * 100).toFixed(1)}%</span>
            </div>
            <dl className="evidence-list">
              <div><dt>Context</dt><dd>{tuple.candidate.context_window.toLocaleString()} tokens</dd></div>
              <div><dt>Concurrency</dt><dd>{tuple.candidate.concurrency}</dd></div>
              {tuple.contributions.filter((item) => item.comparability === 'comparable').slice(0, 4).map((item) => (
                <div key={item.metric}>
                  <dt>{humanName(item.metric)}</dt>
                  <dd>{(item.contribution * 100).toFixed(0)}% · confidence {(item.effective_confidence * 100).toFixed(0)}%</dd>
                </div>
              ))}
              <div><dt>Why</dt><dd>{tuple.summary}</dd></div>
            </dl>
          </article>
        ))}
      </div>
      <div className="feature-table" role="table" aria-label="Excluded tuples">
        <div className="feature-row table-head" role="row">
          <div className="feature-name" role="cell">Excluded tuple</div>
          <div role="cell">Reason</div>
        </div>
        {record.excluded.slice(0, 6).map((excluded) => (
          <div className="feature-row" role="row" key={`${excluded.candidate.model_id}-${excluded.candidate.quantization}-${excluded.candidate.engine_id}-${String(excluded.candidate.context_window)}`}>
            <div className="feature-name" role="cell">
              {excluded.candidate.model_id} · {excluded.candidate.quantization} · {excluded.candidate.engine_id}
            </div>
            <div className="feature-blocker" role="cell">
              {excluded.violations.map((violation) => `${humanName(violation.code)}: ${violation.detail}`).join('; ')}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function RuntimePage({ controls }: { controls: ControlsReport | null }) {
  return (
    <section className="diagnostics-section" aria-labelledby="runtime-heading">
      <div className="section-heading">
        <div>
          <p className="section-label">Morpheus-owned services</p>
          <h2 id="runtime-heading">Feature controls</h2>
        </div>
        {controls && <span>{controls.core_ready ? 'Core runtime ready' : 'Core runtime not ready'}</span>}
      </div>
      {controls === null ? (
        <p className="empty-state">Controls are unavailable. The control API did not return a valid report.</p>
      ) : (
        <div className="control-table" role="table" aria-label="Feature controls">
          {controls.controls.map((entry) => {
            const Icon = CONTROL_ICONS[entry.control] ?? Settings2
            const flags: Array<[string, boolean]> = [
              ['configured', entry.configured],
              ['running', entry.running],
              ['healthy', entry.healthy],
              ['usable', entry.usable],
            ]
            return (
              <div className="feature-row control-row" role="row" key={entry.control}>
                <div className="feature-name" role="cell"><Icon aria-hidden="true" size={17} />{humanName(entry.control)}</div>
                <div role="cell"><Status state={entry.state} /></div>
                <div className="control-flags" role="cell">
                  {flags.map(([flag, on]) => (
                    <span key={flag} className={on ? 'flag-on' : 'flag-off'}>
                      {on ? <CheckCircle2 aria-hidden="true" size={13} /> : <Clock3 aria-hidden="true" size={13} />}
                      {humanName(flag)}
                    </span>
                  ))}
                </div>
                <div className="feature-blocker" role="cell">{entry.blockers.map(humanName).join(', ') || 'No blockers reported'}</div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function HardwarePage({ host }: { host: HostUnavailable | HostAvailable }) {
  if (host.status === 'unavailable') {
    return (
      <section className="diagnostics-section" aria-labelledby="hardware-heading">
        <div className="section-heading">
          <div>
            <p className="section-label">Runtime agent evidence</p>
            <h2 id="hardware-heading">Hardware</h2>
          </div>
          <Status state="unavailable" />
        </div>
        <p className="empty-state">Runtime agent offline: {humanName(host.reason)}. Hardware evidence is unavailable.</p>
      </section>
    )
  }
  const gpu = host.gpu
  const memory = host.memory
  const disk = host.disk
  return (
    <section className="diagnostics-section" aria-labelledby="hardware-heading">
      <div className="section-heading">
        <div>
          <p className="section-label">Runtime agent evidence</p>
          <h2 id="hardware-heading">Hardware</h2>
        </div>
        <Status state="partial" />
      </div>
      <div className="metrics-grid" aria-label="Hardware evidence">
        <article className="metric-cell">
          <Cpu aria-hidden="true" />
          <span>GPU memory</span>
          <strong>{gpu ? `${gpu.memory_used_mib.toLocaleString()} MiB` : 'Not reported'}</strong>
          <small>{gpu ? `${gpu.memory_total_mib.toLocaleString()} MiB total · ${String(gpu.utilization_percent)}% utilized` : 'No accelerator evidence'}</small>
        </article>
        <article className="metric-cell">
          <Gauge aria-hidden="true" />
          <span>Memory</span>
          <strong>{memory ? `${String(Math.round((memory.total_bytes - memory.available_bytes) / 1_073_741_824))} GiB` : 'Not reported'}</strong>
          <small>{memory ? `${String(Math.round(memory.available_bytes / 1_073_741_824))} GiB free` : 'No memory evidence'}</small>
        </article>
        <article className="metric-cell">
          <Database aria-hidden="true" />
          <span>Storage</span>
          <strong>{disk ? `${String(Math.round(disk.free_bytes / 1_073_741_824))} GiB` : 'Not reported'}</strong>
          <small>{disk ? 'free space' : 'No storage evidence'}</small>
        </article>
        <article className="metric-cell">
          <Server aria-hidden="true" />
          <span>Host status</span>
          <strong>{host.status === 'available' ? 'Available' : 'Degraded'}</strong>
          <small>{host.status === 'available' ? 'All probes passed' : 'Partial evidence'}</small>
        </article>
      </div>
    </section>
  )
}

function EmptyWorkspacePage({ workspace }: { workspace: Workspace }) {
  const message = {
    empty: `${workspace.label} has no query model in this release yet.`,
    unavailable: `The evidence source for ${workspace.label} is unavailable right now.`,
    partial: `Only partial evidence is available for ${workspace.label}.`,
    ready: `${workspace.label} is ready.`,
  }[workspace.state]
  const Icon = WORKSPACE_ICONS[workspace.id] ?? Settings2
  return (
    <section className="diagnostics-section" aria-labelledby={`workspace-${workspace.id}-heading`}>
      <div className="section-heading">
        <div>
          <p className="section-label">Operations workspace</p>
          <h2 id={`workspace-${workspace.id}-heading`}>{workspace.label}</h2>
        </div>
        <Status state={workspace.state} />
      </div>
      <p className="empty-state workspace-empty"><Icon aria-hidden="true" size={18} /> {message}</p>
    </section>
  )
}

const TREND_SIGNALS = [
  ['gpu_cache_usage', 'GPU cache usage'],
  ['utilization_percent', 'GPU utilization'],
  ['temperature_c', 'GPU temperature'],
  ['memory_available_bytes', 'Memory available'],
  ['memory_used_bytes', 'Memory used'],
  ['free_bytes', 'Disk free'],
] as const

function formatMetric(value: number | null, unit: string): string {
  if (value === null) return 'No data'
  if (unit === 'percent') return `${String(Math.round(value))}%`
  if (unit === 'bytes') return `${String(Math.round(value / 1_048_576))} MiB`
  if (unit === 'tokens') return `${Math.round(value).toLocaleString()} tokens`
  return value.toLocaleString()
}

function TrendChart({ buckets, gaps, unit }: { buckets: MetricBucket[]; gaps: MetricGap[]; unit: string }) {
  const peak = useMemo(() => Math.max(1, ...buckets.map((bucket) => bucket.mean ?? 0)), [buckets])
  if (buckets.length === 0) {
    return <p className="empty-state">No samples in this window yet.</p>
  }
  return (
    <div className="trend-chart" role="img" aria-label={`Trend of ${unit} over the selected window`}>
      {buckets.map((bucket) => {
        const height = bucket.mean === null ? 0 : Math.max(2, (bucket.mean / peak) * 100)
        const label = `${new Date(bucket.start).toLocaleString()} – ${String(bucket.count)} samples, mean ${formatMetric(bucket.mean, unit)}`
        const gapAfter = gaps.some((gap) => gap.start === bucket.end)
        return (
          <div className="trend-column" key={bucket.start}>
            <div
              className="trend-bar"
              style={{ height: `${String(height)}%` }}
              role="img"
              aria-label={label}
              title={label}
            />
            {gapAfter && (
              <div className="trend-gap" role="img" aria-label="Missing data interval" title="Missing data interval" />
            )}
          </div>
        )
      })}
    </div>
  )
}

function MetricsPage({
  trend,
  trendSignal,
  onTrendSignal,
}: {
  trend: MetricsTrend | null
  trendSignal: string
  onTrendSignal: (signal: string) => void
}) {
  const freshness = trend?.freshness
  const freshnessLabel = freshness?.state === 'fresh'
    ? 'Fresh evidence'
    : freshness?.state === 'stale'
      ? `Stale evidence · ${String(Math.round((freshness.age_seconds ?? 0) / 60))} min old`
      : 'No samples yet'
  return (
    <section className="diagnostics-section" aria-labelledby="trends-heading">
      <div className="section-heading">
        <div>
          <p className="section-label">Bounded metric rollups</p>
          <h2 id="trends-heading">Hardware trends</h2>
        </div>
        {freshness && <span className={`status status-${freshness.state}`}>{freshnessLabel}</span>}
      </div>
      <div className="toolbar">
        <label htmlFor="trend-signal">Signal</label>
        <select
          id="trend-signal"
          value={trendSignal}
          onChange={(event) => { onTrendSignal(event.target.value) }}
        >
          {TREND_SIGNALS.map(([value, label]) => (
            <option value={value} key={value}>{label}</option>
          ))}
        </select>
        {trend && <span>Unit: {trend.unit}</span>}
      </div>
      {trend && (
        <div className="trend-meta">
          <TrendChart buckets={trend.buckets} gaps={trend.gaps} unit={trend.unit} />
          <div className="trend-foot">
            <span>{trend.sample_count.toLocaleString()} samples in window</span>
            <span>Sources: {trend.sources.map((source) => `${source.source} ${source.state}`).join(' · ')}</span>
          </div>
        </div>
      )}
      {trend === null && <p className="empty-state">Trend data is unavailable right now.</p>}
    </section>
  )
}

function EventsPage({ report }: { report: EventsReport | null }) {
  const [source, setSource] = useState('all')
  const [severity, setSeverity] = useState('all')
  const events = useMemo(() => report?.events ?? [], [report])
  const sources = useMemo(() => Array.from(new Set(events.map((event) => event.source))).sort(), [events])
  const filtered = events.filter((event) =>
    (source === 'all' || event.source === source) &&
    (severity === 'all' || event.severity === severity),
  )
  return (
    <section className="diagnostics-section" aria-labelledby="events-heading">
      <div className="section-heading">
        <div>
          <p className="section-label">Redacted operator log</p>
          <h2 id="events-heading">Logs & events</h2>
        </div>
        {report && <span>{report.count} recorded</span>}
      </div>
      <div className="toolbar">
        <label htmlFor="event-source">Source</label>
        <select id="event-source" value={source} onChange={(event) => { setSource(event.target.value) }}>
          <option value="all">All sources</option>
          {sources.map((name) => <option value={name} key={name}>{humanName(name)}</option>)}
        </select>
        <label htmlFor="event-severity">Severity</label>
        <select id="event-severity" value={severity} onChange={(event) => { setSeverity(event.target.value) }}>
          <option value="all">All severities</option>
          <option value="info">Info</option>
          <option value="warn">Warning</option>
          <option value="error">Error</option>
        </select>
      </div>
      {filtered.length === 0 ? (
        <p className="empty-state">{report === null ? 'Event log is unavailable right now.' : 'No events match the filters.'}</p>
      ) : (
        <div className="feature-table event-table" role="table" aria-label="Recorded events">
          {filtered.map((event, index) => (
            <EventRow event={event} index={index} key={`${event.recorded_at}-${event.source}-${String(index)}`} />
          ))}
        </div>
      )}
    </section>
  )
}

function EventRow({ event, index }: { event: EventRecord; index: number }) {
  const correlation = event.correlation_id ? ` · ${event.correlation_id}` : ''
  return (
    <div className="feature-row event-row" role="row" key={`${event.recorded_at}-${String(index)}`}>
      <div className="event-time" role="cell">{new Date(event.recorded_at).toLocaleString()}</div>
      <div role="cell">{humanName(event.source)}</div>
      <div role="cell"><span className={`severity severity-${event.severity}`}>{event.severity}</span></div>
      <div className="event-message" role="cell" title={event.message}>{event.message}{correlation}</div>
    </div>
  )
}

function BenchmarksPage({ report }: { report: BenchmarksReport | null }) {
  return (
    <section className="diagnostics-section" aria-labelledby="benchmarks-heading">
      <div className="section-heading">
        <div>
          <p className="section-label">Campaign run history</p>
          <h2 id="benchmarks-heading">Benchmarks</h2>
        </div>
        {report && <span>{report.count} runs recorded</span>}
      </div>
      {report === null ? (
        <p className="empty-state">Benchmark history is unavailable right now.</p>
      ) : report.runs.length === 0 ? (
        <p className="empty-state">No benchmark runs recorded yet.</p>
      ) : (
        <div className="feature-table" role="table" aria-label="Benchmark runs">
          <div className="feature-row table-head" role="row">
            <div className="feature-name" role="cell">Run</div>
            <div role="cell">Model</div>
            <div role="cell">Engine</div>
            <div role="cell">Started</div>
            <div role="cell">Status</div>
          </div>
          {report.runs.map((run) => (
            <div className="feature-row" role="row" key={run.run_id}>
              <div className="feature-name" role="cell">{run.run_id}</div>
              <div role="cell">{String(run.identity.model_id)}</div>
              <div role="cell">{String(run.identity.engine_id)} · {String(run.identity.quantization)}</div>
              <div role="cell">{new Date(run.started_at).toLocaleString()}</div>
              <div role="cell"><span className={`status status-${run.status === 'completed' ? 'available' : run.status === 'failed' ? 'unhealthy' : 'degraded'}`}>{humanName(run.status)}</span></div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function AnalyticsPage({ report }: { report: AnalyticsReport | null }) {
  if (report === null) {
    return (
      <section className="diagnostics-section" aria-labelledby="analytics-heading">
        <div className="section-heading">
          <div>
            <p className="section-label">Evidence comparisons</p>
            <h2 id="analytics-heading">Analytics</h2>
          </div>
        </div>
        <p className="empty-state">Analytics are unavailable right now.</p>
      </section>
    )
  }
  const usage = report.usage
  return (
    <section className="diagnostics-section" aria-labelledby="analytics-heading">
      <div className="section-heading">
        <div>
          <p className="section-label">Evidence comparisons</p>
          <h2 id="analytics-heading">Analytics</h2>
        </div>
        <span>{usage.window_days}-day window</span>
      </div>
      <div className="metrics-grid" aria-label="Usage summary">
        <article className="metric-cell"><Activity aria-hidden="true" /><span>Requests</span><strong>{usage.requests.toLocaleString()}</strong></article>
        <article className="metric-cell"><CheckCircle2 aria-hidden="true" /><span>Successes</span><strong>{usage.successes.toLocaleString()}</strong></article>
        <article className="metric-cell"><AlertTriangle aria-hidden="true" /><span>Errors</span><strong>{usage.errors.toLocaleString()}</strong></article>
        <article className="metric-cell"><Gauge aria-hidden="true" /><span>Tokens</span><strong>{(usage.prompt_tokens + usage.completion_tokens).toLocaleString()}</strong><small>{usage.prompt_tokens.toLocaleString()} prompt · {usage.completion_tokens.toLocaleString()} completion</small></article>
      </div>
      <div className="feature-table" role="table" aria-label="Run scorecards">
        <div className="feature-row table-head" role="row">
          <div className="feature-name" role="cell">Run</div>
          <div role="cell">TTFT p50</div>
          <div role="cell">Throughput p50</div>
          <div role="cell">Samples</div>
        </div>
        {report.scorecards.map((card) => (
          <div className="feature-row" role="row" key={card.run_id}>
            <div className="feature-name" role="cell">{card.run_id}<small>{card.model_id} · {card.engine_id} · {card.quantization}</small></div>
            <div role="cell">{card.ttft_seconds === null ? '—' : `${String(Math.round(card.ttft_seconds * 1000))} ms`}</div>
            <div role="cell">{card.tokens_per_second === null ? '—' : `${String(Math.round(card.tokens_per_second))} tok/s`}</div>
            <div role="cell">{card.sample_count}</div>
          </div>
        ))}
      </div>
      {report.comparisons.length > 0 && (
        <div className="feature-table" role="table" aria-label="Run comparisons">
          <div className="feature-row table-head" role="row">
            <div className="feature-name" role="cell">Comparison</div>
            <div role="cell">Metric</div>
            <div role="cell">Baseline</div>
            <div role="cell">Candidate</div>
            <div role="cell">Change</div>
          </div>
          {report.comparisons.map((comparison, index) => (
            <div className="feature-row" role="row" key={`${comparison.baseline_run_id}-${comparison.candidate_run_id}-${String(index)}`}>
              <div className="feature-name" role="cell">{comparison.baseline_run_id} → {comparison.candidate_run_id}<small>{comparison.classification}{comparison.classification_note ? ` · ${comparison.classification_note}` : ''}</small></div>
              <div role="cell">{humanName(comparison.metric)} ({comparison.statistic})</div>
              <div role="cell">{formatMetric(comparison.baseline.value, comparison.metric === 'tokens_per_second' ? 'tokens' : 'count')}</div>
              <div role="cell">{formatMetric(comparison.candidate.value, comparison.metric === 'tokens_per_second' ? 'tokens' : 'count')}</div>
              <div role="cell">{comparison.percent_change === null ? '—' : `${comparison.percent_change > 0 ? '+' : ''}${String(Math.round(comparison.percent_change))}%`}</div>
            </div>
          ))}
        </div>
      )}
      {report.regressions.length > 0 && (
        <div className="feature-table" role="table" aria-label="Detected regressions">
          <div className="feature-row table-head" role="row">
            <div className="feature-name" role="cell">Regression</div>
            <div role="cell">Baseline</div>
            <div role="cell">Candidate</div>
            <div role="cell">Change</div>
          </div>
          {report.regressions.map((regression, index) => (
            <div className="feature-row" role="row" key={`${regression.metric}-${String(index)}`}>
              <div className="feature-name" role="cell"><AlertTriangle size={16} aria-hidden="true" /> {humanName(regression.metric)}</div>
              <div role="cell">{String(Math.round(regression.baseline_value))}</div>
              <div role="cell">{String(Math.round(regression.candidate_value))}</div>
              <div role="cell">{regression.change_pct > 0 ? '+' : ''}{String(Math.round(regression.change_pct))}%</div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function WorkspacePage({
  view,
  overview,
  controls,
  recommendation,
  workspaces,
  metrics,
  trendSignal,
  onTrendSignal,
  events,
  benchmarks,
  analytics,
}: {
  view: string
  overview: Overview | null
  controls: ControlsReport | null
  recommendation: RecommendationRecord | null | undefined
  workspaces: Workspace[]
  metrics: MetricsTrend | null
  trendSignal: string
  onTrendSignal: (signal: string) => void
  events: EventsReport | null
  benchmarks: BenchmarksReport | null
  analytics: AnalyticsReport | null
}) {
  const workspace = workspaces.find((item) => item.id === view)
  switch (view) {
    case 'overview':
      return overview ? <OverviewPage overview={overview} /> : null
    case 'diagnostics':
      return overview ? <DiagnosticsPage overview={overview} /> : null
    case 'models':
      return <RecommendationsPage record={recommendation} />
    case 'runtime':
      return <RuntimePage controls={controls} />
    case 'hardware':
      return (
        <div className="page-stack">
          <HardwarePage
            host={overview?.host ?? { status: 'unavailable', reason: 'runtime_agent_not_configured' }}
          />
          <MetricsPage trend={metrics} trendSignal={trendSignal} onTrendSignal={onTrendSignal} />
        </div>
      )
    case 'logs_events':
      return <EventsPage report={events} />
    case 'benchmarks':
      return <BenchmarksPage report={benchmarks} />
    case 'analytics':
      return <AnalyticsPage report={analytics} />
    default:
      return workspace ? <EmptyWorkspacePage workspace={workspace} /> : null
  }
}

function useWorkspaceData<T>(
  view: string,
  target: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
  setter: (value: T | null) => void,
) {
  const request = useRef<AbortController | null>(null)
  useEffect(() => {
    if (view !== target) return
    const controller = new AbortController()
    request.current?.abort()
    request.current = controller
    fetcher(controller.signal)
      .then((value) => { setter(value) })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        setter(null)
      })
      .finally(() => {
        if (request.current === controller) request.current = null
      })
    return () => {
      request.current?.abort()
      request.current = null
    }
  }, [view, target, fetcher, setter])
}

function Dashboard({ onLogout, onSessionExpired }: { onLogout: () => Promise<void>; onSessionExpired: () => void }) {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [navigation, setNavigation] = useState<NavigationManifest | null>(null)
  const [controls, setControls] = useState<ControlsReport | null>(null)
  const [recommendation, setRecommendation] = useState<RecommendationRecord | null | undefined>(undefined)
  const [metrics, setMetrics] = useState<MetricsTrend | null>(null)
  const [events, setEvents] = useState<EventsReport | null>(null)
  const [benchmarks, setBenchmarks] = useState<BenchmarksReport | null>(null)
  const [analytics, setAnalytics] = useState<AnalyticsReport | null>(null)
  const [trendSignal, setTrendSignal] = useState('gpu_cache_usage')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState('overview')
  const overviewRequest = useRef<AbortController | null>(null)
  const recommendationRequest = useRef<AbortController | null>(null)

  const refresh = useCallback(async () => {
    const controller = new AbortController()
    overviewRequest.current?.abort()
    overviewRequest.current = controller
    setLoading(true)
    const [overviewResult, navigationResult, controlsResult] = await Promise.allSettled([
      fetchOverview(controller.signal),
      fetchNavigation(controller.signal),
      fetchControls(controller.signal),
    ])
    if (overviewResult.status === 'fulfilled') {
      setOverview(overviewResult.value)
      setError(null)
    } else {
      const reason: unknown = overviewResult.reason
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      const message = reason instanceof Error ? reason.message : 'Control API request failed'
      if (message === 'Authentication failed') onSessionExpired()
      setError(message)
    }
    if (navigationResult.status === 'fulfilled') setNavigation(navigationResult.value)
    if (controlsResult.status === 'fulfilled') setControls(controlsResult.value)
    if (overviewRequest.current === controller) {
      overviewRequest.current = null
      setLoading(false)
    }
  }, [onSessionExpired])

  const refreshRecommendation = useCallback(async () => {
    const controller = new AbortController()
    recommendationRequest.current?.abort()
    recommendationRequest.current = controller
    try {
      setRecommendation(await fetchLatestRecommendation(controller.signal))
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      setRecommendation(null)
    } finally {
      if (recommendationRequest.current === controller) {
        recommendationRequest.current = null
      }
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => { overviewRequest.current?.abort() }
  }, [refresh])

  useEffect(() => {
    void refreshRecommendation()
    return () => { recommendationRequest.current?.abort() }
  }, [refreshRecommendation])

  const fetchTrend = useCallback(
    (signal: AbortSignal) => fetchMetricsTrend(signal, trendSignal),
    [trendSignal],
  )
  const fetchEventLog = useCallback((signal: AbortSignal) => fetchEvents(200, signal), [])
  const fetchRunHistory = useCallback((signal: AbortSignal) => fetchBenchmarks(20, signal), [])
  useWorkspaceData(view, 'hardware', fetchTrend, setMetrics)
  useWorkspaceData(view, 'logs_events', fetchEventLog, setEvents)
  useWorkspaceData(view, 'benchmarks', fetchRunHistory, setBenchmarks)
  useWorkspaceData(view, 'analytics', fetchAnalytics, setAnalytics)

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (!document.hidden) void refresh()
    }, error ? 45_000 : 15_000)
    return () => {
      window.clearInterval(interval)
    }
  }, [error, refresh])

  const observed = useMemo(() => overview ? new Date(overview.observed_at).toLocaleTimeString() : 'Waiting', [overview])
  const workspaces = useMemo(() => navigation?.workspaces ?? FALLBACK_WORKSPACES, [navigation])

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand"><Activity aria-hidden="true" size={21} /><span>Morpheus</span></div>
        <div className="header-actions">
          <span className="last-updated">Updated {observed}</span>
          <button className="icon-command" type="button" onClick={() => { void refresh() }} aria-label="Refresh overview" title="Refresh overview"><RefreshCw size={17} /></button>
          <button className="icon-command" type="button" onClick={() => { overviewRequest.current?.abort(); recommendationRequest.current?.abort(); void onLogout() }} aria-label="Sign out" title="Sign out"><LogOut size={17} /></button>
        </div>
      </header>
      <nav className="workspace-nav" aria-label="Operator workspaces">
        {workspaces.map((workspace) => {
          const Icon = WORKSPACE_ICONS[workspace.id] ?? Settings2
          return (
            <button
              key={workspace.id}
              type="button"
              aria-label={workspace.label}
              className={view === workspace.id ? 'active' : ''}
              aria-current={view === workspace.id ? 'page' : undefined}
              onClick={() => { setView(workspace.id) }}
            >
              <Icon aria-hidden="true" size={15} />
              {workspace.label}
              <span className={`nav-state nav-state-${workspace.state}`}>{humanName(workspace.state)}</span>
            </button>
          )
        })}
      </nav>
      <main className="workspace">
        {error && <div className="error-banner" role="alert"><AlertTriangle size={18} /> <span>{error}. Showing the most recent valid observation when available.</span></div>}
        {loading && !overview && <div className="loading-state" role="status"><RefreshCw className="spin" size={19} /> Loading operational state</div>}
        <WorkspacePage
          view={view}
          overview={overview}
          controls={controls}
          recommendation={recommendation}
          workspaces={workspaces}
          metrics={metrics}
          trendSignal={trendSignal}
          onTrendSignal={setTrendSignal}
          events={events}
          benchmarks={benchmarks}
          analytics={analytics}
        />
      </main>
    </div>
  )
}

export default function App() {
  const [signedIn, setSignedIn] = useState(() => sessionStorage.getItem(SESSION_MARKER) === '1')
  async function login(value: string) {
    await createSession(value)
    sessionStorage.setItem(SESSION_MARKER, '1')
    setSignedIn(true)
  }
  async function logout() {
    try {
      await destroySession()
    } finally {
      sessionStorage.removeItem(SESSION_MARKER)
      setSignedIn(false)
    }
  }
  function sessionExpired() {
    sessionStorage.removeItem(SESSION_MARKER)
    setSignedIn(false)
  }
  return signedIn ? <Dashboard onLogout={logout} onSessionExpired={sessionExpired} /> : <Login onLogin={login} />
}

