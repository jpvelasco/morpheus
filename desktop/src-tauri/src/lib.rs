//! Minimal-capability Morpheus desktop shell (DESK-001, DESK-002).
//!
//! The shell locates the local Morpheus backend with a loopback health probe,
//! loads the backend-served operations workspace in a Tauri 2 webview, and
//! grants the webview no shell, filesystem, HTTP, or process capability. When
//! no backend is reachable it stays on a bundled fallback page that can open
//! the loopback browser surface instead.

mod compat;
mod discovery;

use std::time::Duration;

pub const DESKTOP_VERSION: &str = env!("CARGO_PKG_VERSION");
pub const DISCOVERY_TIMEOUT: Duration = Duration::from_secs(3);

#[tauri::command]
fn open_browser(url: String) -> Result<(), String> {
    tauri_plugin_opener::open_url(&url, None::<&str>).map_err(|error| error.to_string())
}

pub fn run() {
    compat::validate_capability_manifest(include_str!("../capabilities/default.json"))
        .expect("bundled webview capabilities must satisfy DESK-001");
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![open_browser])
        .setup(|app| {
            let window = tauri::WebviewWindowBuilder::new(
                app,
                "main",
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title("Morpheus")
            .inner_size(1280.0, 800.0)
            .build()?;
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let reachable = discovery::discover();
                let _ = handle.run_on_main_thread(move || {
                    if let Some(url) = discovery::choose(reachable) {
                        let _ = window.navigate(url.parse().expect("valid backend url"));
                    }
                });
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the morpheus desktop shell");
}
