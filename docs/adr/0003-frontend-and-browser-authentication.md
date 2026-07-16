# ADR-0003: React Dashboard and Signed Browser Session

Status: Accepted

The operational dashboard uses strict TypeScript and React. It exchanges the
local API credential once for a short-lived, HMAC-signed browser session. The
session is an `HttpOnly`, `Secure`, `SameSite=Strict` cookie by default; the
dashboard retains only a non-secret in-memory/session-storage marker. It never
stores or re-sends the API credential after sign-in.

State-changing browser routes require a same-site CSRF token that is bound to
the signed session. The API credential remains supported as a bearer credential
for the CLI and non-browser automation. `MORPHEUS_SESSION_COOKIE_SECURE=false`
is permitted only for an explicitly disposable HTTP-only validation lab. LAN
exposure remains out of scope until a separate TLS and identity decision is
accepted.
