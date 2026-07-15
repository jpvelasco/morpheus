# ADR-0003: React Dashboard and Ephemeral Browser Credential

Status: Accepted

The operational dashboard uses strict TypeScript and React. It holds the local
API credential in `sessionStorage`, sends it as a bearer credential, and removes
it at sign-out or browser-session end. No authentication cookie is used, so CSRF
does not apply to the read-only dashboard surface. LAN exposure remains out of
scope until a separate TLS and identity decision is accepted.
