mod config;
mod esptool;
mod flash;

use config::{load_config, save_config, AppConfig};
use flash::{erase_port, FlashManager, FirmwareItem};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fs;
use std::time::Duration;
use tauri::{AppHandle, Emitter, State};

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct PortsChangedEvent {
    ports: Vec<String>,
}

#[tauri::command]
fn list_ports() -> Result<Vec<String>, String> {
    serialport::available_ports()
        .map_err(|e| e.to_string())
        .map(|ports| ports.into_iter().map(|p| p.port_name).collect())
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
fn check_esptool() -> Result<String, String> {
    let (program, prefix) = esptool::find_esptool()?;
    if prefix.is_empty() {
        Ok(program)
    } else {
        Ok(format!("{} {}", program, prefix.join(" ")))
    }
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
    if firmwares.is_empty() {
        return Err("请选择至少一个固件".into());
    }
    for port in ports {
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
    erase_port(app, port, baudrate);
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
        .invoke_handler(tauri::generate_handler![
            list_ports,
            get_config,
            set_config,
            check_esptool,
            start_flash,
            stop_flash,
            erase_single_port,
            export_records,
        ])
        .setup(|app| {
            start_port_monitor(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
