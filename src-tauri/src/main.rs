use serde_json::Value;
use std::{
    env,
    fs,
    io::{BufRead, BufReader},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};
use tauri::{Manager, State};

struct BotState {
    child: Option<Child>,
}

/// Resolve paths relative to the project root (parent of src-tauri)
/// so that config.json is never written inside the watched src-tauri/ dir.
fn project_root() -> PathBuf {
    // CARGO_MANIFEST_DIR is .../src-tauri at compile time
    let manifest = env!("CARGO_MANIFEST_DIR");
    PathBuf::from(manifest)
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| env::current_dir().unwrap())
}

fn resolve_path(rel: &str) -> PathBuf {
    let p = PathBuf::from(rel);
    if p.is_absolute() {
        p
    } else {
        project_root().join(p)
    }
}

/// Try to find the bundled sidecar executable next to the running binary.
/// Returns Some(path) if the sidecar exists, None otherwise (dev mode).
fn find_sidecar() -> Option<PathBuf> {
    let exe = env::current_exe().ok()?;
    let dir = exe.parent()?;

    // Tauri places sidecar binaries next to the main executable
    #[cfg(target_os = "windows")]
    let sidecar_name = "WowFishingBot.exe";
    #[cfg(not(target_os = "windows"))]
    let sidecar_name = "WowFishingBot";

    let path = dir.join(sidecar_name);
    if path.exists() {
        Some(path)
    } else {
        None
    }
}

/// Build a Command for the bot.
/// - Sidecar mode: runs the bundled exe directly (no python needed)
/// - Python mode: runs `python_cmd src/wow_fishing_bot.py` (dev fallback)
fn bot_command(python_cmd: &str, args: &[&str]) -> Result<Command, String> {
    if let Some(sidecar) = find_sidecar() {
        let mut cmd = Command::new(sidecar);
        cmd.current_dir(project_root());
        cmd.args(args);
        Ok(cmd)
    } else {
        if python_cmd.trim().is_empty() {
            return Err("python command is empty (sidecar not found)".to_string());
        }
        let mut cmd = Command::new(python_cmd);
        cmd.current_dir(project_root());
        cmd.arg("src/wow_fishing_bot.py");
        cmd.args(args);
        Ok(cmd)
    }
}

fn collect_output(output: std::process::Output) -> Result<String, String> {
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    let mut combined = String::new();
    if !stdout.trim().is_empty() {
        combined.push_str(stdout.trim());
    }
    if !stderr.trim().is_empty() {
        if !combined.is_empty() {
            combined.push('\n');
        }
        combined.push_str(stderr.trim());
    }
    if !output.status.success() {
        return Err(combined.trim().to_string());
    }
    Ok(combined.trim().to_string())
}

#[tauri::command]
fn check_sidecar() -> bool {
    find_sidecar().is_some()
}

#[tauri::command]
fn load_config(path: String) -> Result<Value, String> {
    let full = resolve_path(&path);
    let raw = fs::read_to_string(&full).map_err(|err| err.to_string())?;
    serde_json::from_str(&raw).map_err(|err| err.to_string())
}

#[tauri::command]
fn save_config(path: String, config: Value) -> Result<(), String> {
    let full = resolve_path(&path);
    let raw = serde_json::to_string_pretty(&config).map_err(|err| err.to_string())?;
    fs::write(&full, raw).map_err(|err| err.to_string())
}

