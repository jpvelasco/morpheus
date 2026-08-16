//! Package-trust-aware bootstrap gating (DESK-002, ADR-0009).
//!
//! The shell maps a compatibility handshake status onto a local bootstrap
//! plan kind and then decides whether that plan may be applied. An
//! unsigned developer package can never be applied without explicit
//! confirmation, and no plan is ever applied unattended for unsigned
//! packages regardless of policy.

/// The kinds of local bootstrap action a desktop session may plan.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlanKind {
    Noop,
    Install,
    Update,
    Repair,
}

/// Map a compatibility handshake status onto a bootstrap plan kind.
///
/// `unsupported_desktop` and version drift map to an update, an absent
/// backend maps to an install, an unhealthy backend maps to a repair,
/// and a compatible backend maps to no action.
pub fn plan_for_status(status: &str, backend_running: bool) -> PlanKind {
    match status {
        "compatible" => PlanKind::Noop,
        "unsupported_desktop" | "missing_desktop_version" => PlanKind::Update,
        "unhealthy" => PlanKind::Repair,
        _ => {
            if backend_running {
                PlanKind::Repair
            } else {
                PlanKind::Install
            }
        }
    }
}

/// Decide whether ``kind`` may be applied under the given confirmation.
///
/// An unsigned package requires explicit confirmation for every
/// state-changing plan; without it the plan must not be applied.
pub fn can_apply(kind: PlanKind, unsigned: bool, confirmed: bool) -> bool {
    match kind {
        PlanKind::Noop => true,
        _ => !unsigned || confirmed,
    }
}

#[cfg(test)]
mod tests {
    use super::{can_apply, plan_for_status, PlanKind};

    #[test]
    fn compatible_backend_plans_noop() {
        assert_eq!(plan_for_status("compatible", true), PlanKind::Noop);
    }

    #[test]
    fn unsupported_desktop_plans_update() {
        assert_eq!(
            plan_for_status("unsupported_desktop", true),
            PlanKind::Update
        );
        assert_eq!(
            plan_for_status("missing_desktop_version", false),
            PlanKind::Update
        );
    }

    #[test]
    fn absent_backend_plans_install() {
        assert_eq!(plan_for_status("no_backend", false), PlanKind::Install);
    }

    #[test]
    fn unhealthy_backend_plans_repair() {
        assert_eq!(plan_for_status("unhealthy", true), PlanKind::Repair);
    }

    #[test]
    fn noop_is_always_applyable() {
        assert!(can_apply(PlanKind::Noop, true, false));
    }

    #[test]
    fn unsigned_package_requires_confirmation_for_every_plan() {
        assert!(!can_apply(PlanKind::Install, true, false));
        assert!(!can_apply(PlanKind::Update, true, false));
        assert!(!can_apply(PlanKind::Repair, true, false));
        assert!(can_apply(PlanKind::Install, true, true));
        assert!(can_apply(PlanKind::Update, true, true));
        assert!(can_apply(PlanKind::Repair, true, true));
    }

    #[test]
    fn signed_package_plan_is_applyable_without_confirmation() {
        assert!(can_apply(PlanKind::Install, false, false));
        assert!(can_apply(PlanKind::Update, false, false));
    }
}
