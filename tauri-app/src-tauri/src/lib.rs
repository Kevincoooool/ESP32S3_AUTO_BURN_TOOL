mod config;
mod esptool_runner;
mod flash;
mod serial_monitor;

use config::{load_config, save_config, AppConfig};
use base64::{engine::general_purpose::STANDARD, Engine};
use flash::{erase_port, FlashManager, FirmwareItem};
use serial_monitor::SerialMonitorManager;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fs;
use std::path::Path;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder};

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct PortsChangedEvent {
    ports: Vec<String>,
}

#[tauri::command]
fn list_ports() -> Result<Vec<String>, String> {
    let mut ports: Vec<String> = serialport::available_ports()
        .map_err(|e| e.to_string())?
        .into_iter()
        .map(|p| p.port_name)
        .collect();
    ports.sort_by_key(|p| com_port_num(p));
    Ok(ports)
}

fn com_port_num(name: &str) -> u32 {
    name.trim()
        .strip_prefix("COM")
        .or_else(|| name.strip_prefix("com"))
        .and_then(|n| n.parse().ok())
        .unwrap_or(u32::MAX)
}

#[tauri::command]
fn get_config(app: AppHandle) -> Result<AppConfig, String> {
    load_config(&app)
}

#[tauri::command]
fn set_config(app: AppHandle, config: AppConfig) -> Result<(), String> {
    save_config(&app, &config)
}

#[tauri::command]
fn check_esptool(app: AppHandle) -> Result<String, String> {
    esptool_runner::flasher_info(&app)
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct FlashArgsEntry {
    address: String,
    path: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct FlashArgsImport {
    entries: Vec<FlashArgsEntry>,
    flash_mode: Option<String>,
    flash_freq: Option<String>,
}

#[tauri::command]
fn parse_flash_args(flash_args_path: String) -> Result<FlashArgsImport, String> {
    let content = fs::read_to_string(&flash_args_path).map_err(|e| format!("读取失败: {e}"))?;
    let base = Path::new(&flash_args_path)
        .parent()
        .ok_or_else(|| "无效的 flash_args 路径".to_string())?;

    let mut entries = Vec::new();
    let mut flash_mode = None;
    let mut flash_freq = None;

    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        if line.starts_with('-') {
            for token in line.split_whitespace() {
                if let Some(v) = token.strip_prefix("--flash-mode=") {
                    flash_mode = Some(v.to_string());
                } else if let Some(v) = token.strip_prefix("--flash-freq=") {
                    flash_freq = Some(v.to_string());
                }
            }
            continue;
        }

        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 2 {
            continue;
        }
        let addr = parts[0].to_string();
        let full = base.join(parts[1]);
        if !full.is_file() {
            return Err(format!("文件不存在: {}", full.display()));
        }
        entries.push(FlashArgsEntry {
            address: addr,
            path: full.to_string_lossy().into_owned(),
        });
    }

    if entries.is_empty() {
        return Err("flash_args 中未找到烧录条目".into());
    }

    Ok(FlashArgsImport {
        entries,
        flash_mode,
        flash_freq,
    })
}

#[tauri::command]
fn start_flash(
    app: AppHandle,
    ports: Vec<String>,
    firmwares: Vec<FirmwareItem>,
    config: AppConfig,
    manager: State<'_, FlashManager>,
) -> Result<(), String> {
    if ports.is_empty() {
        return Err("请选择至少一个串口".into());
    }
    let mut ports: Vec<String> = ports
        .into_iter()
        .collect::<std::collections::HashSet<_>>()
        .into_iter()
        .collect();
    ports.sort_by_key(|p| com_port_num(p));
    if firmwares.is_empty() {
        return Err("请选择至少一个固件".into());
    }
    let monitor = app.state::<SerialMonitorManager>();
    for port in ports {
        let _ = monitor.close(&port);
        manager.start(app.clone(), port, firmwares.clone(), config.clone());
    }
    Ok(())
}

#[tauri::command]
fn stop_flash(port: Option<String>, manager: State<'_, FlashManager>) {
    manager.stop(port.as_deref());
}

#[tauri::command]
fn erase_single_port(
    app: AppHandle,
    port: String,
    baudrate: u32,
) -> Result<(), String> {
    if port.is_empty() {
        return Err("请先选择串口".into());
    }
    let monitor = app.state::<SerialMonitorManager>();
    let _ = monitor.close(&port);
    erase_port(app, port, baudrate);
    Ok(())
}

#[tauri::command]
async fn open_serial_monitor_window(app: AppHandle, port: String, baudrate: u32) -> Result<(), String> {
    if port.is_empty() {
        return Err("未选择串口".into());
    }
    let label = format!(
        "monitor-{}",
        port.chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() || c == '_' || c == '-' {
                    c
                } else {
                    '_'
                }
            })
            .collect::<String>()
    );
    if let Some(existing) = app.get_webview_window(&label) {
        existing.set_focus().map_err(|e| e.to_string())?;
        return Ok(());
    }

    let url = format!("/monitor.html?port={port}&baud={baudrate}&open=1");
    WebviewWindowBuilder::new(&app, &label, WebviewUrl::App(url.into()))
        .title(format!("ESP32 串口助手 - {port}"))
        .inner_size(960.0, 720.0)
        .min_inner_size(760.0, 560.0)
        .build()
        .map_err(|e| format!("创建串口窗口失败: {e}"))?;
    Ok(())
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct FlashRecord {
    time: String,
    port: String,
    chip_type: String,
    mac_address: String,
    success: bool,
    error_msg: String,
}

