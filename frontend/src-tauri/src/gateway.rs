use std::{
    env, fs,
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
};

#[cfg(unix)]
use std::os::unix::process::CommandExt;

use tauri::{AppHandle, Manager};

pub struct GatewayProcess(Mutex<Option<Child>>);

impl Drop for GatewayProcess {
    fn drop(&mut self) {
        self.stop();
    }
}

impl GatewayProcess {
    pub fn new() -> Self {
        Self(Mutex::new(None))
    }

    pub fn start(&self, app: &AppHandle) -> Result<(), String> {
        let Some(executable) = gateway_executable(app)? else {
            return Ok(());
        };

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
        let stdout = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|error| format!("could not open CaberOS gateway log: {error}"))?;
        let stderr = stdout
            .try_clone()
            .map_err(|error| format!("could not prepare CaberOS gateway log: {error}"))?;

        let mut command = Command::new(&executable);
        command
            .current_dir(&data_dir)
            .env("AGENTOS_DB_PATH", data_dir.join("agentos.db"))
            .env("AGENTOS_SECRET_KEY_PATH", data_dir.join("secret.key"))
            .env("AGENTOS_WORKSPACE_ROOT", data_dir.join("workspaces"))
            .env("AGENTOS_AGENT_HOME_ROOT", data_dir.join("agents"))
            .stdin(Stdio::null())
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr));

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

        let mut process = self
            .0
            .lock()
            .map_err(|_| "CaberOS gateway process lock was poisoned".to_string())?;
        *process = Some(child);
        Ok(())
    }

    pub fn stop(&self) {
        let Ok(mut process) = self.0.lock() else {
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
