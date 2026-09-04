use reqwest::{Client, Method};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Manager};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

const API_VERSION: u32 = 1;
const REQUEST_LIMIT: usize = 2 * 1024 * 1024;
const RESPONSE_LIMIT: usize = 64 * 1024 * 1024;

#[derive(Default)]
pub struct AgentProcessState {
    child: Mutex<Option<ManagedTransient>>,
}

struct ManagedTransient {
    pid: u32,
    child: CommandChild,
}

#[derive(Debug, Deserialize)]
pub struct AgentRequest {
    pub(crate) method: String,
    pub(crate) path: String,
    pub(crate) body: Option<Value>,
}

#[derive(Debug, Deserialize)]
struct AgentDescriptor {
    pid: u32,
    api_version: u32,
    port: u16,
    token: String,
    codex_home: String,
    #[serde(default)]
    process_owner: Option<ProcessOwner>,
    #[serde(default)]
    parent_pid: Option<u32>,
}

#[derive(Debug, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
enum ProcessOwner {
    Background,
    Transient,
}

#[derive(Debug, Deserialize)]
struct AgentSettings {
    codex_home: String,
    #[serde(default)]
    background_capture: bool,
}

#[derive(Debug, Serialize)]
pub struct AgentConnection {
    pub codex_home: String,
    pub transient: bool,
}

#[derive(Debug, Serialize)]
pub struct CodexHomeStatus {
    pub codex_home: String,
    pub valid: bool,
    pub issue: String,
}

pub async fn ensure_agent(app: &AppHandle) -> Result<AgentConnection, String> {
    if let Ok(descriptor) = live_descriptor().await {
        return Ok(AgentConnection {
            codex_home: descriptor.codex_home,
            transient: false,
        });
    }
    stop_transient(app);
    if configured_background_capture()? {
        sidecar_control(app, &["--install-service"]).await?;
        if let Ok(descriptor) = wait_for_live_descriptor().await {
            return Ok(AgentConnection {
                codex_home: descriptor.codex_home,
                transient: false,
            });
        }
        return Err("The background collector did not become ready.".to_owned());
    }
    start_transient_agent(app).await
}

pub fn codex_home_status() -> Result<CodexHomeStatus, String> {
    let home = active_codex_home()?;
    let issue = validate_codex_home(&home).err().unwrap_or_default();
    Ok(CodexHomeStatus {
        codex_home: home.to_string_lossy().into_owned(),
        valid: issue.is_empty(),
        issue,
    })
}

pub async fn prepare_codex_home(app: &AppHandle, path: &str) -> Result<(), String> {
    if live_descriptor().await.is_ok() {
        return Err(
            "The collector is already running; use the guarded home switch instead.".to_owned(),
        );
    }
    let home = expand_home(path);
    validate_codex_home(&home)?;
    sidecar_control(app, &["--set-codex-home", path]).await?;
    Ok(())
}

pub async fn start_transient_agent(app: &AppHandle) -> Result<AgentConnection, String> {
    stop_transient(app);
    let command = app
        .shell()
        .sidecar("codex-usage-agent")
        .map_err(display_error)?;
    let parent_pid = std::process::id().to_string();
    let (mut events, child) = command
        .args(["--background", "--parent-pid", parent_pid.as_str()])
        .spawn()
        .map_err(display_error)?;
    let pid = child.pid();
    *app.state::<AgentProcessState>()
        .child
        .lock()
        .map_err(display_error)? = Some(ManagedTransient { pid, child });
    tauri::async_runtime::spawn(async move { while events.recv().await.is_some() {} });
    if let Ok(descriptor) = wait_for_live_descriptor().await {
        return Ok(AgentConnection {
            codex_home: descriptor.codex_home,
            transient: true,
        });
    }
    stop_transient(app);
    Err("The Codex Usage collector did not become ready.".to_owned())
}

