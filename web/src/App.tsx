import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Cpu,
  Database,
  Gauge,
  LogOut,
  RefreshCw,
  Search,
  Server,
  Settings2,
  ShieldCheck,
  Volume2,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'

import {
  createSession,
  destroySession,
  fetchLatestRecommendation,
  fetchOverview,
  type CapabilityState,
  type HealthState,
  type Overview,
  type RecommendationRecord,
} from './api'
import './styles.css'

const SESSION_MARKER = 'morpheus.session.active'

function humanName(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function Status({ state }: { state: HealthState | CapabilityState | 'unavailable' }) {
  const healthy = state === 'ready' || state === 'available'
  const Icon = healthy ? CheckCircle2 : state === 'disabled' || state === 'unavailable' ? Clock3 : AlertTriangle
  return (
    <span className={`status status-${state}`}>
      <Icon aria-hidden="true" size={15} />
      {humanName(state)}
    </span>
  )
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
            const Icon = name === 'search' ? Search : name === 'voice' ? Volume2 : name === 'core' ? Activity : Settings2
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

function Dashboard({ onLogout, onSessionExpired }: { onLogout: () => Promise<void>; onSessionExpired: () => void }) {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [recommendation, setRecommendation] = useState<RecommendationRecord | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState<'overview' | 'diagnostics' | 'recommendations'>('overview')
  const activeRequest = useRef<AbortController | null>(null)

  const refresh = useCallback(async () => {
    const controller = new AbortController()
    activeRequest.current?.abort()
    activeRequest.current = controller
    setLoading(true)
    try {
      const next = await fetchOverview(controller.signal)
      setOverview(next)
      setError(null)
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      const message = reason instanceof Error ? reason.message : 'Control API request failed'
      if (message === 'Authentication failed') onSessionExpired()
      setError(message)
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null
        setLoading(false)
      }
    }
  }, [onSessionExpired])

  const refreshRecommendation = useCallback(async () => {
    const controller = new AbortController()
    activeRequest.current?.abort()
    activeRequest.current = controller
    try {
      setRecommendation(await fetchLatestRecommendation(controller.signal))
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      setRecommendation(null)
    } finally {
      if (activeRequest.current === controller) {
        activeRequest.current = null
      }
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => { activeRequest.current?.abort() }
  }, [refresh])

  useEffect(() => {
    void refreshRecommendation()
    return () => { activeRequest.current?.abort() }
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

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand"><Activity aria-hidden="true" size={21} /><span>Morpheus</span></div>
        <div className="header-actions">
          <span className="last-updated">Updated {observed}</span>
          <button className="icon-command" type="button" onClick={() => { void refresh() }} aria-label="Refresh overview" title="Refresh overview"><RefreshCw size={17} /></button>
          <button className="icon-command" type="button" onClick={() => { activeRequest.current?.abort(); void onLogout() }} aria-label="Sign out" title="Sign out"><LogOut size={17} /></button>
        </div>
      </header>
      <nav className="view-tabs" aria-label="Dashboard views">
        <button type="button" className={view === 'overview' ? 'active' : ''} onClick={() => { setView('overview') }}>Overview</button>
        <button type="button" className={view === 'diagnostics' ? 'active' : ''} onClick={() => { setView('diagnostics') }}>Diagnostics</button>
        <button type="button" className={view === 'recommendations' ? 'active' : ''} onClick={() => { setView('recommendations') }}>Recommendations</button>
      </nav>
      <main className="workspace">
        {error && <div className="error-banner" role="alert"><AlertTriangle size={18} /> <span>{error}. Showing the most recent valid observation when available.</span></div>}
        {loading && !overview && <div className="loading-state" role="status"><RefreshCw className="spin" size={19} /> Loading operational state</div>}
        {overview && view === 'overview' && <OverviewPage overview={overview} />}
        {overview && view === 'diagnostics' && <DiagnosticsPage overview={overview} />}
        {view === 'recommendations' && <RecommendationsPage record={recommendation} />}
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
