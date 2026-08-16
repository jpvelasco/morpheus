# Access Runbook (ACCESS-001)

Morpheus v0.2 serves loopback-only surfaces behind an authenticated
browser session. Reach a remote host by establishing an SSH tunnel to the
host; never bind the services to a peer-addressable interface in the
loopback or SSH-tunnel profile.

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
