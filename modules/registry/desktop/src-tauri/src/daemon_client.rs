//! Minimal client for the local agent-registry daemon: health probing and
//! starting it only when the port refuses connections.

use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

const DEFAULT_PORT: u16 = 8765;
const DEFAULT_PROGRAM: &str = "agent-registry";
const DEFAULT_START_TIMEOUT_SECS: u64 = 5;
const IO_TIMEOUT: Duration = Duration::from_secs(1);
const POLL_INTERVAL: Duration = Duration::from_millis(100);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Health {
    Ours,
    Stranger,
    Refused,
}

/// GET `path` on 127.0.0.1:`port`. `Err` means the TCP connection failed;
/// `Ok(Err(_))` means connected but the exchange failed.
fn http_get(port: u16, path: &str) -> Result<Result<String, String>, String> {
    let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let mut stream = TcpStream::connect_timeout(&addr, IO_TIMEOUT).map_err(|e| e.to_string())?;
    let exchange = (|| -> Result<String, String> {
        stream
            .set_read_timeout(Some(IO_TIMEOUT))
            .map_err(|e| e.to_string())?;
        stream
            .set_write_timeout(Some(IO_TIMEOUT))
            .map_err(|e| e.to_string())?;
        let request =
            format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
        stream
            .write_all(request.as_bytes())
            .map_err(|e| e.to_string())?;
        let mut buf = Vec::new();
        stream.read_to_end(&mut buf).map_err(|e| e.to_string())?;
        Ok(String::from_utf8_lossy(&buf).into_owned())
    })();
    Ok(exchange)
}

pub fn classify_health(port: u16) -> Health {
    match http_get(port, "/api/health") {
        Err(_) => Health::Refused,
        Ok(Err(_)) => Health::Stranger,
        Ok(Ok(body)) => {
            if body.contains("\"service\":\"agent-registry\"")
                || body.contains("\"service\": \"agent-registry\"")
            {
                Health::Ours
            } else {
                Health::Stranger
            }
        }
    }
}

fn registry_dir() -> PathBuf {
    if let Some(p) = std::env::var_os("AGENT_REGISTRY_PATH").filter(|p| !p.is_empty()) {
        if let Some(parent) = Path::new(&p).parent() {
            return parent.to_path_buf();
        }
    }
    let home = std::env::var_os("HOME").unwrap_or_default();
    PathBuf::from(home).join(".local/share/agent-registry")
}

fn env_port() -> Option<u16> {
    std::env::var("AGENT_REGISTRY_DAEMON_PORT")
        .ok()
        .and_then(|v| v.trim().parse().ok())
}

fn pid_alive(pid: i32) -> bool {
    if pid <= 0 {
        return false;
    }
    // SAFETY: signal 0 performs only an existence/permission check.
    unsafe { libc::kill(pid, 0) == 0 }
}

/// Port of the daemon recorded in `dir`, if its pid file names a live process.
fn live_daemon_port(dir: &Path) -> Option<u16> {
    let pid: i32 = std::fs::read_to_string(dir.join("daemon.pid"))
        .ok()?
        .trim()
        .parse()
        .ok()?;
    if !pid_alive(pid) {
        return None;
    }
    std::fs::read_to_string(dir.join("daemon.port"))
        .ok()?
        .trim()
        .parse()
        .ok()
}

fn start_timeout() -> Duration {
    let secs = std::env::var("AGENT_REGISTRY_DAEMON_START_TIMEOUT")
        .ok()
        .and_then(|v| v.trim().parse::<u64>().ok())
        .unwrap_or(DEFAULT_START_TIMEOUT_SECS);
    Duration::from_secs(secs)
}

/// Spawn `program daemon run --port <port>` with output appended to
/// `daemon.log` in `dir`, then poll until healthy or `timeout` elapses.
fn spawn_and_wait(program: &str, port: u16, dir: &Path, timeout: Duration) -> Result<u16, String> {
    std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("daemon.log"))
        .map_err(|e| e.to_string())?;
    let log_err = log.try_clone().map_err(|e| e.to_string())?;
    let mut child = Command::new(program)
        .args(["daemon", "run", "--port", &port.to_string()])
        .stdin(Stdio::null())
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(log_err))
        .spawn()
        .map_err(|e| e.to_string())?;

    let deadline = Instant::now() + timeout;
    loop {
        if classify_health(port) == Health::Ours {
            return Ok(port);
        }
        if Instant::now() >= deadline {
            return Err("daemon did not become healthy".to_string());
        }
        // Reap the child if it already exited, to avoid a zombie.
        let _ = child.try_wait();
        std::thread::sleep(POLL_INTERVAL);
    }
}

fn ensure_daemon_with(program: &str, port_hint: Option<u16>) -> Result<u16, String> {
    let dir = registry_dir();
    let requested = port_hint.or_else(env_port);

    if let Some(live_port) = live_daemon_port(&dir) {
        if let Some(want) = requested {
            if want != live_port {
                return Err(format!("daemon already listening on {live_port}"));
            }
        }
        return Ok(live_port);
    }

    let port = requested.unwrap_or(DEFAULT_PORT);
    match classify_health(port) {
        Health::Ours => Ok(port),
        Health::Stranger => Err("port is not agent-registry".to_string()),
        Health::Refused => spawn_and_wait(program, port, &dir, start_timeout()),
    }
}

pub fn ensure_daemon(port_hint: Option<u16>) -> Result<u16, String> {
    ensure_daemon_with(DEFAULT_PROGRAM, port_hint)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    /// Serve one canned HTTP response on an ephemeral port. The listener is
    /// bound before this returns, so connects cannot race the accept.
    fn serve_once(body: &'static str) -> u16 {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = [0u8; 1024];
                let _ = stream.read(&mut buf);
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                );
                let _ = stream.write_all(response.as_bytes());
            }
        });
        port
    }

    #[test]
    fn our_health_body_is_ours() {
        let port = serve_once(r#"{"ok":true,"service":"agent-registry"}"#);
        assert_eq!(classify_health(port), Health::Ours);
    }

    #[test]
    fn different_service_is_stranger() {
        let port = serve_once(r#"{"ok":true,"service":"something-else"}"#);
        assert_eq!(classify_health(port), Health::Stranger);
    }

    #[test]
    fn closed_port_is_refused() {
        let port = {
            let l = TcpListener::bind("127.0.0.1:0").unwrap();
            l.local_addr().unwrap().port()
        };
        assert_eq!(classify_health(port), Health::Refused);
    }
}
