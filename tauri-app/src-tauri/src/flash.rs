use crate::config::AppConfig;
use crate::esptool_runner::{detect_chip_and_mac, erase_flash, serial_post_flash_reset, write_firmwares};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, Manager};

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FlashLogEvent {
    pub port: String,
    pub line: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FlashCompleteEvent {
    pub port: String,
    pub success: bool,
    pub chip_type: String,
    pub mac_address: String,
    pub error_msg: String,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FirmwareItem {
    pub path: String,
    pub address: String,
}

pub struct FlashManager {
    cancel_flags: Mutex<HashMap<String, Arc<AtomicBool>>>,
}

impl FlashManager {
    pub fn new() -> Self {
        Self {
            cancel_flags: Mutex::new(HashMap::new()),
        }
    }

    pub fn is_busy(&self, port: &str) -> bool {
        self.cancel_flags.lock().unwrap().contains_key(port)
    }

    pub fn stop(&self, port: Option<&str>) {
        let flags = self.cancel_flags.lock().unwrap();
        match port {
            Some(p) => {
                if let Some(flag) = flags.get(p) {
                    flag.store(true, Ordering::Relaxed);
                }
            }
            None => {
                for flag in flags.values() {
                    flag.store(true, Ordering::Relaxed);
                }
            }
        }
    }

    pub fn start(
        &self,
        app: AppHandle,
        port: String,
        firmwares: Vec<FirmwareItem>,
        config: AppConfig,
    ) {
        let cancel = Arc::new(AtomicBool::new(false));
        {
            let mut flags = self.cancel_flags.lock().unwrap();
            flags.insert(port.clone(), cancel.clone());
        }

        std::thread::spawn(move || {
            let result = run_flash_job(&app, &port, &firmwares, &config, cancel.clone());
            {
                let state = app.state::<FlashManager>();
                let mut flags = state.cancel_flags.lock().unwrap();
                flags.remove(&port);
            }
            let _ = app.emit("flash-complete", result);
        });
    }
}

fn emit_log(app: &AppHandle, port: &str, line: &str) {
    let _ = app.emit(
        "flash-log",
        FlashLogEvent {
            port: port.to_string(),
            line: line.to_string(),
        },
    );
}

fn cancelled_event(port: &str, chip_type: String, mac_address: String) -> FlashCompleteEvent {
    FlashCompleteEvent {
        port: port.to_string(),
        success: false,
        chip_type,
        mac_address,
        error_msg: "cancelled".into(),
    }
}

fn cleanup_port(port: &str, emit: &dyn Fn(&str)) {
    if let Err(e) = serial_post_flash_reset(port) {
        emit(&format!("复位警告: {e}"));
    }
}

fn fail_with_cleanup(
    port: &str,
    chip_type: String,
    mac_address: String,
    error_msg: String,
    emit: &dyn Fn(&str),
) -> FlashCompleteEvent {
    emit(&format!("错误: {error_msg}"));
    cleanup_port(port, emit);
    FlashCompleteEvent {
        port: port.to_string(),
        success: false,
        chip_type,
        mac_address,
        error_msg,
    }
}

fn run_flash_job(
    app: &AppHandle,
    port: &str,
    firmwares: &[FirmwareItem],
    config: &AppConfig,
    cancel: Arc<AtomicBool>,
) -> FlashCompleteEvent {
    let mut chip_type = "Unknown".to_string();
    let mut mac_address = "Unknown".to_string();

    let emit = |line: &str| emit_log(app, port, line);

    emit(&format!("开始为端口 {port} 烧录固件..."));

    if cancel.load(Ordering::Relaxed) {
        return cancelled_event(port, chip_type, mac_address);
    }

    emit("Connecting...");
    match detect_chip_and_mac(app, port, config.baudrate, cancel.clone(), &emit) {
        Ok((chip, mac)) => {
            chip_type = chip;
            mac_address = mac;
            emit(&format!("检测到芯片类型: {chip_type}"));
            if mac_address != "Unknown" {
                emit(&format!("MAC地址: {mac_address}"));
            }
        }
        Err(e) if e == "cancelled" => {
            return cancelled_event(port, chip_type, mac_address);
        }
        Err(e) => {
            return fail_with_cleanup(port, chip_type, mac_address, e, &emit);
        }
    }

    if config.erase_flash {
        if cancel.load(Ordering::Relaxed) {
            return cancelled_event(port, chip_type, mac_address);
        }
        emit("正在擦除 Flash...");
        if let Err(e) = erase_flash(app, port, config.baudrate, cancel.clone(), &emit) {
            let msg = if e == "cancelled" {
                "cancelled".to_string()
            } else {
                format!("擦除失败: {e}")
            };
            return fail_with_cleanup(port, chip_type, mac_address, msg, &emit);
        }
        emit("Flash 擦除完成!");
    }

    let firmware_items: Vec<(String, String)> = firmwares
        .iter()
        .map(|item| (item.path.clone(), item.address.clone()))
        .collect();

    emit(&format!(
        "执行命令: esptool write_flash ({} 个文件)",
        firmware_items.len()
    ));
    if let Err(e) = write_firmwares(
        app,
        port,
        config.baudrate,
        &firmware_items,
        &config.flash_mode,
        &config.flash_freq,
        cancel.clone(),
        &emit,
    ) {
        let msg = if e == "cancelled" {
            "cancelled".to_string()
        } else {
            e
        };
        return fail_with_cleanup(port, chip_type, mac_address, msg, &emit);
    }

    for item in firmwares {
        emit(&format!("固件 {} 烧录完成!", item.path));
    }

    if let Err(e) = serial_post_flash_reset(port) {
        emit(&format!("复位警告: {e}"));
    } else {
        emit("hard resetting via RTS/DTR...");
    }

    emit(&format!("端口 {port} 所有固件烧录完成!"));
    FlashCompleteEvent {
        port: port.to_string(),
        success: true,
        chip_type,
        mac_address,
        error_msg: String::new(),
    }
}

pub fn erase_port(app: AppHandle, port: String, baudrate: u32) {
    std::thread::spawn(move || {
        let cancel = Arc::new(AtomicBool::new(false));
        let emit = |line: &str| emit_log(&app, &port, line);
        emit(&format!("开始擦除端口 {port} 的 Flash..."));

        let result = (|| {
            emit("Connecting...");
            emit("erase_flash");
            erase_flash(&app, &port, baudrate, cancel.clone(), &emit)?;
            serial_post_flash_reset(&port)?;
            emit("Flash 擦除完成!");
            Ok::<(), String>(())
        })();

        if result.is_err() {
            cleanup_port(&port, &emit);
        }

        let (success, error_msg) = match result {
            Ok(()) => (true, String::new()),
            Err(e) => (
                false,
                if e == "cancelled" {
                    "cancelled".into()
                } else {
                    e
                },
            ),
        };

        let _ = app.emit(
            "flash-complete",
            FlashCompleteEvent {
                port,
                success,
                chip_type: "Erase".into(),
                mac_address: "-".into(),
                error_msg,
            },
        );
    });
}
