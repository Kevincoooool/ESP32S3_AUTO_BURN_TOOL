//! Rust 烧录后端，基于 espflash（协议与官方 esptool 5.x 对齐）。
//! 芯片专用逻辑参考 esptool targets/：
//! - esp32p4.py  power_on_flash / hard_reset (USB OTG → watchdog)
//! - esp32s31.py hard_reset (USB OTG → watchdog)
//! - esp32c5.py  hard_reset (USB Serial/JTAG → 延长 DTR/RTS 时序)
//! - esp32h2.py  标准 hard_reset（不支持 watchdog 复位）

use espflash::command::{Command, CommandType};
use espflash::connection::{Connection, ResetAfterOperation, ResetBeforeOperation};
use espflash::flasher::{DeviceInfo, Flasher};
use espflash::image_format::Segment;
use espflash::target::{Chip, ProgressCallbacks};
use serialport::{FlowControl, SerialPort, SerialPortType, UsbPortInfo};
use std::borrow::Cow;
use std::fs;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::sleep;
use std::time::Duration;

const ESPRESSIF_VID: u16 = 0x303A;
const USB_SERIAL_JTAG_PID: u16 = 0x1001;

pub fn supported_chips() -> &'static [&'static str] {
    &[
        "ESP32",
        "ESP32-S2",
        "ESP32-S3",
        "ESP32-S31",
        "ESP32-C2",
        "ESP32-C3",
        "ESP32-C5",
        "ESP32-C6",
        "ESP32-C61",
        "ESP32-H2",
        "ESP32-H4",
        "ESP32-P4",
    ]
}

pub fn flasher_info() -> String {
    format!(
        "内置 espflash 4.6 (Rust 原生，对齐 esptool 5.x) · 支持 {}",
        supported_chips().join(" / ")
    )
}

pub fn format_chip(chip: Chip) -> String {
    match chip.to_string().as_str() {
        "esp32" => "ESP32".into(),
        "esp32s2" => "ESP32-S2".into(),
        "esp32s3" => "ESP32-S3".into(),
        "esp32s31" => "ESP32-S31".into(),
        "esp32c2" => "ESP32-C2".into(),
        "esp32c3" => "ESP32-C3".into(),
        "esp32c5" => "ESP32-C5".into(),
        "esp32c6" => "ESP32-C6".into(),
        "esp32c61" => "ESP32-C61".into(),
        "esp32h2" => "ESP32-H2".into(),
        "esp32h4" => "ESP32-H4".into(),
        "esp32p4" => "ESP32-P4".into(),
        other => other.into(),
    }
}

fn is_usb_serial_jtag(vid: u16, pid: u16) -> bool {
    vid == ESPRESSIF_VID && pid == USB_SERIAL_JTAG_PID
}

fn chip_uses_watchdog_on_usb_otg(chip: Chip) -> bool {
    matches!(chip, Chip::Esp32p4 | Chip::Esp32s31)
}

pub fn format_chip_with_revision(info: &DeviceInfo) -> String {
    let mut chip = format_chip(info.chip);
    if let Some((major, minor)) = info.revision {
        chip = format!("{chip} (revision v{major}.{minor})");
    }
    chip
}

pub fn chip_and_mac(info: &DeviceInfo) -> (String, String) {
    let chip = format_chip_with_revision(info);
    let mac = info
        .mac_address
        .clone()
        .unwrap_or_else(|| "Unknown".to_string());
    (chip, mac)
}

pub fn emit_device_info(info: &DeviceInfo, emit: &dyn Fn(&str)) {
    emit(&format!("检测到芯片: {}", format_chip_with_revision(info)));
    emit(&format!("晶振频率: {}", info.crystal_frequency));
    emit(&format!("Flash 大小: {}", info.flash_size));
    if !info.features.is_empty() {
        emit(&format!("特性: {}", info.features.join(", ")));
    }
    if let Some(ref mac) = info.mac_address {
        emit(&format!("MAC地址: {mac}"));
    }
}

pub fn parse_address(addr: &str) -> Result<u32, String> {
    let s = addr.trim();
    let hex = s
        .strip_prefix("0x")
        .or_else(|| s.strip_prefix("0X"))
        .unwrap_or(s);
    u32::from_str_radix(hex, 16).map_err(|e| format!("无效地址 {addr}: {e}"))
}

pub const FLASH_CANCELLED: &str = "flash_cancelled";

pub fn is_cancel_error(err: &str, cancel: &Arc<AtomicBool>) -> bool {
    cancel.load(Ordering::Relaxed)
        || err.contains("Interrupted")
        || err.contains("cancelled")
        || err.contains(FLASH_CANCELLED)
}

fn check_cancelled(cancel: &Arc<AtomicBool>) {
    if cancel.load(Ordering::Relaxed) {
        panic!("{FLASH_CANCELLED}");
    }
}

