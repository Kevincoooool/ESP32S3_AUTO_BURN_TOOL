use crate::flash::FlashManager;
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::Write as _;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, Sender, SyncSender};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use serialport::{DataBits, FlowControl, Parity, SerialPort, StopBits};
use tauri::{AppHandle, Emitter, State};

const READ_BUF_SIZE: usize = 8192;
const READ_TIMEOUT_MS: u64 = 50;
const WRITE_CHUNK_SIZE: usize = 4096;
const IO_REPLY_TIMEOUT: Duration = Duration::from_secs(3);

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SerialDataEvent {
    pub port: String,
    pub data: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SerialClosedEvent {
    pub port: String,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SerialOpenParams {
    pub port: String,
    pub baudrate: u32,
    pub data_bits: u8,
    pub stop_bits: u8,
    pub parity: String,
    pub dtr: bool,
    pub rts: bool,
}

enum IoRequest {
    Write(Vec<u8>, SyncSender<Result<usize, String>>),
    SetLines {
        dtr: bool,
        rts: bool,
        reply: SyncSender<Result<(), String>>,
    },
    PulseReset(SyncSender<Result<(), String>>),
}

struct MonitorSession {
    stop: Arc<AtomicBool>,
    io_tx: Sender<IoRequest>,
}

pub struct SerialMonitorManager {
    sessions: Mutex<HashMap<String, MonitorSession>>,
}

impl SerialMonitorManager {
    pub fn new() -> Self {
        Self {
            sessions: Mutex::new(HashMap::new()),
        }
    }

    pub fn is_open(&self, port: &str) -> bool {
        self.sessions.lock().unwrap().contains_key(port)
    }

    pub fn close(&self, port: &str) -> Result<(), String> {
        if let Some(session) = self.sessions.lock().unwrap().remove(port) {
            session.stop.store(true, Ordering::Relaxed);
            drop(session.io_tx);
        }
        Ok(())
    }

    pub fn open(
        &self,
        app: AppHandle,
        params: SerialOpenParams,
        flash_mgr: &FlashManager,
    ) -> Result<(), String> {
        if params.port.is_empty() {
            return Err("未选择串口".into());
        }
        if flash_mgr.is_busy(&params.port) {
            return Err(format!("端口 {} 正在烧录，无法打开串口监视", params.port));
        }

        self.close(&params.port)?;

        let mut port = serialport::new(&params.port, params.baudrate)
            .data_bits(parse_data_bits(params.data_bits)?)
            .stop_bits(parse_stop_bits(params.stop_bits)?)
            .parity(parse_parity(&params.parity)?)
            .flow_control(FlowControl::None)
            .timeout(Duration::from_millis(READ_TIMEOUT_MS))
            .open()
            .map_err(|e| format!("打开串口失败: {e}"))?;

        port.write_data_terminal_ready(params.dtr)
            .map_err(|e| format!("设置 DTR 失败: {e}"))?;
        port.write_request_to_send(params.rts)
            .map_err(|e| format!("设置 RTS 失败: {e}"))?;

        let stop = Arc::new(AtomicBool::new(false));
        let (io_tx, io_rx) = mpsc::channel();
        let reader_stop = stop.clone();
        let reader_app = app.clone();
        let reader_name = params.port.clone();

        thread::spawn(move || {
            run_io_loop(port, reader_stop, io_rx, reader_app.clone(), reader_name.clone());
            let _ = reader_app.emit(
                "serial-closed",
                SerialClosedEvent {
                    port: reader_name,
                },
            );
        });

        self.sessions.lock().unwrap().insert(
            params.port.clone(),
            MonitorSession { stop, io_tx },
        );
        Ok(())
    }

    pub fn write(&self, port: &str, data: Vec<u8>) -> Result<usize, String> {
        if data.is_empty() {
            return Ok(0);
        }
        let io_tx = self.io_sender(port)?;
        let (reply_tx, reply_rx) = mpsc::sync_channel(1);
        io_tx
            .send(IoRequest::Write(data, reply_tx))
            .map_err(|_| format!("端口 {port} IO 线程已退出"))?;
        recv_reply(reply_rx)
    }

    pub fn pulse_reset(&self, port: &str) -> Result<(), String> {
        let io_tx = self.io_sender(port)?;
        let (reply_tx, reply_rx) = mpsc::sync_channel(1);
        io_tx
            .send(IoRequest::PulseReset(reply_tx))
            .map_err(|_| format!("端口 {port} IO 线程已退出"))?;
        recv_reply(reply_rx)
    }

    pub fn set_lines(&self, port: &str, dtr: bool, rts: bool) -> Result<(), String> {
        let io_tx = self.io_sender(port)?;
        let (reply_tx, reply_rx) = mpsc::sync_channel(1);
        io_tx
            .send(IoRequest::SetLines {
                dtr,
                rts,
                reply: reply_tx,
            })
            .map_err(|_| format!("端口 {port} IO 线程已退出"))?;
        recv_reply(reply_rx)
    }

    fn io_sender(&self, port: &str) -> Result<Sender<IoRequest>, String> {
        let sessions = self.sessions.lock().unwrap();
        let session = sessions
            .get(port)
            .ok_or_else(|| format!("端口 {port} 未打开"))?;
        Ok(session.io_tx.clone())
    }
}

fn recv_reply<T>(rx: Receiver<Result<T, String>>) -> Result<T, String> {
    rx.recv_timeout(IO_REPLY_TIMEOUT)
        .map_err(|_| "串口操作超时".to_string())?
}

fn run_io_loop(
    mut port: Box<dyn SerialPort>,
    stop: Arc<AtomicBool>,
    io_rx: Receiver<IoRequest>,
    app: AppHandle,
    port_name: String,
) {
    let mut buf = [0u8; READ_BUF_SIZE];
    while !stop.load(Ordering::Relaxed) {
        drain_io_requests(&mut port, &io_rx, &stop);

        if stop.load(Ordering::Relaxed) {
            break;
        }

        match drain_read(port.as_mut(), &mut buf) {
            Ok(chunk) if !chunk.is_empty() => {
                let data = STANDARD.encode(&chunk);
                let _ = app.emit(
                    "serial-data",
                    SerialDataEvent {
                        port: port_name.clone(),
                        data,
                    },
                );
            }
            Ok(_) => {}
            Err(ref e) if e.kind() == std::io::ErrorKind::TimedOut => {}
            Err(_) => break,
        }
    }
}

fn drain_io_requests(
    port: &mut Box<dyn SerialPort>,
    io_rx: &Receiver<IoRequest>,
    stop: &AtomicBool,
) {
    loop {
        match io_rx.try_recv() {
            Ok(req) => handle_io_request(port, req),
            Err(mpsc::TryRecvError::Empty) => break,
            Err(mpsc::TryRecvError::Disconnected) => {
                stop.store(true, Ordering::Relaxed);
                break;
            }
        }
    }
}

fn handle_io_request(port: &mut Box<dyn SerialPort>, req: IoRequest) {
    match req {
        IoRequest::Write(data, reply) => {
            let _ = reply.send(write_port_data(port.as_mut(), &data));
        }
        IoRequest::SetLines { dtr, rts, reply } => {
            let _ = reply.send(set_port_lines(port.as_mut(), dtr, rts));
        }
        IoRequest::PulseReset(reply) => {
            let _ = reply.send(pulse_port_reset(port.as_mut()));
        }
    }
}

fn write_port_data(port: &mut dyn SerialPort, data: &[u8]) -> Result<usize, String> {
    if data.is_empty() {
        return Ok(0);
    }
    for chunk in data.chunks(WRITE_CHUNK_SIZE) {
        port.write_all(chunk).map_err(|e| e.to_string())?;
        port.flush().map_err(|e| e.to_string())?;
    }
    Ok(data.len())
}

fn set_port_lines(port: &mut dyn SerialPort, dtr: bool, rts: bool) -> Result<(), String> {
    port.write_data_terminal_ready(dtr)
        .map_err(|e| e.to_string())?;
    port.write_request_to_send(rts).map_err(|e| e.to_string())?;
    Ok(())
}

fn pulse_port_reset(port: &mut dyn SerialPort) -> Result<(), String> {
    set_port_lines(port, false, false)?;
    thread::sleep(Duration::from_millis(80));
    set_port_lines(port, true, false)?;
    thread::sleep(Duration::from_millis(50));
    Ok(())
}

fn drain_read(port: &mut dyn SerialPort, buf: &mut [u8]) -> std::io::Result<Vec<u8>> {
    let mut out = Vec::new();
    loop {
        match port.read(buf) {
            Ok(0) => break,
            Ok(n) => {
                out.extend_from_slice(&buf[..n]);
                if n < buf.len() {
                    break;
                }
                match port.bytes_to_read() {
                    Ok(0) => break,
                    Ok(_) => continue,
                    Err(_) => break,
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::TimedOut => break,
            Err(e) => return Err(e),
        }
    }
    Ok(out)
}

fn parse_data_bits(bits: u8) -> Result<DataBits, String> {
    match bits {
        5 => Ok(DataBits::Five),
        6 => Ok(DataBits::Six),
        7 => Ok(DataBits::Seven),
        8 => Ok(DataBits::Eight),
        _ => Err(format!("无效数据位: {bits}")),
    }
}

fn parse_stop_bits(bits: u8) -> Result<StopBits, String> {
    match bits {
        1 => Ok(StopBits::One),
        2 => Ok(StopBits::Two),
        _ => Err(format!("无效停止位: {bits}")),
    }
}

fn parse_parity(value: &str) -> Result<Parity, String> {
    match value.to_lowercase().as_str() {
        "none" => Ok(Parity::None),
        "odd" => Ok(Parity::Odd),
        "even" => Ok(Parity::Even),
        _ => Err(format!("无效校验位: {value}")),
    }
}

#[tauri::command]
pub fn serial_monitor_open(
    app: AppHandle,
    params: SerialOpenParams,
    monitor: State<'_, SerialMonitorManager>,
    flash_mgr: State<'_, FlashManager>,
) -> Result<(), String> {
    monitor.open(app, params, &flash_mgr)
}

#[tauri::command]
pub fn serial_monitor_close(
    port: String,
    monitor: State<'_, SerialMonitorManager>,
) -> Result<(), String> {
    monitor.close(&port)
}

#[tauri::command]
pub fn serial_monitor_write(
    port: String,
    data: Option<Vec<u8>>,
    data_b64: Option<String>,
    monitor: State<'_, SerialMonitorManager>,
) -> Result<usize, String> {
    let bytes = if let Some(b64) = data_b64.filter(|s| !s.is_empty()) {
        STANDARD
            .decode(b64.trim())
            .map_err(|e| format!("数据解码失败: {e}"))?
    } else {
        data.unwrap_or_default()
    };
    monitor.write(&port, bytes)
}

#[tauri::command]
pub fn serial_monitor_pulse_reset(
    port: String,
    monitor: State<'_, SerialMonitorManager>,
) -> Result<(), String> {
    monitor.pulse_reset(&port)
}

#[tauri::command]
pub fn serial_monitor_set_lines(
    port: String,
    dtr: bool,
    rts: bool,
    monitor: State<'_, SerialMonitorManager>,
) -> Result<(), String> {
    monitor.set_lines(&port, dtr, rts)
}

#[tauri::command]
pub fn serial_monitor_is_open(
    port: String,
    monitor: State<'_, SerialMonitorManager>,
) -> bool {
    monitor.is_open(&port)
}
