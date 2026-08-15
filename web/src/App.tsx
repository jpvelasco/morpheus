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
  fetchControls,
  fetchLatestRecommendation,
  fetchNavigation,
  fetchOverview,
  type CapabilityState,
  type ControlState,
  type ControlsReport,
  type HealthState,
  type HostAvailable,
  type HostUnavailable,
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

function WorkspacePage({
  view,
  overview,
  controls,
  recommendation,
  workspaces,
}: {
  view: string
  overview: Overview | null
  controls: ControlsReport | null
  recommendation: RecommendationRecord | null | undefined
  workspaces: Workspace[]
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
        <HardwarePage
          host={overview?.host ?? { status: 'unavailable', reason: 'runtime_agent_not_configured' }}
        />
      )
    default:
      return workspace ? <EmptyWorkspacePage workspace={workspace} /> : null
  }
}

function Dashboard({ onLogout, onSessionExpired }: { onLogout: () => Promise<void>; onSessionExpired: () => void }) {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [navigation, setNavigation] = useState<NavigationManifest | null>(null)
  const [controls, setControls] = useState<ControlsReport | null>(null)
  const [recommendation, setRecommendation] = useState<RecommendationRecord | null | undefined>(undefined)
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