pub fn open_flasher(port: &str, baud: u32, cancel: Arc<AtomicBool>) -> Result<Flasher, String> {
    let available = serialport::available_ports().map_err(|e| e.to_string())?;
    let port_info = available
        .iter()
        .find(|p| p.port_name == port)
        .ok_or_else(|| format!("串口 {port} 不存在或未连接"))?;

    let usb_info = match &port_info.port_type {
        SerialPortType::UsbPort(info) => info.clone(),
        _ => UsbPortInfo {
            vid: 0,
            pid: 0,
            serial_number: None,
            manufacturer: None,
            product: None,
        },
    };

    if cancel.load(Ordering::Relaxed) {
        return Err("cancelled".to_string());
    }

    let mut serial_port = serialport::new(port, 115_200)
        .flow_control(FlowControl::None)
        .open_native()
        .map_err(|e| format!("无法打开串口 {port}: {e}"))?;

    let _ = set_serial_safe_idle(&mut serial_port);

    let connection = Connection::new(
        serial_port,
        usb_info,
        ResetAfterOperation::HardReset,
        ResetBeforeOperation::DefaultReset,
        115_200,
    );

    Flasher::connect(connection, true, false, false, None, Some(baud)).map_err(|e| e.to_string())
}


pub fn port_usb_ids(port: &str) -> (u16, u16) {
    serialport::available_ports()
        .ok()
        .and_then(|ports| {
            ports.iter().find(|p| p.port_name == port).map(|p| {
                if let SerialPortType::UsbPort(info) = &p.port_type {
                    (info.vid, info.pid)
                } else {
                    (0, 0)
                }
            })
        })
        .unwrap_or((0, 0))
}

pub struct LogProgress<'a> {
    pub emit: &'a dyn Fn(&str),
    pub cancel: Arc<AtomicBool>,
    flash_addr: u32,
    total: usize,
    last_pct: i32,
}

impl<'a> LogProgress<'a> {
    pub fn new(emit: &'a dyn Fn(&str), cancel: Arc<AtomicBool>) -> Self {
        Self {
            emit,
            cancel,
            flash_addr: 0,
            total: 0,
            last_pct: -1,
        }
    }
}

impl ProgressCallbacks for LogProgress<'_> {
    fn init(&mut self, addr: u32, total: usize) {
        check_cancelled(&self.cancel);
        self.flash_addr = addr;
        self.total = total;
        self.last_pct = -1;
        (self.emit)(&format!("writing at {addr:#010x}..."));
    }

    fn update(&mut self, current: usize) {
        check_cancelled(&self.cancel);
        if self.total == 0 {
            return;
        }
        let pct = (current as f64 / self.total as f64) * 100.0;
        let pct_step = pct.floor() as i32;
        if pct_step != self.last_pct {
            self.last_pct = pct_step;
            (self.emit)(&format!(
                "Writing at {:#010x}... ({pct:.1} %)",
                self.flash_addr
            ));
        }
    }

    fn verifying(&mut self) {
        (self.emit)("Hash of data verified");
    }

    fn finish(&mut self, _skipped: bool) {}
}

pub fn read_device_info(flasher: &mut Flasher) -> Result<DeviceInfo, String> {
    flasher.device_info().map_err(|e| e.to_string())
}

pub fn erase_flash(flasher: &mut Flasher) -> Result<(), String> {
    flasher.erase_flash().map_err(|e| e.to_string())
}

fn pad_firmware_data(data: &mut Vec<u8>) {
    if !data.len().is_multiple_of(4) {
        let pad = 4 - (data.len() % 4);
        data.extend(std::iter::repeat_n(0xFF, pad));
    }
}

pub fn write_all_firmwares(
    flasher: &mut Flasher,
    items: &[(String, String)],
    cancel: Arc<AtomicBool>,
    emit: &dyn Fn(&str),
) -> Result<(), String> {
    if cancel.load(Ordering::Relaxed) {
        return Err("cancelled".to_string());
    }

    let mut segments = Vec::with_capacity(items.len());
    for (path, address) in items {
        if cancel.load(Ordering::Relaxed) {
            return Err("cancelled".to_string());
        }
        let mut data = fs::read(path).map_err(|e| format!("读取固件失败 {path}: {e}"))?;
        pad_firmware_data(&mut data);
        let addr = parse_address(address)?;
        emit(&format!("write-flash {address} -> {addr:#010x} {path}"));
        segments.push(Segment {
            addr,
            data: Cow::Owned(data),
        });
    }

    for segment in segments {
        check_cancelled(&cancel);
        let mut progress = LogProgress::new(emit, cancel.clone());
        flasher
            .write_bin_to_flash(segment.addr, &segment.data, &mut progress)
            .map_err(|e| {
                let msg = e.to_string();
                if is_cancel_error(&msg, &cancel) {
                    "cancelled".to_string()
                } else {
                    msg
                }
            })?;
    }

    Ok(())
}

