# Access Runbook (ACCESS-001/002)

Morpheus v0.2 serves loopback-only surfaces behind an authenticated
browser session. Reach a remote host by establishing an SSH tunnel to the
host; never bind the services to a peer-addressable interface in the
loopback or SSH-tunnel profile. The network profile is the only profile
that may bind beyond loopback, and it demands TLS, explicit origins, and
hardened cookies.

## Default posture

- API binds to `127.0.0.1:7400` and the dashboard to `127.0.0.1:7401`.
- Browser sessions require the API key once, then issue short-lived
  signed cookies (`Secure` when configured, `HttpOnly` for the session
  token, `SameSite=Strict`).
- Every state-changing browser call requires the CSRF token.
- Proxy headers (`X-Forwarded-*`) are never trusted.
- Check the live posture at `GET /api/v1/system/access` (API key
  required).

## Establishing an SSH tunnel

From the operator machine:

```bash
ssh -L 7400:127.0.0.1:7400 -L 7401:127.0.0.1:7401 operator@<host>
```

Then open `http://127.0.0.1:7401/` locally. The backend does not know or
care that the connection arrived through a tunnel; authorization,
workflows, progress, cancellation, and recovery behave exactly as they do
on the local machine.

## Tearing down

- Close the tunnel (`Ctrl-C` or kill the `ssh` process). The loopback
  sockets stay up on the host but are unreachable from the operator
  machine again.
- After teardown, log out or wait for the session lifetime to expire on
  the host if you want the browser session terminated too.

## Revoking access

- Logout (`DELETE /api/v1/session` with the CSRF token) clears the
  session and CSRF cookies; the next request is rejected.
- The session lifetime bound applies regardless: after
  `session_ttl_seconds`, a signed token is invalid on the next request.
- To revoke a key outright, rotate `api_key` and restart the backend.

## Reconnecting

- The desktop and browser reconnect with the same API key and receive the
  same health, compatibility, and capability semantics after a backend
  restart or a tunnel re-establishment.
- After the backend restarts, log in again; the old signed cookie remains
  valid until its expiry because sessions are stateless signed tokens.

## Network profile (ACCESS-002, optional)

The network profile allows direct LAN or remote browser access only when
all of the following are configured together:

- `access_profile=network` with `allow_lan=true` and an explicit bind
  address;
- TLS certificate and key paths (`tls_cert_path`, `tls_key_path`) so every
  served surface runs HTTPS;
- `allowed_origins` listing every `https://host[:port]` that may reach the
  surfaces (any other Host header is rejected with 403);
- `session_cookie_secure=true` and a configured `api_key`.

Behavior that never changes in the network profile:

- proxy headers (`X-Forwarded-*`) are never trusted for authorization or
  origin decisions;
- CSRF and session cookie semantics are identical to loopback access;
- API rate limits apply to every client IP.

Recovery: after rate-limit backoff or a backend restart, a valid login
restores the same semantics. Keep the loopback profile unless the network
profile is explicitly required, and re-check the live posture at
`GET /api/v1/system/access` before serving.

## Support posture (ACCESS-003)

`GET /api/v1/support` reports the evidence-bounded support matrix. It is
read-only: every claim is derived from retained PASS evidence runs under
`data_dir/diagnostics` and completed benchmark runs, and it never probes
live hosts. Dimensions (os, architecture, accelerator, engine, install,
lifecycle, access, recovery, benchmark) are `proven` only when retained
evidence supports the exact value; everything else is `unproven` and is
never advertised. Every proven claim carries the evidence references
(`run_id:digest`) behind it.

Named targets (batwing, batmobile) are advertised only when a PASS run
from a physical environment (`HOST-RO` or `HOST-MAINT`) names the target
machine and platform; DEV or VM evidence can never advertise a physical
target. Support claims therefore never exceed the attached target
evidence, and physical qualification lanes add the claims they actually
prove.