pub async fn request_agent(app: &AppHandle, request: AgentRequest) -> Result<Value, String> {
    validate_request(&request)?;
    let descriptor = match live_descriptor().await {
        Ok(descriptor) => descriptor,
        Err(_) => {
            ensure_agent(app).await?;
            live_descriptor().await?
        }
    };
    let result = request_agent_with_descriptor(&descriptor, &request).await;
    if result.is_ok() || live_descriptor().await.is_ok() {
        return result;
    }
    // A VS Code-owned transient can disappear after the initial health check.
    // Reconnect through ensure_agent so this app starts only its own
    // replacement rather than trying to stop the former owner.
    ensure_agent(app).await?;
    let replacement = live_descriptor().await?;
    request_agent_with_descriptor(&replacement, &request).await
}

async fn request_agent_with_descriptor(
    descriptor: &AgentDescriptor,
    request: &AgentRequest,
) -> Result<Value, String> {
    let method = match request.method.as_str() {
        "GET" => Method::GET,
        "POST" => Method::POST,
        _ => return Err("Only GET and POST agent requests are supported.".to_owned()),
    };
    let client = Client::builder()
        .connect_timeout(Duration::from_secs(2))
        .build()
        .map_err(display_error)?;
    let mut outgoing = client
        .request(
            method,
            format!("http://127.0.0.1:{}{}", descriptor.port, request.path),
        )
        .bearer_auth(descriptor.token)
        .header("Content-Type", "application/json");
    if let Some(body) = &request.body {
        outgoing = outgoing.json(body);
    }
    let response = outgoing.send().await.map_err(display_error)?;
    let status = response.status();
    if response
        .content_length()
        .is_some_and(|size| size > RESPONSE_LIMIT as u64)
    {
        return Err("The collector response exceeded the native app limit.".to_owned());
    }
    let bytes = response.bytes().await.map_err(display_error)?;
    if bytes.len() > RESPONSE_LIMIT {
        return Err("The collector response exceeded the native app limit.".to_owned());
    }
    let value: Value = serde_json::from_slice(&bytes).map_err(display_error)?;
    if !status.is_success() {
        let detail = value
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("collector request failed");
        return Err(detail.to_owned());
    }
    Ok(value)
}

pub async fn shutdown_agent(app: &AppHandle) {
    let descriptor = match live_descriptor().await {
        Ok(descriptor) => descriptor,
        Err(_) => {
            stop_transient(app);
            return;
        }
    };
    if !owns_transient(app, &descriptor) {
        return;
    }
    let _ = request_agent_with_descriptor(
        &descriptor,
        &AgentRequest {
            method: "POST".to_owned(),
            path: "/v1/shutdown".to_owned(),
            body: Some(Value::Object(Default::default())),
        },
    )
    .await;
    for _ in 0..50 {
        if live_descriptor().await.is_err() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    stop_transient(app);
}

pub async fn quiesce_agent(app: &AppHandle) -> Result<bool, String> {
    let installed = background_agent_installed(app).await?;
    if installed {
        sidecar_control(app, &["--uninstall-service"]).await?;
        stop_transient(app);
        wait_until_stopped().await?;
    } else {
        if let Ok(descriptor) = live_descriptor().await {
            if !owns_transient(app, &descriptor) {
                return Err(
                    "Another client owns the active collector. Stop it from its owning client before changing collector settings."
                        .to_owned(),
                );
            }
        }
        shutdown_agent(app).await;
    }
    Ok(installed)
}

pub async fn background_agent_installed(app: &AppHandle) -> Result<bool, String> {
    Ok(sidecar_control(app, &["--service-status"])
        .await?
        .get("installed")
        .and_then(Value::as_bool)
        .unwrap_or(false))
}

pub async fn restore_agent_mode(
    app: &AppHandle,
    background_capture: bool,
) -> Result<AgentConnection, String> {
    if background_capture {
        sidecar_control(app, &["--install-service"]).await?;
        let descriptor = wait_for_live_descriptor().await?;
        return Ok(AgentConnection {
            codex_home: descriptor.codex_home,
            transient: false,
        });
    }
    start_transient_agent(app).await
}

pub async fn sidecar_control(app: &AppHandle, args: &[&str]) -> Result<Value, String> {
    let output = app
        .shell()
        .sidecar("codex-usage-agent")
        .map_err(display_error)?
        .args(args)
        .output()
        .await
        .map_err(display_error)?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
    }
    serde_json::from_slice(&output.stdout).map_err(display_error)
}