fn write_dtr(serial: &mut dyn SerialPort, level: bool) -> Result<(), String> {
    serial
        .write_data_terminal_ready(level)
        .map_err(|e| e.to_string())?;
    #[cfg(windows)]
    {
        serial.write_request_to_send(!level).ok();
        serial
            .write_data_terminal_ready(level)
            .map_err(|e| e.to_string())?;
        serial.write_request_to_send(level).ok();
        serial
            .write_data_terminal_ready(level)
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn write_rts(serial: &mut dyn SerialPort, level: bool) -> Result<(), String> {
    serial
        .write_request_to_send(level)
        .map_err(|e| e.to_string())
}

fn set_serial_safe_idle(serial: &mut dyn SerialPort) -> Result<(), String> {
    write_dtr(serial, false)?;
    write_rts(serial, false)?;
    sleep(Duration::from_millis(30));
    write_dtr(serial, true)?;
    write_rts(serial, true)?;
    sleep(Duration::from_millis(30));
    write_dtr(serial, false)?;
    write_rts(serial, false)?;
    Ok(())
}

fn run_mode_reset_uart(serial: &mut dyn SerialPort) -> Result<(), String> {
    write_dtr(serial, false)?;
    write_rts(serial, true)?;
    sleep(Duration::from_millis(100));
    write_dtr(serial, false)?;
    write_rts(serial, false)?;
    sleep(Duration::from_millis(100));
    set_serial_safe_idle(serial)?;
    Ok(())
}

/// USB Serial/JTAG 复位（esptool reset.py HardReset uses_usb=True：更长 hold/release）
fn run_mode_reset_usb_jtag(serial: &mut dyn SerialPort) -> Result<(), String> {
    write_dtr(serial, false)?;
    sleep(Duration::from_millis(200));
    write_rts(serial, true)?;
    write_dtr(serial, false)?;
    write_rts(serial, true)?;
    sleep(Duration::from_millis(200));
    write_rts(serial, false)?;
    write_dtr(serial, false)?;
    sleep(Duration::from_millis(200));
    Ok(())
}

fn run_mode_reset_jtag(serial: &mut dyn SerialPort) -> Result<(), String> {
    write_dtr(serial, false)?;
    sleep(Duration::from_millis(100));
    write_rts(serial, true)?;
    write_dtr(serial, false)?;
    write_rts(serial, true)?;
    sleep(Duration::from_millis(100));
    write_rts(serial, false)?;
    write_dtr(serial, false)?;
    Ok(())
}

fn run_mode_reset_serial(
    serial: &mut dyn SerialPort,
    vid: u16,
    pid: u16,
    chip: Chip,
) -> Result<(), String> {
    let use_usb_jtag_timing = is_usb_serial_jtag(vid, pid)
        || (matches!(chip, Chip::Esp32c5 | Chip::Esp32h2 | Chip::Esp32s31) && pid == USB_SERIAL_JTAG_PID);

    if use_usb_jtag_timing {
        run_mode_reset_usb_jtag(serial)
    } else if pid == USB_SERIAL_JTAG_PID {
        run_mode_reset_jtag(serial)
    } else {
        run_mode_reset_uart(serial)
    }
}

fn run_user_code_from_stub(connection: &mut Connection) -> Result<(), String> {
    connection
        .with_timeout(CommandType::RunUserCode.timeout(), |conn| {
            conn.command(Command::RunUserCode).map(|_| ())
        })
        .map_err(|e| e.to_string())
}

pub fn serial_post_flash_reset(port: &str) -> Result<(), String> {
    let (vid, pid) = port_usb_ids(port);
    sleep(Duration::from_millis(100));

    let mut serial = serialport::new(port, 115_200)
        .timeout(Duration::from_millis(200))
        .open()
        .map_err(|e| format!("无法打开串口进行复位 {port}: {e}"))?;

    set_serial_safe_idle(&mut *serial)?;
    run_mode_reset_serial(&mut *serial, vid, pid, Chip::Esp32)?;
    set_serial_safe_idle(&mut *serial)?;

    Ok(())
}

pub fn finish_and_reset(flasher: Flasher, port: &str, emit: &dyn Fn(&str)) -> Result<(), String> {
    let chip = flasher.chip();
    let mut connection = flasher.into_connection();
    let (vid, pid) = port_usb_ids(port);

    emit("退出烧录模式，运行用户程序...");
    if run_user_code_from_stub(&mut connection).is_ok() {
        sleep(Duration::from_millis(150));
    }

    if chip_uses_watchdog_on_usb_otg(chip) && chip.is_using_usb_otg(&mut connection).unwrap_or(false)
    {
        emit("检测到 USB OTG，通过看门狗复位...");
        chip.rtc_wdt_reset(&mut connection)
            .map_err(|e| e.to_string())?;
        sleep(Duration::from_millis(500));
        return Ok(());
    }

    let usb_jtag = is_usb_serial_jtag(vid, pid);
    if usb_jtag && matches!(chip, Chip::Esp32c5 | Chip::Esp32h2 | Chip::Esp32s31) {
        emit("hard resetting via USB Serial/JTAG...");
    } else {
        emit("hard resetting via RTS/DTR...");
    }

    connection.reset().map_err(|e| e.to_string())?;
    sleep(Duration::from_millis(if usb_jtag { 200 } else { 50 }));

    let mut serial = connection.into_serial();
    run_mode_reset_serial(&mut serial, vid, pid, chip)?;
    set_serial_safe_idle(&mut serial)?;
    Ok(())
}
