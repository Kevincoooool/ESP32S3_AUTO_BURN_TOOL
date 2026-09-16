use crate::config::AppConfig;
use crate::flasher::{
    chip_and_mac, emit_device_info, erase_flash, finish_and_reset, is_cancel_error, open_flasher,
    read_device_info, serial_post_flash_reset, write_all_firmwares, FLASH_CANCELLED,
};
use espflash::flasher::Flasher;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::panic::{catch_unwind, resume_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::sleep;
use std::time::Duration;
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
            let job = catch_unwind(AssertUnwindSafe(|| {
                run_flash_job(&app, &port, &firmwares, &config, cancel.clone())
            }));

            let result = match job {
                Ok(event) => event,
                Err(payload) => {
                    let panic_msg = panic_message(&payload);
                    if panic_msg.contains(FLASH_CANCELLED) {
                        emit_log(&app, &port, "烧录已停止，正在释放串口...");
                        sleep(Duration::from_millis(200));
                        if let Err(e) = serial_post_flash_reset(&port) {
                            emit_log(&app, &port, &format!("释放串口警告: {e}"));
                        } else {
                            emit_log(&app, &port, "串口已释放");
                        }
                        FlashCompleteEvent {
                            port: port.clone(),
                            success: false,
                            chip_type: "Unknown".into(),
                            mac_address: "Unknown".into(),
                            error_msg: "cancelled".into(),
                        }
                    } else {
                        resume_unwind(payload);
                    }
                }
            };

            {
                let state = app.state::<FlashManager>();
                let mut flags = state.cancel_flags.lock().unwrap();
                flags.remove(&port);
            }
            let _ = app.emit("flash-complete", result);
        });
    }
}

fn panic_message(payload: &Box<dyn std::any::Any + Send>) -> String {
    payload
        .downcast_ref::<&str>()
        .map(|s| (*s).to_string())
        .or_else(|| payload.downcast_ref::<String>().cloned())
        .unwrap_or_else(|| "unknown panic".to_string())
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

fn release_flasher_and_port(flasher: Flasher, port: &str, emit: &dyn Fn(&str)) {
    emit("烧录已停止，正在释放串口...");
    drop(flasher);
    sleep(Duration::from_millis(200));
    if let Err(e) = serial_post_flash_reset(port) {
        emit(&format!("释放串口警告: {e}"));
    } else {
        emit("串口已释放");
    }
}

fn stop_with_cleanup(
    port: &str,
    flasher: Flasher,
    chip_type: String,
    mac_address: String,
    emit: &dyn Fn(&str),
) -> FlashCompleteEvent {
    release_flasher_and_port(flasher, port, emit);
    cancelled_event(port, chip_type, mac_address)
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
    let mut flasher = match open_flasher(port, config.baudrate, cancel.clone()) {
        Ok(f) => f,
        Err(e) => {
            let msg = if is_cancel_error(&e, &cancel) {
                "cancelled".to_string()
            } else {
                e
            };
            return fail_with_cleanup(port, chip_type, mac_address, msg, &emit);
        }
    };

    if cancel.load(Ordering::Relaxed) {
        return stop_with_cleanup(port, flasher, chip_type, mac_address, &emit);
    }

    match read_device_info(&mut flasher) {
        Ok(info) => {
            let (chip, mac) = chip_and_mac(&info);
            chip_type = chip;
            mac_address = mac;
            emit_device_info(&info, &emit);
        }
        Err(e) if is_cancel_error(&e, &cancel) => {
            return stop_with_cleanup(port, flasher, chip_type, mac_address, &emit);
        }
        Err(e) => {
            drop(flasher);
            return fail_with_cleanup(port, chip_type, mac_address, e, &emit);
        }
    }

    if config.erase_flash {
        if cancel.load(Ordering::Relaxed) {
            return stop_with_cleanup(port, flasher, chip_type, mac_address, &emit);
        }
        emit("正在擦除 Flash...");
        if let Err(e) = erase_flash(&mut flasher) {
            let msg = if is_cancel_error(&e, &cancel) {
                "cancelled".to_string()
            } else {
                format!("擦除失败: {e}")
            };
            if msg == "cancelled" {
                return stop_with_cleanup(port, flasher, chip_type, mac_address, &emit);
            }
            drop(flasher);
            return fail_with_cleanup(port, chip_type, mac_address, msg, &emit);
        }
        emit("Flash 擦除完成!");
    }

    let firmware_items: Vec<(String, String)> = firmwares
        .iter()
        .map(|item| (item.path.clone(), item.address.clone()))
        .collect();

    emit(&format!(
        "write_flash ({} 个文件)",
        firmware_items.len()
    ));
    if let Err(e) = write_all_firmwares(&mut flasher, &firmware_items, cancel.clone(), &emit) {
        if e == "cancelled" || is_cancel_error(&e, &cancel) {
            return stop_with_cleanup(port, flasher, chip_type, mac_address, &emit);
        }
        drop(flasher);
        return fail_with_cleanup(port, chip_type, mac_address, e, &emit);
    }

    for item in firmwares {
        emit(&format!("固件 {} 烧录完成!", item.path));
    }

    if let Err(e) = finish_and_reset(flasher, port, &emit) {
        emit(&format!("复位警告: {e}"));
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
        let emit = |line: &str| emit_log(&app, &port, line);
        emit(&format!("开始擦除端口 {port} 的 Flash..."));

        let result = (|| {
            emit("Connecting...");
            let cancel = Arc::new(AtomicBool::new(false));
            let mut flasher = open_flasher(&port, baudrate, cancel)?;
            emit("erase_flash");
            erase_flash(&mut flasher)?;
            finish_and_reset(flasher, &port, &emit)?;
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