#[tauri::command]
fn export_records(path: String, records: Vec<FlashRecord>) -> Result<(), String> {
    let mut lines = vec!["烧录时间,端口,芯片型号,MAC地址,状态,错误信息".to_string()];
    for record in records {
        lines.push(format!(
            "{},{},{},{},{},{}",
            record.time,
            record.port,
            record.chip_type,
            record.mac_address,
            if record.success { "成功" } else { "失败" },
            record.error_msg.replace(',', "，")
        ));
    }
    fs::write(path, lines.join("\n")).map_err(|e| e.to_string())
}

#[tauri::command]
fn write_text_file(path: String, content: String) -> Result<(), String> {
    fs::write(path, content).map_err(|e| e.to_string())
}

#[tauri::command]
fn read_text_file(path: String) -> Result<String, String> {
    fs::read_to_string(path).map_err(|e| e.to_string())
}

#[tauri::command]
fn read_binary_file(path: String) -> Result<String, String> {
    let bytes = fs::read(&path).map_err(|e| e.to_string())?;
    Ok(STANDARD.encode(bytes))
}

fn start_port_monitor(app: AppHandle) {
    std::thread::spawn(move || {
        let mut old_ports = HashSet::new();
        loop {
            if let Ok(ports) = list_ports() {
                let current: HashSet<String> = ports.iter().cloned().collect();
                if current != old_ports {
                    let _ = app.emit(
                        "ports-changed",
                        PortsChangedEvent {
                            ports: ports.clone(),
                        },
                    );
                    old_ports = current;
                }
            }
            std::thread::sleep(Duration::from_millis(1500));
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(FlashManager::new())
        .manage(SerialMonitorManager::new())
        .invoke_handler(tauri::generate_handler![
            list_ports,
            get_config,
            set_config,
            check_esptool,
            start_flash,
            stop_flash,
            erase_single_port,
            open_serial_monitor_window,
            export_records,
            parse_flash_args,
            write_text_file,
            read_text_file,
            read_binary_file,
            serial_monitor::serial_monitor_open,
            serial_monitor::serial_monitor_close,
            serial_monitor::serial_monitor_write,
            serial_monitor::serial_monitor_pulse_reset,
            serial_monitor::serial_monitor_set_lines,
            serial_monitor::serial_monitor_is_open,
        ])
        .setup(|app| {
            start_port_monitor(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
