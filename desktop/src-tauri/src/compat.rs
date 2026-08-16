//! Capability and compatibility rules for the desktop shell (DESK-001).
//!
//! DESK-001 requires the webview to receive no general shell or filesystem
//! capability. This module validates the bundled capability manifest against
//! that invariant so a future permission addition fails the test suite
//! instead of shipping silently.

use serde_json::Value;

/// Permissions the webview may hold. Anything else is rejected: shell,
/// filesystem, HTTP, process, OS, and opener access are all out of scope.
fn allowed_capability(permission: &str) -> bool {
    permission.starts_with("core:")
        && !permission.contains("shell")
        && !permission.contains("fs:")
        && !permission.contains("http:")
        && !permission.contains("process")
        && !permission.contains("os:")
        && !permission.contains("opener")
}

/// Validate a Tauri capability manifest (the `permissions` arrays across all
/// capability files) against the DESK-001 invariant.
pub fn validate_capability_manifest(manifest: &str) -> Result<(), String> {
    let value: Value =
        serde_json::from_str(manifest).map_err(|error| format!("invalid manifest: {error}"))?;
    let capabilities: Vec<&Value> = match &value {
        Value::Array(items) => items.iter().collect(),
        Value::Object(_) => vec![&value],
        _ => return Err("manifest must be a JSON object or array".to_string()),
    };
    if capabilities.is_empty() {
        return Err("manifest declares no capabilities".to_string());
    }
    for capability in capabilities {
        let permissions = capability
            .get("permissions")
            .and_then(Value::as_array)
            .ok_or_else(|| "capability missing permissions array".to_string())?;
        for permission in permissions {
            let name = permission
                .as_str()
                .ok_or_else(|| "permission entry must be a string".to_string())?;
            if !allowed_capability(name) {
                return Err(format!("disallowed webview capability: {name}"));
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const MINIMAL_MANIFEST: &str = r#"{
            "identifier": "main",
            "windows": ["main"],
            "permissions": ["core:default", "core:window:allow-set-title"]
        }"#;

    #[test]
    fn minimal_manifest_passes() {
        assert!(validate_capability_manifest(MINIMAL_MANIFEST).is_ok());
    }

    #[test]
    fn bundled_manifest_passes() {
        let bundled = include_str!("../capabilities/default.json");
        assert!(validate_capability_manifest(bundled).is_ok());
    }

    #[test]
    fn shell_capability_is_rejected() {
        let manifest =
            MINIMAL_MANIFEST.replace("\"core:window:allow-set-title\"", "\"shell:allow-execute\"");
        let error = validate_capability_manifest(&manifest).unwrap_err();
        assert!(error.contains("shell"));
    }

    #[test]
    fn filesystem_capability_is_rejected() {
        let manifest =
            MINIMAL_MANIFEST.replace("\"core:window:allow-set-title\"", "\"fs:allow-read\"");
        let error = validate_capability_manifest(&manifest).unwrap_err();
        assert!(error.contains("fs:"));
    }

    #[test]
    fn http_and_process_capabilities_are_rejected() {
        for permission in ["http:default", "process:allow-restart", "opener:default"] {
            let manifest = MINIMAL_MANIFEST.replace("\"core:window:allow-set-title\"", permission);
            assert!(
                validate_capability_manifest(&manifest).is_err(),
                "{permission} must be rejected"
            );
        }
    }

    #[test]
    fn malformed_manifest_is_rejected() {
        assert!(validate_capability_manifest("not json").is_err());
        assert!(validate_capability_manifest("[]").is_err());
    }
}
