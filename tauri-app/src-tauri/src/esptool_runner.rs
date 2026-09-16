use regex::Regex;
use serialport::{FlowControl, SerialPort};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;
use tauri::AppHandle;

const USB_SERIAL_JTAG_PID: u16 = 0x1001;

pub fn flasher_info(app: &AppHandle) -> Result<String, String> {
    let bin = resolve_esptool_binary(app)?;
    let output = Command::new(&bin)
        .arg("version")
        .output()
        .map_err(|e| format!("无法运行 esptool: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "esptool 不可用: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    Ok(format!(
        "内置 esptool {}",
        String::from_utf8_lossy(&output.stdout).trim()
    ))
}

pub fn resolve_esptool_binary(_app: &AppHandle) -> Result<PathBuf, String> {
    let ext = if cfg!(windows) { ".exe" } else { "" };
    let file_name = format!("esptool-{}{}", env!("BUILD_TARGET"), ext);

    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let bundled = dir.join(&file_name);
            if bundled.is_file() {
                return Ok(bundled);
            }
            let plain = dir.join(format!("esptool{ext}"));
            if plain.is_file() {
                return Ok(plain);
            }
        }
    }

    let dev = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("binaries")
        .join(&file_name);
    if dev.is_file() {
        return Ok(dev);
    }

    Err(format!(
        "未找到 esptool sidecar ({file_name})，请先运行 build_esptool_sidecar.bat"
    ))
}

pub fn detect_chip_and_mac(
    app: &AppHandle,
    port: &str,
    baud: u32,
    cancel: Arc<AtomicBool>,
    emit: &dyn Fn(&str),
) -> Result<(String, String), String> {
    let output = run_esptool(
        app,
        port,
        baud,
        &["read_mac"],
        cancel,
        emit,
    )?;
    Ok(parse_chip_and_mac(&output))
}

pub fn parse_chip_and_mac(output: &str) -> (String, String) {
    let upper = output.to_uppercase();
    let chip_type = if upper.contains("ESP32-P4") || upper.contains("ESP32P4") {
        "ESP32-P4".to_string()
    } else if upper.contains("ESP32-S3") || upper.contains("ESP32S3") {
        "ESP32-S3".to_string()
    } else if upper.contains("ESP32-S2") || upper.contains("ESP32S2") {
        "ESP32-S2".to_string()
    } else if upper.contains("ESP32-C6") || upper.contains("ESP32C6") {
        "ESP32-C6".to_string()
    } else if upper.contains("ESP32-C3") || upper.contains("ESP32C3") {
        "ESP32-C3".to_string()
    } else if upper.contains("ESP32-H2") || upper.contains("ESP32H2") {
        "ESP32-H2".to_string()
    } else if upper.contains("ESP32-C2") || upper.contains("ESP32C2") {
        "ESP32-C2".to_string()
    } else if upper.contains("ESP32") {
        "ESP32".to_string()
    } else {
        "Unknown".to_string()
    };

    let mac = Regex::new(r"(?i)MAC:\s*([0-9a-f]{2}(?::[0-9a-f]{2}){5})")
        .ok()
        .and_then(|re| re.captures(output))
        .and_then(|caps| caps.get(1).map(|m| m.as_str().to_string()))
        .unwrap_or_else(|| "Unknown".to_string());

    (chip_type, mac)
}

