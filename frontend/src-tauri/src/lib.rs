mod gateway;
mod shell_sandbox;

use gateway::{GatewayProcess, GATEWAY_PORT};
use serde::Serialize;
use std::path::Path;
use tauri::{AppHandle, Emitter, Manager, RunEvent};

#[derive(Serialize)]
struct DroppedFile {
    name: String,
    bytes: Vec<u8>,
}

#[tauri::command]
fn gateway_url(gateway: tauri::State<'_, GatewayProcess>) -> String {
    format!(
        "http://127.0.0.1:{}",
        gateway.port().unwrap_or(GATEWAY_PORT)
    )
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    app.exit(0);
}

/// Update-install restart. `process.relaunch()` spawns the new instance
/// before the old one finishes its Exit handler, so the surviving gateway
/// can still hold GATEWAY_PORT when the new gateway probes it (B48-class
/// race: FATAL "cannot bind 127.0.0.1:51718"). Stopping the child first —
/// `stop()` SIGKILLs the process group and waits for the reap — means the
/// port is free before the new process exists.
#[tauri::command]
fn restart_app(app: AppHandle) {
    app.state::<GatewayProcess>().stop();
    app.restart();
}

#[tauri::command]
async fn enable_shell_sandbox(app: AppHandle) -> Result<(), String> {
    shell_sandbox::enable(&app).await
}

/// Non-null once the gateway has died on its own — the message names the
/// cause (usually a port holder, from the gateway's own FATAL log line) so
/// the frontend can show it instead of spinning on "Starting…" forever.
#[tauri::command]
fn gateway_error(app: AppHandle, gateway: tauri::State<'_, GatewayProcess>) -> Option<String> {
    let log_path = app
        .path()
        .app_data_dir()
        .ok()?
        .join("logs")
        .join("gateway.log");
    gateway.error_detail(&log_path)
}

#[tauri::command]
fn gateway_log_path(app: AppHandle) -> Result<String, String> {
    app.path()
        .app_data_dir()
        .map(|path| path.join("logs").join("gateway.log").display().to_string())
        .map_err(|error| format!("could not resolve gateway log path: {error}"))
}

#[tauri::command]
fn read_dropped_file(path: String) -> Result<DroppedFile, String> {
    let file_path = Path::new(&path);
    let metadata =
        std::fs::metadata(file_path).map_err(|_| "Dropped file is unavailable".to_string())?;
    if !metadata.is_file() {
        return Err("Dropped item is not a file".to_string());
    }
    if metadata.len() > 25 * 1024 * 1024 {
        return Err("Dropped file exceeds the 25 MB limit".to_string());
    }
    let name = file_path
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "Dropped file has no valid name".to_string())?;
    let bytes =
        std::fs::read(file_path).map_err(|_| "Dropped file could not be read".to_string())?;
    Ok(DroppedFile {
        name: name.to_string(),
        bytes,
    })
}

/// Real macOS notification authorization via UNUserNotificationCenter.
/// The plugin's permission_state() is hardcoded Granted on desktop — its
/// legacy API predates the permission model — so the frontend can't tell
/// "off in System Settings" from on (B41). Returns granted | denied |
/// default | unavailable (unbundled dev binaries have no usable bundle).
#[cfg(target_os = "macos")]
#[tauri::command]
async fn notification_os_state() -> &'static str {
    use mac_usernotifications::AuthorizationStatus;
    match mac_usernotifications::get_notification_settings().await {
        Ok(settings) => match settings.authorization_status {
            AuthorizationStatus::Authorized
            | AuthorizationStatus::Provisional
            | AuthorizationStatus::Ephemeral => "granted",
            AuthorizationStatus::Denied => "denied",
            _ => "default",
        },
        Err(_) => "unavailable",
    }
}

/// Shows the real macOS permission prompt when state is notDetermined;
/// resolves granted/denied. Pairs with `notification_os_state`.
#[cfg(target_os = "macos")]
#[tauri::command]
async fn notification_os_request() -> &'static str {
    match mac_usernotifications::request_auth().await {
        Ok(true) => "granted",
        Ok(false) => "denied",
        Err(_) => "unavailable",
    }
}

/// Fire the OS notification through UNUserNotificationCenter and return the
/// real result. The plugin's send is unusable for honest reporting: it spawns
/// `notify_rust::Notification::show()` on a detached task and discards the
/// result — and that path goes through `block_on_current`, which returns
/// `MainThreadNotRunning` whenever the main run loop isn't idle the instant
/// the send lands, silently dropping the notification before it reaches
/// macOS. The async `send()` path has no run-loop gate; it resolves once
/// macOS accepts or rejects the request (B43).
#[cfg(target_os = "macos")]
#[tauri::command]
async fn notification_os_send(title: String, body: String) -> Result<(), String> {
    let n = mac_usernotifications::Notification::new()
        .title(title)
        .message(body);
    mac_usernotifications::send(n)
        .await
        .map(|_| ())
        .map_err(|e| e.to_string())
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
async fn notification_os_send(_title: String, _body: String) -> Result<(), String> {
    Err("unavailable".into())
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
async fn notification_os_state() -> &'static str {
    "unavailable"
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
async fn notification_os_request() -> &'static str {
    "unavailable"
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_notification::init())
        .manage(GatewayProcess::new())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            app.state::<GatewayProcess>()
                .start(app.handle())
                .map_err(std::io::Error::other)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            quit_app,
            restart_app,
            enable_shell_sandbox,
            gateway_url,
            gateway_error,
            gateway_log_path,
            read_dropped_file,
            notification_os_state,
            notification_os_request,
            notification_os_send
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                // The quit-confirm bridge only exists in the healthy shell —
                // on the gateway-failed screen nothing listens for this event,
                // so preventing the close here would strand the window. When
                // the gateway never started or died on its own there are no
                // active runs to protect anyway, so let the close go through.
                let gateway = window.app_handle().state::<GatewayProcess>();
                let healthy = gateway.port().is_some() && gateway.last_error().is_none();
                if !healthy {
                    return;
                }
                api.prevent_close();
                let _ = window.emit("caberos://quit-requested", ());
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app, event| match event {
        // Reopen is the macOS dock-icon click. The variant does not exist on
        // other platforms, so the arm has to be compiled out rather than just
        // never matched — otherwise the build fails on Windows and Linux.
        #[cfg(target_os = "macos")]
        RunEvent::Reopen { .. } => {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
        RunEvent::Exit => {
            app.state::<GatewayProcess>().stop();
        }
        _ => {}
    });
}
