use std::{
    env, fs,
    io::{Read, Write},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

use tauri::{AppHandle, Manager};

pub const GATEWAY_PORT: u16 = 51718;
const DEFAULT_LOG_MAX_BYTES: u64 = 10 * 1024 * 1024;
const DEFAULT_LOG_BACKUP_COUNT: usize = 3;

struct RotatingLog {
    path: PathBuf,
    file: fs::File,
    bytes_written: u64,
    max_bytes: u64,
    backup_count: usize,
}

impl RotatingLog {
    fn open(path: PathBuf, max_bytes: u64, backup_count: usize) -> std::io::Result<Self> {
        let file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)?;
        let bytes_written = file.metadata()?.len();
        let mut log = Self {
            path,
            file,
            bytes_written,
            max_bytes,
            backup_count,
        };
        if log.max_bytes > 0 && log.bytes_written >= log.max_bytes {
            log.rotate()?;
        }
        Ok(log)
    }

    fn backup_path(&self, index: usize) -> PathBuf {
        PathBuf::from(format!("{}.{}", self.path.display(), index))
    }

    fn rotate(&mut self) -> std::io::Result<()> {
        self.file.flush()?;
        if self.backup_count == 0 {
            self.file.set_len(0)?;
        } else {
            for index in (1..=self.backup_count).rev() {
                let source = if index == 1 {
                    self.path.clone()
                } else {
                    self.backup_path(index - 1)
                };
                let destination = self.backup_path(index);
                if destination.exists() {
                    fs::remove_file(&destination)?;
                }
                if source.exists() {
                    fs::rename(source, destination)?;
                }
            }
        }
        self.file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)?;
        self.bytes_written = 0;
        Ok(())
    }

    fn write_bytes(&mut self, bytes: &[u8]) -> std::io::Result<()> {
        if self.max_bytes > 0
            && self.bytes_written > 0
            && self.bytes_written + bytes.len() as u64 > self.max_bytes
        {
            self.rotate()?;
        }
        self.file.write_all(bytes)?;
        self.file.flush()?;
        self.bytes_written += bytes.len() as u64;
        Ok(())
    }
}

fn forward_output<R: Read + Send + 'static>(mut reader: R, log: Arc<Mutex<RotatingLog>>) {
    std::thread::spawn(move || {
        let mut buffer = [0_u8; 8192];
        loop {
            let bytes_read = match reader.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(bytes_read) => bytes_read,
            };
            let Ok(mut log) = log.lock() else {
                break;
            };
            if log.write_bytes(&buffer[..bytes_read]).is_err() {
                break;
            }
        }
    });
}

pub struct GatewayProcess {
    child: Mutex<Option<Child>>,
    port: Mutex<Option<u16>>,
}

impl Drop for GatewayProcess {
    fn drop(&mut self) {
        self.stop();
    }
}

