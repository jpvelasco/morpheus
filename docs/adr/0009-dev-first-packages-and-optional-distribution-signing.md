# ADR-0009: Dev-First Packages and Optional Distribution Signing

Status: Accepted

Date: 2026-08-12

## Context

Morpheus needs native development and qualification packages on Linux, Windows,
and macOS before public code-signing identities or Apple notarization
credentials may be available. Treating those externally issued credentials as a
source-development prerequisite would serialize otherwise independent product
work and could stop the cross-platform implementation indefinitely.

Unsigned packages cannot safely make the same trust, reputation, or automatic
update claims as signed public distributions. Removing the signature gate must
not turn an untrusted download into a silent install or update path.

## Decision

Morpheus has two package qualification levels:

- **Developer/source-qualified** artifacts are reproducibly built on the target
  platform, checksummed, version-inventoried, scanned, accompanied by an SBOM,
  and exercised by the complete install, lifecycle, recovery, and physical
  target lanes. They may be unsigned and may require documented manual operating
  system trust steps.
- **Signed-distribution-qualified** artifacts additionally use the applicable
  public distribution trust mechanisms, including Windows code signing and
  Apple application signing and notarization. This is an optional final
  distribution-hardening lane when credentials are available.

Missing signing or notarization credentials never block source implementation,
DEV/VM testing, physical product qualification, or a source-available release.
Every artifact and support report states its qualification level explicitly;
open-source status remains a separate license decision.

Unsigned developer packages require a deliberate local install or update with
checksum verification and confirmation. They cannot use unattended bootstrap,
background auto-update, or a signed-distribution claim. Automatic update
metadata and unattended replacement remain disabled until the complete signing
and update-trust lane passes.

Signing credentials are external release inputs. They are never stored in the
repository, copied into ordinary development environments, or exposed to build
agents that are not running the optional signing lane.

## Consequences

- Agents can implement and physically qualify the entire product without waiting
  for commercial certificates or notarization access.
- Checksums, provenance, SBOMs, scanning, explicit confirmation, and rollback
  remain mandatory for unsigned development artifacts.
- Windows SmartScreen and macOS Gatekeeper may present warnings or require
  documented manual steps for developer/source-qualified packages.
- Public installers and unattended updates are not described as trusted or
  frictionless until the optional signed-distribution lane passes.
- Signing can be added later without changing the backend, desktop, API, or
  managed-runtime contracts.

## Alternatives Considered

### Block all native work until signing identities exist

Rejected because external credential procurement is not a useful dependency for
domain, adapter, package, installer, lifecycle, or physical qualification work.

### Allow unsigned automatic updates

Rejected because a checksum shown after download is not an authenticated update
channel and must not authorize unattended replacement.

### Remove native packages until signing is available

Rejected because install, service, upgrade, rollback, and uninstall behavior are
part of the product and need early target-native evidence.
