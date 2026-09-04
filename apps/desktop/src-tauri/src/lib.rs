mod agent_host;

use agent_host::{AgentConnection, AgentProcessState, AgentRequest};
use serde::Serialize;
use serde_json::Value;
use std::path::PathBuf;
use tauri::{AppHandle, RunEvent};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_updater::UpdaterExt;

#[derive(Serialize)]
struct UpdateInfo {
    available: bool,
    current_version: String,
    version: String,
    date: Option<String>,
    body: Option<String>,
}

#[tauri::command]
async fn ensure_agent(app: AppHandle) -> Result<AgentConnection, String> {
    agent_host::ensure_agent(&app).await
}

#[tauri::command]
fn codex_home_status() -> Result<agent_host::CodexHomeStatus, String> {
    agent_host::codex_home_status()
}

#[tauri::command]
async fn prepare_codex_home(app: AppHandle, path: String) -> Result<(), String> {
    agent_host::prepare_codex_home(&app, &path).await
}

#[tauri::command]
async fn agent_request(app: AppHandle, request: AgentRequest) -> Result<Value, String> {
    agent_host::request_agent(&app, request).await
}

#[tauri::command]
async fn choose_directory(app: AppHandle, title: String) -> Result<Option<String>, String> {
    let selected = app.dialog().file().set_title(title).blocking_pick_folder();
    Ok(selected
        .and_then(|path| path.into_path().ok())
        .map(|path| path.to_string_lossy().into_owned()))
}

#[tauri::command]
async fn reveal_path(app: AppHandle, path: String) -> Result<(), String> {
    app.opener()
        .reveal_item_in_dir(PathBuf::from(path))
        .map_err(|error| error.to_string())
}

#[tauri::command]
async fn configure_background(app: AppHandle, enabled: bool) -> Result<(), String> {
    let previous = agent_host::configured_background_capture()?;
    let installed = agent_host::background_agent_installed(&app).await?;
    if enabled == previous && installed == enabled {
        return Ok(());
    }
    agent_host::quiesce_agent(&app).await?;
    let value = if enabled { "true" } else { "false" };
    let result = async {
        agent_host::sidecar_control(&app, &["--set-background-capture", value]).await?;
        agent_host::restore_agent_mode(&app, enabled).await?;
        Ok::<(), String>(())
    }
    .await;
    if let Err(error) = result {
        let previous_value = if previous { "true" } else { "false" };
        let _ =
            agent_host::sidecar_control(&app, &["--set-background-capture", previous_value]).await;
        let _ = agent_host::restore_agent_mode(&app, previous).await;
        return Err(error);
    }
    Ok(())
}

#[tauri::command]
async fn switch_codex_home(app: AppHandle, path: String) -> Result<(), String> {
    let previous_home = agent_host::active_codex_home()?;
    let background = agent_host::configured_background_capture()?;
    agent_host::quiesce_agent(&app).await?;
    let result = async {
        agent_host::sidecar_control(&app, &["--set-codex-home", &path]).await?;
        agent_host::restore_agent_mode(&app, background).await?;
        Ok::<(), String>(())
    }
    .await;
    if let Err(error) = result {
        let old_home = previous_home.to_string_lossy().into_owned();
        let _ = agent_host::sidecar_control(&app, &["--set-codex-home", &old_home]).await;
        let _ = agent_host::restore_agent_mode(&app, background).await;
        return Err(error);
    }
    Ok(())
}

#[tauri::command]
async fn reset_local_data(app: AppHandle) -> Result<(), String> {
    let background = agent_host::configured_background_capture()?;
    agent_host::quiesce_agent(&app).await?;
    let result = agent_host::sidecar_control(&app, &["--reset-local-data"]).await;
    let restored = agent_host::restore_agent_mode(&app, background).await;
    result?;
    restored.map(|_| ())
}

#[tauri::command]
async fn check_for_update(app: AppHandle) -> Result<UpdateInfo, String> {
    let current = app.package_info().version.to_string();
    let update = app
        .updater()
        .map_err(|error| error.to_string())?
        .check()
        .await
        .map_err(|error| error.to_string())?;
    Ok(match update {
        Some(update) => UpdateInfo {
            available: true,
            current_version: current,
            version: update.version,
            date: update.date.map(|value| value.to_string()),
            body: update.body,
        },
        None => UpdateInfo {
            available: false,
            current_version: current.clone(),
            version: current,
            date: None,
            body: None,
        },
    })
}

#[tauri::command]
async fn install_update(app: AppHandle) -> Result<(), String> {
    let update = app
        .updater()
        .map_err(|error| error.to_string())?
        .check()
        .await
        .map_err(|error| error.to_string())?
        .ok_or_else(|| "No update is available.".to_owned())?;
    let was_installed = agent_host::quiesce_agent(&app).await?;
    if let Err(error) = update.download_and_install(|_, _| {}, || {}).await {
        if was_installed {
            let _ = agent_host::sidecar_control(&app, &["--install-service"]).await;
        } else {
            let _ = agent_host::ensure_agent(&app).await;
        }
        return Err(error.to_string());
    }
    app.restart();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(AgentProcessState::default())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            ensure_agent,
            codex_home_status,
            prepare_codex_home,
            agent_request,
            choose_directory,
            reveal_path,
            configure_background,
            switch_codex_home,
            reset_local_data,
            check_for_update,
            install_update,
        ])
        .build(tauri::generate_context!())
        .expect("error while building Codex Usage");
    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            agent_host::stop_transient(handle);
        }
    });
}