pub fn stop_transient(app: &AppHandle) {
    let state = app.state::<AgentProcessState>();
    if let Ok(mut guard) = state.child.lock() {
        if let Some(managed) = guard.take() {
            let _ = managed.child.kill();
        }
    };
}

fn owns_transient(app: &AppHandle, descriptor: &AgentDescriptor) -> bool {
    let state = app.state::<AgentProcessState>();
    let Ok(guard) = state.child.lock() else {
        return false;
    };
    let Some(managed) = guard.as_ref() else {
        return false;
    };
    descriptor_matches_transient(descriptor, std::process::id(), managed.pid)
}

fn descriptor_matches_transient(
    descriptor: &AgentDescriptor,
    parent_pid: u32,
    managed_pid: u32,
) -> bool {
    descriptor.process_owner == Some(ProcessOwner::Transient)
        && descriptor.parent_pid == Some(parent_pid)
        && descriptor.pid == managed_pid
}

fn validate_request(request: &AgentRequest) -> Result<(), String> {
    if !request.path.starts_with("/v1/")
        || request.path.contains("://")
        || request.path.contains(['\r', '\n'])
    {
        return Err("Invalid collector API path.".to_owned());
    }
    let size = request
        .body
        .as_ref()
        .map(serde_json::to_vec)
        .transpose()
        .map_err(display_error)?
        .map_or(0, |body| body.len());
    if size > REQUEST_LIMIT {
        return Err("Collector request body is too large.".to_owned());
    }
    Ok(())
}

async fn live_descriptor() -> Result<AgentDescriptor, String> {
    let descriptor = read_descriptor()?;
    let response = Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(display_error)?
        .get(format!("http://127.0.0.1:{}/v1/health", descriptor.port))
        .bearer_auth(&descriptor.token)
        .send()
        .await
        .map_err(display_error)?;
    if !response.status().is_success() {
        return Err("Collector health check failed.".to_owned());
    }
    let payload: Value = response.json().await.map_err(display_error)?;
    if payload.get("api_version").and_then(Value::as_u64) != Some(API_VERSION as u64) {
        return Err("Collector API version is incompatible.".to_owned());
    }
    Ok(descriptor)
}