impl GatewayProcess {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            port: Mutex::new(None),
        }
    }

    pub fn port(&self) -> Option<u16> {
        self.port.lock().ok().and_then(|port| *port)
    }

    pub fn start(&self, app: &AppHandle) -> Result<(), String> {
        let Some(executable) = gateway_executable(app)? else {
            return Ok(());
        };

        let port = GATEWAY_PORT;

        let data_dir = app
            .path()
            .app_data_dir()
            .map_err(|error| format!("could not resolve CaberOS app-data directory: {error}"))?;
        fs::create_dir_all(&data_dir)
            .map_err(|error| format!("could not create CaberOS app-data directory: {error}"))?;
        let log_dir = data_dir.join("logs");
        fs::create_dir_all(&log_dir)
            .map_err(|error| format!("could not create CaberOS log directory: {error}"))?;
        let log_path = log_dir.join("gateway.log");
        let max_log_bytes = env::var("AGENTOS_LOG_MAX_BYTES")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(DEFAULT_LOG_MAX_BYTES);
        let log_backup_count = env::var("AGENTOS_LOG_BACKUP_COUNT")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(DEFAULT_LOG_BACKUP_COUNT);
        let log = Arc::new(Mutex::new(
            RotatingLog::open(log_path, max_log_bytes, log_backup_count)
                .map_err(|error| format!("could not open CaberOS gateway log: {error}"))?,
        ));
        let log_level = env::var("AGENTOS_LOG_LEVEL").unwrap_or_else(|_| "warning".to_string());
        let log_access = env::var("AGENTOS_LOG_ACCESS").unwrap_or_else(|_| "false".to_string());

        let mut command = Command::new(&executable);
        command
            .current_dir(&data_dir)
            .env("AGENTOS_CONTROL_PLANE_HOST", "127.0.0.1")
            .env("AGENTOS_CONTROL_PLANE_PORT", port.to_string())
            .env("AGENTOS_DB_PATH", data_dir.join("agentos.db"))
            .env("AGENTOS_SECRET_KEY_PATH", data_dir.join("secret.key"))
            .env("AGENTOS_WORKSPACE_ROOT", data_dir.join("workspaces"))
            .env("AGENTOS_KNOWLEDGE_ROOT", data_dir.join("knowledge"))
            .env("AGENTOS_AGENT_HOME_ROOT", data_dir.join("agents"))
            .env("AGENTOS_LOG_LEVEL", log_level)
            .env("AGENTOS_LOG_ACCESS", log_access)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());

        // Point the gateway at the bundled skills directory (Tauri resource).
        let resource_dir = app
            .path()
            .resource_dir()
            .map_err(|error| format!("could not resolve CaberOS resource directory: {error}"))?;
        let skills_dir = resource_dir.join("resources").join("skills");
        if skills_dir.is_dir() {
            command.env("AGENTOS_SKILLS_DIR", &skills_dir);
        }

        #[cfg(unix)]
        command.process_group(0);

        let mut child = command.spawn().map_err(|error| {
            format!(
                "could not start CaberOS gateway at {}: {error}",
                executable.display()
            )
        })?;

        if let Some(status) = child
            .try_wait()
            .map_err(|error| format!("could not inspect CaberOS gateway process: {error}"))?
        {
            return Err(format!(
                "CaberOS gateway exited immediately with status {status}"
            ));
        }

        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "CaberOS gateway stdout was not captured".to_string())?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| "CaberOS gateway stderr was not captured".to_string())?;
        forward_output(stdout, Arc::clone(&log));
        forward_output(stderr, log);

        let mut process = self
            .child
            .lock()
            .map_err(|_| "CaberOS gateway process lock was poisoned".to_string())?;
        *process = Some(child);
        let mut gateway_port = self
            .port
            .lock()
            .map_err(|_| "CaberOS gateway port lock was poisoned".to_string())?;
        *gateway_port = Some(port);
        Ok(())
    }

    pub fn stop(&self) {
        let Ok(mut process) = self.child.lock() else {
            return;
        };

        if let Some(mut child) = process.take() {
            #[cfg(unix)]
            unsafe {
                libc::kill(-(child.id() as libc::pid_t), libc::SIGKILL);
            }
            #[cfg(not(unix))]
            let _ = child.kill();
            let _ = child.wait();
        }
        if let Ok(mut port) = self.port.lock() {
            *port = None;
        }
    }
}

fn gateway_executable(app: &AppHandle) -> Result<Option<PathBuf>, String> {
    if let Some(path) = env::var_os("CABEROS_GATEWAY_EXECUTABLE") {
        return Ok(Some(PathBuf::from(path)));
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("could not resolve CaberOS resource directory: {error}"))?;
    let file_name = if cfg!(windows) {
        "caberos-gateway.exe"
    } else {
        "caberos-gateway"
    };
    let candidates = [
        resource_dir
            .join("resources")
            .join("gateway")
            .join(file_name)
            .join(file_name),
        resource_dir
            .join("resources")
            .join("gateway")
            .join(file_name),
        resource_dir.join("resources").join(file_name),
        resource_dir.join(file_name),
    ];

    Ok(candidates.into_iter().find(|candidate| candidate.is_file()))
}

#[cfg(test)]
mod tests {
    use std::{fs, time::SystemTime};

    use super::{RotatingLog, GATEWAY_PORT};

    #[test]
    fn uses_the_stable_oauth_callback_port() {
        assert_eq!(GATEWAY_PORT, 51718);
    }

    #[test]
    fn rotates_gateway_logs_with_bounded_backups() {
        let directory = std::env::temp_dir().join(format!(
            "caberos-gateway-log-test-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(SystemTime::UNIX_EPOCH)
                .expect("system clock should be after the Unix epoch")
                .as_nanos()
        ));
        fs::create_dir_all(&directory).expect("test directory should be created");
        let path = directory.join("gateway.log");
        let mut log = RotatingLog::open(path.clone(), 4, 2).expect("log should open");

        log.write_bytes(b"1234")
            .expect("first write should succeed");
        log.write_bytes(b"56").expect("second write should rotate");

        assert_eq!(fs::read(&path).expect("active log should exist"), b"56");
        assert_eq!(
            fs::read(directory.join("gateway.log.1")).expect("first backup should exist"),
            b"1234"
        );
        fs::remove_dir_all(directory).expect("test directory should be removed");
    }
}
