use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use tauri::Manager;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AppConfig {
    pub firmware_paths: Vec<String>,
    pub firmware_addresses: Vec<String>,
    pub firmware_enables: Vec<bool>,
    pub port_enables: Vec<bool>,
    pub auto_flash: bool,
    pub baudrate: u32,
    pub erase_flash: bool,
    pub flash_mode: String,
    pub flash_freq: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            firmware_paths: vec![String::new(); 8],
            firmware_addresses: vec!["0x0".to_string(); 8],
            firmware_enables: vec![false; 8],
            port_enables: vec![true; 8],
            auto_flash: false,
            baudrate: 4_000_000,
            erase_flash: false,
            flash_mode: "keep".to_string(),
            flash_freq: "keep".to_string(),
        }
    }
}

pub fn config_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map_err(|e| e.to_string())
        .map(|dir| dir.join("config.json"))
}

pub fn load_config(app: &tauri::AppHandle) -> Result<AppConfig, String> {
    let path = config_path(app)?;
    if !path.exists() {
        return Ok(AppConfig::default());
    }
    let content = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    serde_json::from_str(&content).map_err(|e| e.to_string())
}

pub fn save_config(app: &tauri::AppHandle, config: &AppConfig) -> Result<(), String> {
    let path = config_path(app)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let content = serde_json::to_string_pretty(config).map_err(|e| e.to_string())?;
    fs::write(path, content).map_err(|e| e.to_string())
}
