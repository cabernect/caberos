//! One-time host setup for the Windows shell sandbox (Microsoft Execution Containers).
//!
//! MXC needs a single elevated grant on the system drive
//! (`wxc-host-prep.exe prepare-system-drive`). It persists across reboots and every
//! later command runs without elevation. The desktop app runs it only when the user
//! clicks "Enable shell sandbox", and only the bundled, hash-pinned tool with a fixed
//! argument — nothing here is built from user input.

use std::path::PathBuf;
use tauri::{AppHandle, Manager};

fn prep_tool(app: &AppHandle) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("could not resolve the CaberOS resource directory: {error}"))?;
    let tool = resource_dir
        .join("resources")
        .join("mxc")
        .join("wxc-host-prep.exe");
    if tool.is_file() {
        Ok(tool)
    } else {
        Err("The shell sandbox setup tool is not bundled with this build.".to_string())
    }
}

#[cfg(windows)]
mod elevated {
    use std::path::Path;
    use windows::core::{w, HRESULT, HSTRING, PCWSTR};
    use windows::Win32::Foundation::{CloseHandle, ERROR_CANCELLED};
    use windows::Win32::System::Threading::{GetExitCodeProcess, WaitForSingleObject, INFINITE};
    use windows::Win32::UI::Shell::{ShellExecuteExW, SEE_MASK_NOCLOSEPROCESS, SHELLEXECUTEINFOW};
    use windows::Win32::UI::WindowsAndMessaging::SW_HIDE;

    /// Run `tool arguments` elevated and wait for it. The "runas" verb is what raises the
    /// Windows consent prompt; declining it surfaces as ERROR_CANCELLED.
    pub fn run(tool: &Path, arguments: &str) -> Result<(), String> {
        let file = HSTRING::from(tool.to_string_lossy().as_ref());
        let parameters = HSTRING::from(arguments);

        let mut info = SHELLEXECUTEINFOW {
            cbSize: std::mem::size_of::<SHELLEXECUTEINFOW>() as u32,
            fMask: SEE_MASK_NOCLOSEPROCESS,
            lpVerb: w!("runas"),
            lpFile: PCWSTR(file.as_ptr()),
            lpParameters: PCWSTR(parameters.as_ptr()),
            nShow: SW_HIDE.0,
            ..Default::default()
        };

        // SAFETY: `info` is fully initialised, and `file`/`parameters` outlive the call.
        unsafe { ShellExecuteExW(&mut info) }.map_err(|error| {
            if error.code() == HRESULT::from_win32(ERROR_CANCELLED.0) {
                "Setup was cancelled. Approve the Windows permission prompt to enable the shell sandbox."
                    .to_string()
            } else {
                format!("Could not start the shell sandbox setup: {error}")
            }
        })?;

        let process = info.hProcess;
        let mut exit_code: u32 = 1;
        // SAFETY: SEE_MASK_NOCLOSEPROCESS gave us a process handle that we own and close.
        unsafe {
            WaitForSingleObject(process, INFINITE);
            let _ = GetExitCodeProcess(process, &mut exit_code);
            let _ = CloseHandle(process);
        }

        if exit_code == 0 {
            Ok(())
        } else {
            Err(format!("The shell sandbox setup failed (exit code {exit_code})."))
        }
    }
}

pub async fn enable(app: &AppHandle) -> Result<(), String> {
    #[cfg(windows)]
    {
        let tool = prep_tool(app)?;
        // Blocking wait on the consent prompt must not stall the UI thread.
        tauri::async_runtime::spawn_blocking(move || elevated::run(&tool, "prepare-system-drive"))
            .await
            .map_err(|error| format!("The shell sandbox setup task failed: {error}"))?
    }
    #[cfg(not(windows))]
    {
        let _ = (app, prep_tool);
        Err("The shell sandbox setup is only needed on Windows.".to_string())
    }
}
