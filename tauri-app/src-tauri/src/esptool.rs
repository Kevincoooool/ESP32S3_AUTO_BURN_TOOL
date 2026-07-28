use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::Arc;
use std::time::Duration;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub fn find_esptool() -> Result<(String, Vec<String>), String> {
    for candidate in ["esptool", "esptool.exe"] {
        let status = Command::new(candidate)
            .arg("--help")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        if matches!(status, Ok(s) if s.success()) {
            return Ok((candidate.to_string(), Vec::new()));
        }
    }

    for python in ["python", "python3", "py"] {
        let status = Command::new(python)
            .args(["-m", "esptool", "--help"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        if matches!(status, Ok(s) if s.success()) {
            return Ok((python.to_string(), vec!["-m".to_string(), "esptool".to_string()]));
        }
    }

    Err("未找到 esptool，请安装: pip install esptool".to_string())
}

pub fn run_esptool<F>(
    args: &[String],
    cancel: Arc<AtomicBool>,
    mut on_line: F,
) -> Result<String, String>
where
    F: FnMut(&str),
{
    if cancel.load(Ordering::Relaxed) {
        return Err("cancelled".to_string());
    }

    let (program, prefix) = find_esptool()?;
    let mut cmd = Command::new(&program);
    cmd.args(&prefix).args(args);
    cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = cmd.spawn().map_err(|e| format!("启动 esptool 失败: {e}"))?;
    let stdout = child.stdout.take().ok_or("无法读取 esptool 输出")?;
    let stderr = child.stderr.take().ok_or("无法读取 esptool 错误输出")?;

    let (tx, rx) = mpsc::channel::<String>();

    let cancel_out = cancel.clone();
    let tx_out = tx.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(|result| result.ok()) {
            if cancel_out.load(Ordering::Relaxed) {
                break;
            }
            let _ = tx_out.send(line);
        }
    });

    let cancel_err = cancel.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines().map_while(|result| result.ok()) {
            if cancel_err.load(Ordering::Relaxed) {
                break;
            }
            if !line.trim().is_empty() {
                let _ = tx.send(line);
            }
        }
    });

    let mut captured = String::new();

    loop {
        while let Ok(text) = rx.try_recv() {
            captured.push_str(&text);
            captured.push('\n');
            on_line(&text);
        }

        if cancel.load(Ordering::Relaxed) {
            let _ = child.kill();
            break;
        }

        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => std::thread::sleep(Duration::from_millis(50)),
            Err(e) => return Err(e.to_string()),
        }
    }

    while let Ok(text) = rx.try_recv() {
        captured.push_str(&text);
        captured.push('\n');
        on_line(&text);
    }

    let status = child.wait().map_err(|e| e.to_string())?;

    if cancel.load(Ordering::Relaxed) {
        return Err("cancelled".to_string());
    }
    if !status.success() {
        return Err(format!("esptool 退出码 {}", status.code().unwrap_or(-1)));
    }

    Ok(captured)
}

pub fn detect_chip(output: &str) -> Option<String> {
    let upper = output.to_uppercase();
    let chips = [
        ("ESP32-P4", "ESP32-P4"),
        ("ESP32P4", "ESP32-P4"),
        ("ESP32-S3", "ESP32-S3"),
        ("ESP32S3", "ESP32-S3"),
        ("ESP32-S2", "ESP32-S2"),
        ("ESP32S2", "ESP32-S2"),
        ("ESP32-C6", "ESP32-C6"),
        ("ESP32C6", "ESP32-C6"),
        ("ESP32-H2", "ESP32-H2"),
        ("ESP32H2", "ESP32-H2"),
        ("ESP32-C3", "ESP32-C3"),
        ("ESP32C3", "ESP32-C3"),
        ("ESP32-C2", "ESP32-C2"),
        ("ESP32C2", "ESP32-C2"),
        ("ESP32", "ESP32"),
    ];
    for (needle, label) in chips {
        if upper.contains(needle) {
            return Some(label.to_string());
        }
    }
    None
}

pub fn parse_mac(output: &str) -> Option<String> {
    let re = regex::Regex::new(
        r"MAC:\s*([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})",
    )
    .ok()?;
    re.captures(output).map(|cap| cap[1].to_string())
}