#[tauri::command]
fn list_audio_devices(python_cmd: String) -> Result<String, String> {
    if let Some(sidecar) = find_sidecar() {
        let output = Command::new(sidecar)
            .current_dir(project_root())
            .arg("--list-devices")
            .output()
            .map_err(|err| err.to_string())?;
        return collect_output(output);
    }
    let output = Command::new(python_cmd)
        .current_dir(project_root())
        .args([
            "-c",
            "import sounddevice as sd; print(sd.query_devices())",
        ])
        .output()
        .map_err(|err| err.to_string())?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(stderr.trim().to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

#[tauri::command]
fn record_audio(
    python_cmd: String,
    config_path: String,
    seconds: f32,
    output_path: String,
) -> Result<String, String> {
    if config_path.trim().is_empty() {
        return Err("config path is empty".to_string());
    }
    if output_path.trim().is_empty() {
        return Err("output path is empty".to_string());
    }
    if seconds <= 0.0 {
        return Err("record seconds must be > 0".to_string());
    }
    let sec_str = seconds.to_string();
    let mut cmd = bot_command(&python_cmd, &[
        "--config", &config_path,
        "--record",
        "--record-seconds", &sec_str,
        "--record-out", &output_path,
    ])?;
    let output = cmd.output().map_err(|err| err.to_string())?;
    collect_output(output)
}

#[tauri::command]
fn capture_bobber(
    python_cmd: String,
    config_path: String,
    size: i32,
    output_path: String,
    timeout: f32,
) -> Result<String, String> {
    if config_path.trim().is_empty() {
        return Err("config path is empty".to_string());
    }
    if output_path.trim().is_empty() {
        return Err("output path is empty".to_string());
    }
    if size <= 0 {
        return Err("capture size must be > 0".to_string());
    }
    if timeout <= 0.0 {
        return Err("capture timeout must be > 0".to_string());
    }
    let size_str = size.to_string();
    let timeout_str = timeout.to_string();
    let mut cmd = bot_command(&python_cmd, &[
        "--config", &config_path,
        "--capture-bobber",
        "--capture-size", &size_str,
        "--capture-out", &output_path,
        "--capture-timeout", &timeout_str,
    ])?;
    let output = cmd.output().map_err(|err| err.to_string())?;
    collect_output(output)
}

#[tauri::command]
fn capture_region(
    python_cmd: String,
    config_path: String,
    timeout: f32,
) -> Result<String, String> {
    if config_path.trim().is_empty() {
        return Err("config path is empty".to_string());
    }
    if timeout <= 0.0 {
        return Err("region timeout must be > 0".to_string());
    }
    let timeout_str = timeout.to_string();
    let mut cmd = bot_command(&python_cmd, &[
        "--config", &config_path,
        "--capture-region",
        "--region-timeout", &timeout_str,
    ])?;
    let output = cmd.output().map_err(|err| err.to_string())?;
    collect_output(output)
}

#[tauri::command]
fn start_bot(
    app: tauri::AppHandle,
    state: State<Arc<Mutex<BotState>>>,
    python_cmd: String,
    config_path: String,
    once: bool,
) -> Result<(), String> {
    if config_path.trim().is_empty() {
        return Err("config path is empty".to_string());
    }
    let mut guard = state.lock().map_err(|_| "state lock failed".to_string())?;
    if guard.child.is_some() {
        return Err("bot already running".to_string());
    }

    let mut cmd = bot_command(&python_cmd, &["--config", &config_path])?;
    if once {
        cmd.arg("--once");
    }
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

    let mut child = cmd.spawn().map_err(|err| err.to_string())?;
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();

    if let Some(stdout) = stdout {
        let app_handle = app.clone();
        thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines().flatten() {
                let _ = app_handle.emit_all("bot-log", line);
            }
        });
    }

    if let Some(stderr) = stderr {
        let app_handle = app.clone();
        thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line in reader.lines().flatten() {
                let _ = app_handle.emit_all("bot-log", format!("[stderr] {line}"));
            }
        });
    }

    guard.child = Some(child);

    let state_handle = state.inner().clone();
    let app_handle = app.clone();
    thread::spawn(move || loop {
        thread::sleep(Duration::from_millis(300));
        let mut guard = match state_handle.lock() {
            Ok(guard) => guard,
            Err(_) => return,
        };
        if let Some(child) = guard.child.as_mut() {
            match child.try_wait() {
                Ok(Some(status)) => {
                    guard.child = None;
                    let _ = app_handle.emit_all("bot-exit", status.to_string());
                    return;
                }
                Ok(None) => {}
                Err(err) => {
                    guard.child = None;
                    let _ = app_handle.emit_all("bot-exit", format!("error: {err}"));
                    return;
                }
            }
        } else {
            return;
        }
    });

    Ok(())
}

#[tauri::command]
fn stop_bot(state: State<Arc<Mutex<BotState>>>) -> Result<(), String> {
    let mut guard = state.lock().map_err(|_| "state lock failed".to_string())?;
    if let Some(mut child) = guard.child.take() {
        let _ = child.kill();
        let _ = child.wait();
        return Ok(());
    }
    Err("bot not running".to_string())
}

#[tauri::command]
fn capture_blacklist(
    python_cmd: String,
    config_path: String,
    size: i32,
    output_path: String,
    timeout: f32,
) -> Result<String, String> {
    if config_path.trim().is_empty() {
        return Err("config path is empty".to_string());
    }
    if output_path.trim().is_empty() {
        return Err("output path is empty".to_string());
    }
    if size <= 0 {
        return Err("capture size must be > 0".to_string());
    }
    if timeout <= 0.0 {
        return Err("capture timeout must be > 0".to_string());
    }
    let size_str = size.to_string();
    let timeout_str = timeout.to_string();
    let mut cmd = bot_command(&python_cmd, &[
        "--config", &config_path,
        "--capture-blacklist",
        "--blacklist-size", &size_str,
        "--blacklist-out", &output_path,
        "--capture-timeout", &timeout_str,
    ])?;
    let output = cmd.output().map_err(|err| err.to_string())?;
    collect_output(output)
}

fn main() {
    let state = Arc::new(Mutex::new(BotState { child: None }));
    tauri::Builder::default()
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            check_sidecar,
            load_config,
            save_config,
            list_audio_devices,
            record_audio,
            capture_bobber,
            capture_blacklist,
            capture_region,
            start_bot,
            stop_bot
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