pub fn run_esptool(
    app: &AppHandle,
    port: &str,
    baud: u32,
    args: &[&str],
    cancel: Arc<AtomicBool>,
    emit: &dyn Fn(&str),
) -> Result<String, String> {
    if cancel.load(Ordering::Relaxed) {
        return Err("cancelled".to_string());
    }

    let bin = resolve_esptool_binary(app)?;
    let mut cmd = Command::new(&bin);
    cmd.arg("--port").arg(port);
    cmd.arg("--baud").arg(baud.to_string());
    cmd.args(args);
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    emit(&format!(
        "esptool --port {port} --baud {baud} {}",
        args.join(" ")
    ));

    let mut child = cmd.spawn().map_err(|e| format!("启动 esptool 失败: {e}"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "无法读取 esptool 输出".to_string())?;
    let stderr = child.stderr.take();

    let mut captured = String::new();
    let reader = BufReader::new(stdout);
    for line in reader.lines() {
        if cancel.load(Ordering::Relaxed) {
            kill_child(&mut child);
            return Err("cancelled".to_string());
        }
        let line = line.map_err(|e| format!("读取 esptool 输出失败: {e}"))?;
        if !line.trim().is_empty() {
            emit(&line);
            captured.push_str(&line);
            captured.push('\n');
        }
    }

    if let Some(stderr) = stderr {
        let err_reader = BufReader::new(stderr);
        for line in err_reader.lines().flatten() {
            if !line.trim().is_empty() {
                emit(&line);
                captured.push_str(&line);
                captured.push('\n');
            }
        }
    }

    let status = child.wait().map_err(|e| format!("等待 esptool 结束失败: {e}"))?;
    if cancel.load(Ordering::Relaxed) {
        return Err("cancelled".to_string());
    }
    if !status.success() {
        return Err(format!(
            "esptool 退出码 {}",
            status.code().unwrap_or(-1)
        ));
    }

    Ok(captured)
}

fn kill_child(child: &mut Child) {
    #[cfg(windows)]
    {
        let _ = Command::new("taskkill")
            .args(["/F", "/T", "/PID", &child.id().to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    #[cfg(not(windows))]
    {
        let _ = child.kill();
    }
}

pub fn write_firmwares(
    app: &AppHandle,
    port: &str,
    baud: u32,
    items: &[(String, String)],
    flash_mode: &str,
    flash_freq: &str,
    cancel: Arc<AtomicBool>,
    emit: &dyn Fn(&str),
) -> Result<(), String> {
    let mut args: Vec<String> = vec![
        "--before".into(),
        "default_reset".into(),
        "--after".into(),
        "hard_reset".into(),
    ];
    if flash_mode != "keep" {
        args.push("--flash_mode".into());
        args.push(flash_mode.to_string());
    }
    if flash_freq != "keep" {
        args.push("--flash_freq".into());
        args.push(flash_freq.to_string());
    }
    args.push("write_flash".into());
    for (path, address) in items {
        args.push(address.clone());
        args.push(path.clone());
        emit(&format!("write-flash {address} -> {path}"));
    }

    let arg_refs: Vec<&str> = args.iter().map(String::as_str).collect();
    run_esptool(app, port, baud, &arg_refs, cancel, emit).map(|_| ())
}

pub fn erase_flash(
    app: &AppHandle,
    port: &str,
    baud: u32,
    cancel: Arc<AtomicBool>,
    emit: &dyn Fn(&str),
) -> Result<(), String> {
    run_esptool(app, port, baud, &["erase_flash"], cancel, emit).map(|_| ())
}

pub fn serial_post_flash_reset(port: &str) -> Result<(), String> {
    thread::sleep(Duration::from_millis(100));

    let mut serial = serialport::new(port, 115_200)
        .timeout(Duration::from_millis(200))
        .flow_control(FlowControl::None)
        .open()
        .map_err(|e| format!("无法打开串口进行复位 {port}: {e}"))?;

    let pid = serialport::available_ports()
        .ok()
        .and_then(|ports| {
            ports
                .into_iter()
                .find(|p| p.port_name == port)
                .and_then(|p| match p.port_type {
                    serialport::SerialPortType::UsbPort(info) => Some(info.pid),
                    _ => None,
                })
        })
        .unwrap_or(0);

    set_serial_safe_idle(&mut *serial)?;
    run_mode_reset_serial(&mut *serial, pid)?;
    set_serial_safe_idle(&mut *serial)?;
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
    thread::sleep(Duration::from_millis(30));
    write_dtr(serial, true)?;
    write_rts(serial, true)?;
    thread::sleep(Duration::from_millis(30));
    write_dtr(serial, false)?;
    write_rts(serial, false)?;
    Ok(())
}

fn run_mode_reset_uart(serial: &mut dyn SerialPort) -> Result<(), String> {
    write_dtr(serial, false)?;
    write_rts(serial, true)?;
    thread::sleep(Duration::from_millis(100));
    write_dtr(serial, false)?;
    write_rts(serial, false)?;
    thread::sleep(Duration::from_millis(100));
    set_serial_safe_idle(serial)?;
    Ok(())
}

fn run_mode_reset_jtag(serial: &mut dyn SerialPort) -> Result<(), String> {
    write_dtr(serial, false)?;
    thread::sleep(Duration::from_millis(100));
    write_rts(serial, true)?;
    write_dtr(serial, false)?;
    write_rts(serial, true)?;
    thread::sleep(Duration::from_millis(100));
    write_rts(serial, false)?;
    write_dtr(serial, false)?;
    Ok(())
}

fn run_mode_reset_serial(serial: &mut dyn SerialPort, pid: u16) -> Result<(), String> {
    if pid == USB_SERIAL_JTAG_PID {
        run_mode_reset_jtag(serial)
    } else {
        run_mode_reset_uart(serial)
    }
}
