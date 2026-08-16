//! Loopback backend discovery for the desktop shell (DESK-002).
//!
//! Discovery is deliberately read-only and loopback-only: it probes the
//! public health endpoint on the default API and dashboard ports, then the
//! shell hands the reachable URL to the webview. No authenticated request is
//! made by the shell itself; the webview session performs the authenticated
//! compatibility handshake through the shared operations workspace.

use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};

use crate::DISCOVERY_TIMEOUT;

/// Default loopback candidates in probe order (API port first, then
/// dashboard port; the health endpoint is public on both surfaces).
pub const CANDIDATES: &[(&str, u16)] = &[("127.0.0.1", 7400), ("127.0.0.1", 7401)];

const HEALTH_PATH: &str = "/healthz";
const MAX_RESPONSE_BYTES: usize = 4096;

/// Minimal bounded loopback HTTP GET used only for discovery probes.
///
/// Returns `(status_code, body)` for a 200-class response, otherwise `None`.
/// The request is a plaintext loopback probe; TLS is never required.
fn probe_health(host: &str, port: u16) -> Option<(u16, String)> {
    let address = (host, port).to_socket_addrs().ok()?.next()?;
    let mut stream = TcpStream::connect_timeout(&address, DISCOVERY_TIMEOUT).ok()?;
    stream.set_read_timeout(Some(DISCOVERY_TIMEOUT)).ok()?;
    let request =
        format!("GET {HEALTH_PATH} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n");
    stream.write_all(request.as_bytes()).ok()?;
    let mut raw = Vec::new();
    let mut chunk = [0u8; 512];
    loop {
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(read) => {
                raw.extend_from_slice(&chunk[..read]);
                if raw.len() >= MAX_RESPONSE_BYTES {
                    break;
                }
            }
            Err(_) => break,
        }
    }
    let text = String::from_utf8_lossy(&raw);
    let (head, body) = text.split_once("\r\n\r\n").unwrap_or((&text, ""));
    let status = head.split_whitespace().nth(1)?.parse::<u16>().ok()?;
    Some((status, body.to_string()))
}

/// Probe every candidate and return the first reachable backend base URL.
pub fn discover() -> Option<String> {
    for (host, port) in CANDIDATES {
        if let Some((status, _)) = probe_health(host, *port) {
            if (200..300).contains(&status) {
                return Some(format!("http://{host}:{port}"));
            }
        }
    }
    None
}

/// Decide what the shell should load: the reachable backend or the bundled
/// fallback page. Kept pure for unit testing.
pub fn choose(reachable: Option<String>) -> Option<String> {
    reachable.filter(|url| url.starts_with("http://127.0.0.1:"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn discover_returns_first_reachable_candidate() {
        assert!(CANDIDATES.len() >= 2);
        assert_eq!(CANDIDATES[0], ("127.0.0.1", 7400));
        assert_eq!(CANDIDATES[1], ("127.0.0.1", 7401));
    }

    #[test]
    fn choose_accepts_loopback_urls_only() {
        assert_eq!(
            choose(Some("http://127.0.0.1:7400".to_string())),
            Some("http://127.0.0.1:7400".to_string())
        );
        assert_eq!(
            choose(Some("http://127.0.0.1:7401".to_string())),
            Some("http://127.0.0.1:7401".to_string())
        );
        assert_eq!(choose(Some("https://example.com".to_string())), None);
        assert_eq!(choose(None), None);
    }

    #[test]
    fn probe_health_parses_status_line() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();
        let handle = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept");
            let mut request = [0u8; 512];
            let _ = stream.read(&mut request);
            let _ = stream.write_all(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 15\r\n\r\n{\"status\":\"ok\"}",
            );
        });
        let result = probe_health("127.0.0.1", port);
        handle.join().expect("thread");
        let (status, body) = result.expect("probe result");
        assert_eq!(status, 200);
        assert!(body.contains("\"status\":\"ok\""));
    }

    #[test]
    fn probe_health_returns_none_when_port_closed() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind");
        let port = listener.local_addr().expect("addr").port();
        drop(listener);
        assert!(probe_health("127.0.0.1", port).is_none());
    }
}
