use crate::config::AppConfig;
use crate::esptool::{detect_chip, parse_mac, run_esptool};
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

    let baud = config.baudrate.to_string();
    let read_args = vec![
        "--port".into(),
        port.into(),
        "--baud".into(),
        baud.clone(),
        "read-mac".into(),
    ];

    emit("检测芯片类型...");
    match run_esptool(&read_args, cancel.clone(), |line| emit(line)) {
        Ok(output) => {
            chip_type = detect_chip(&output).unwrap_or_else(|| "ESP32".to_string());
            mac_address = parse_mac(&output).unwrap_or_else(|| "Unknown".to_string());
            emit(&format!("检测到芯片类型: {chip_type}"));
            if mac_address != "Unknown" {
                emit(&format!("MAC地址: {mac_address}"));
            }
        }
        Err(e) if e == "cancelled" => {
            return FlashCompleteEvent {
                port: port.to_string(),
                success: false,
                chip_type,
                mac_address,
                error_msg: "cancelled".into(),
            };
        }
        Err(e) => {
            return FlashCompleteEvent {
                port: port.to_string(),
                success: false,
                chip_type,
                mac_address,
                error_msg: e,
            };
        }
    }

    if config.erase_flash {
        emit("正在擦除 Flash...");
        let erase_args = vec![
            "--port".into(),
            port.into(),
            "--baud".into(),
            baud.clone(),
            "erase-flash".into(),
        ];
        if let Err(e) = run_esptool(&erase_args, cancel.clone(), |line| emit(line)) {
            let msg = if e == "cancelled" {
                "cancelled".to_string()
            } else {
                format!("擦除失败: {e}")
            };
            return FlashCompleteEvent {
                port: port.to_string(),
                success: false,
                chip_type,
                mac_address,
                error_msg: msg,
            };
        }
        emit("Flash 擦除完成!");
    }

    for item in firmwares {
        if cancel.load(Ordering::Relaxed) {
            return FlashCompleteEvent {
                port: port.to_string(),
                success: false,
                chip_type,
                mac_address,
                error_msg: "cancelled".into(),
            };
        }

        let mut flash_args = vec![
            "--port".into(),
            port.into(),
            "--baud".into(),
            baud.clone(),
            "--before".into(),
            "default-reset".into(),
            "--after".into(),
            "hard-reset".into(),
        ];
        if config.flash_mode != "keep" {
            flash_args.push("--flash-mode".into());
            flash_args.push(config.flash_mode.clone());
        }
        if config.flash_freq != "keep" {
            flash_args.push("--flash-freq".into());
            flash_args.push(config.flash_freq.clone());
        }
        flash_args.push("write-flash".into());
        flash_args.push(item.address.clone());
        flash_args.push(item.path.clone());

        emit(&format!("执行命令: esptool {}", flash_args.join(" ")));
        if let Err(e) = run_esptool(&flash_args, cancel.clone(), |line| emit(line)) {
            let msg = if e == "cancelled" {
                "cancelled".to_string()
            } else {
                e
            };
            return FlashCompleteEvent {
                port: port.to_string(),
                success: false,
                chip_type,
                mac_address,
                error_msg: msg,
            };
        }
        emit(&format!("固件 {} 烧录完成!", item.path));
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
        let args = vec![
            "--port".into(),
            port.clone(),
            "--baud".into(),
            baudrate.to_string(),
            "erase-flash".into(),
        ];
        let result = run_esptool(&args, cancel, |line| emit(line));
        let success = result.is_ok();
        let error_msg = result.err().unwrap_or_default();
        let _ = app.emit(
            "flash-complete",
            FlashCompleteEvent {
                port,
                success,
                chip_type: "Erase".into(),
                mac_address: "-".into(),
                error_msg: if success {
                    String::new()
                } else if error_msg == "cancelled" {
                    "cancelled".into()
                } else {
                    error_msg
                },
            },
        );
    });
}
