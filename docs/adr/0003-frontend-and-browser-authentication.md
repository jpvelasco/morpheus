# ADR-0003: React Dashboard and Signed Browser Session

Status: Accepted

The operational dashboard uses strict TypeScript and React. It exchanges the
local API credential once for a short-lived, HMAC-signed browser session. The
session is an `HttpOnly`, `SameSite=Strict` cookie. `Secure` stays off on the
default HTTP loopback and SSH-tunnel profiles so the browser will store it;
`access_profile=network` still requires `MORPHEUS_SESSION_COOKIE_SECURE=true`
plus TLS. The dashboard retains only a non-secret in-memory/session-storage
marker. It never stores or re-sends the API credential after sign-in.

State-changing browser routes require a same-site CSRF token that is bound to
the signed session. The API credential remains supported as a bearer credential
for the CLI and non-browser automation. LAN exposure remains out of scope
until the network access profile is selected with TLS and identity controls.
