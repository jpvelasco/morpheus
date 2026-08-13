# ADR-0007: Tauri Desktop and Independent Backend

Status: Accepted; distribution-signing gate amended by ADR-0009

Date: 2026-08-11

## Context

Morpheus needs a modern desktop application on Windows, Linux, and macOS while
remaining useful on headless inference hosts reached through SSH. The existing
React application and versioned FastAPI boundary are reusable, but embedding the
control plane inside the desktop process would couple inference operation to the
window lifecycle and prevent clean remote administration.

## Decision

Morpheus v0.2 uses Tauri 2 as a thin native desktop shell around the existing
strict TypeScript and React operations workspace. The UI communicates only with
the versioned Morpheus API and contains no host, engine, or authorization logic.

The workstation installer delivers a separately versioned, target-native
Morpheus backend and registers it as a per-user background service. Closing the
desktop window does not stop inference or the backend. The desktop performs a
version and capability handshake, can bootstrap or repair its compatible local
backend after explicit confirmation, and can connect to another backend through
an operator-established SSH tunnel.

The backend continues to serve the browser application on loopback. Tauri is the
preferred workstation experience, not a replacement protocol or a prerequisite
for headless use. Desktop and backend updates are independently versioned,
compatibility-checked, health-gated, and recoverable. ADR-0009 permits explicitly
confirmed, checksum-verified developer updates while reserving unattended update
for a completed signed-distribution trust lane.

## Consequences

- React feature code, API contracts, and browser accessibility tests remain
  shared between desktop and browser delivery.
- Native packaging, update, and service lifecycle require separate Windows,
  Linux, and macOS build and validation lanes. Public signing and notarization
  add the optional distribution-hardening lanes defined by ADR-0009.
- Tauri capabilities expose only the minimum operations required to locate and
  open the backend; the webview receives no general shell or filesystem access.
- The local installer is cohesive for ordinary users while backend-only install
  and remote attachment remain possible for headless servers.
- Per-user service mode is the v0.2 default. Elevated system-service deployment
  is deferred until an always-on, pre-login requirement is separately accepted.

## Alternatives Considered

### Browser-only application

Rejected because it does not provide the requested native installation,
application lifecycle, update, and workstation integration across all three
operating systems.

### Backend embedded in the desktop process

Rejected because closing or updating the UI could interrupt operations and the
same package could not cleanly support a headless or remote backend.

### Electron desktop shell

Rejected for v0.2 because Morpheus can reuse the platform webview through Tauri
with a smaller distribution and a narrower native capability surface. This can
be revisited if required webview behavior cannot be qualified consistently.

## References

- [Tauri external binaries](https://v2.tauri.app/develop/sidecar/)
- [Tauri capability security](https://v2.tauri.app/security/capabilities/)
- [Tauri updater](https://v2.tauri.app/plugin/updater/)
- [PyInstaller platform packaging](https://pyinstaller.org/en/stable/index.html)