async fn wait_for_live_descriptor() -> Result<AgentDescriptor, String> {
    for _ in 0..120 {
        if let Ok(descriptor) = live_descriptor().await {
            return Ok(descriptor);
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    Err("The Codex Usage collector did not become ready.".to_owned())
}

fn read_descriptor() -> Result<AgentDescriptor, String> {
    let home = active_codex_home()?;
    let path = home.join(".codex-usage").join("agent.json");
    let descriptor: AgentDescriptor =
        serde_json::from_slice(&std::fs::read(&path).map_err(display_error)?)
            .map_err(display_error)?;
    if descriptor.pid == 0
        || descriptor.api_version != API_VERSION
        || descriptor.port == 0
        || descriptor.token.len() < 32
        || !same_path(Path::new(&descriptor.codex_home), &home)
    {
        return Err("Collector descriptor is invalid or incompatible.".to_owned());
    }
    Ok(descriptor)
}

pub fn active_codex_home() -> Result<PathBuf, String> {
    if let Some(settings) = read_agent_settings()? {
        return Ok(expand_home(&settings.codex_home));
    }
    default_codex_home()
}

pub fn configured_background_capture() -> Result<bool, String> {
    Ok(read_agent_settings()?
        .map(|settings| settings.background_capture)
        .unwrap_or(false))
}

fn read_agent_settings() -> Result<Option<AgentSettings>, String> {
    let path = settings_path()?;
    if !path.is_file() {
        return Ok(None);
    }
    serde_json::from_slice(&std::fs::read(path).map_err(display_error)?)
        .map(Some)
        .map_err(display_error)
}

fn default_codex_home() -> Result<PathBuf, String> {
    if let Ok(value) = std::env::var("CODEX_HOME") {
        if !value.trim().is_empty() {
            return Ok(expand_home(value.trim()));
        }
    }
    dirs::home_dir()
        .map(|home| home.join(".codex"))
        .ok_or_else(|| "Could not resolve the user home directory.".to_owned())
}

fn settings_path() -> Result<PathBuf, String> {
    if let Ok(value) = std::env::var("CODEX_USAGE_DATA_DIR") {
        if !value.trim().is_empty() {
            return Ok(expand_home(value.trim()).join("settings.json"));
        }
    }
    #[cfg(target_os = "macos")]
    let root = dirs::home_dir().map(|home| home.join("Library/Application Support/Codex Usage"));
    #[cfg(target_os = "windows")]
    let root = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .map(|path| path.join("Codex Usage"));
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let root = dirs::config_dir().map(|path| path.join("codex-usage"));
    root.map(|path| path.join("settings.json"))
        .ok_or_else(|| "Could not resolve the Codex Usage settings path.".to_owned())
}

fn expand_home(value: &str) -> PathBuf {
    if value == "~" {
        return dirs::home_dir().unwrap_or_else(|| PathBuf::from(value));
    }
    if let Some(suffix) = value.strip_prefix("~/") {
        return dirs::home_dir()
            .map(|home| home.join(suffix))
            .unwrap_or_else(|| PathBuf::from(value));
    }
    PathBuf::from(value)
}

fn same_path(left: &Path, right: &Path) -> bool {
    #[cfg(target_os = "windows")]
    {
        left.to_string_lossy().to_lowercase() == right.to_string_lossy().to_lowercase()
    }
    #[cfg(not(target_os = "windows"))]
    {
        left == right
    }
}

fn validate_codex_home(path: &Path) -> Result<(), String> {
    if !path.is_dir() {
        return Err(format!("Codex home does not exist: {}", path.display()));
    }
    if !path.join("sessions").is_dir() && !path.join("archived_sessions").is_dir() {
        return Err(format!(
            "Codex home has no sessions or archived_sessions directory: {}",
            path.display()
        ));
    }
    Ok(())
}

async fn wait_until_stopped() -> Result<(), String> {
    for _ in 0..50 {
        if live_descriptor().await.is_err() {
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    Err("The Codex Usage collector did not stop in time.".to_owned())
}

fn display_error(error: impl std::fmt::Display) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::{
        descriptor_matches_transient, validate_codex_home, validate_request, AgentDescriptor,
        AgentRequest, ProcessOwner, REQUEST_LIMIT,
    };
    use serde_json::{json, Value};
    use std::fs;

    #[test]
    fn collector_proxy_accepts_only_versioned_local_paths() {
        assert!(validate_request(&AgentRequest {
            method: "GET".to_owned(),
            path: "/v1/status".to_owned(),
            body: None,
        })
        .is_ok());
        for path in [
            "/status",
            "http://example.test/v1/status",
            "/v1/x\nInjected",
        ] {
            assert!(validate_request(&AgentRequest {
                method: "GET".to_owned(),
                path: path.to_owned(),
                body: None,
            })
            .is_err());
        }
    }

    #[test]
    fn collector_proxy_rejects_oversized_request_bodies() {
        let oversized = Value::String("x".repeat(REQUEST_LIMIT + 1));
        assert!(validate_request(&AgentRequest {
            method: "POST".to_owned(),
            path: "/v1/settings".to_owned(),
            body: Some(json!({ "value": oversized })),
        })
        .is_err());
    }

    #[test]
    fn codex_home_requires_an_active_or_archived_session_root() {
        let root =
            std::env::temp_dir().join(format!("codex-usage-home-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        assert!(validate_codex_home(&root).is_err());
        fs::create_dir(root.join("archived_sessions")).unwrap();
        assert!(validate_codex_home(&root).is_ok());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn transient_shutdown_requires_the_native_parent_and_child_identity() {
        let mut descriptor = AgentDescriptor {
            pid: 42,
            api_version: 1,
            port: 1234,
            token: "x".repeat(32),
            codex_home: "/tmp/codex-home".to_owned(),
            process_owner: Some(ProcessOwner::Transient),
            parent_pid: Some(7),
        };

        assert!(descriptor_matches_transient(&descriptor, 7, 42));
        assert!(!descriptor_matches_transient(&descriptor, 8, 42));
        assert!(!descriptor_matches_transient(&descriptor, 7, 43));

        descriptor.process_owner = Some(ProcessOwner::Background);
        assert!(!descriptor_matches_transient(&descriptor, 7, 42));
    }
}
