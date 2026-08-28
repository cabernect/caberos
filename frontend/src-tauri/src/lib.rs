mod gateway;

use gateway::{GatewayProcess, GATEWAY_PORT};
use serde::Serialize;
use std::path::Path;
use tauri::{AppHandle, Manager, RunEvent};

#[derive(Serialize)]
struct DroppedFile {
    name: String,
    bytes: Vec<u8>,
}

#[tauri::command]
fn gateway_url(gateway: tauri::State<'_, GatewayProcess>) -> String {
    format!("http://127.0.0.1:{}", gateway.port().unwrap_or(GATEWAY_PORT))
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
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
        .invoke_handler(tauri::generate_handler![gateway_url, gateway_log_path, read_dropped_file])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app, event| match event {
        RunEvent::Reopen { .. } => {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }
        RunEvent::ExitRequested { .. } | RunEvent::Exit => {
            app.state::<GatewayProcess>().stop();
        }
        _ => {}
    });
}
