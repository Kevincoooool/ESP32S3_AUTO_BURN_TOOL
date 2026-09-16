# ESP32 批量烧录工具 (Tauri)

基于 **Tauri 2 + Rust + TypeScript** 的 ESP32 系列芯片多端口并行烧录工具。

烧录后端使用 **espflash 4.6**（Rust 原生实现，协议与官方 [esptool](https://github.com/espressif/esptool) 5.x 对齐），包括 ESP32-P4 ECO6/ECO7 上电时序等逻辑。分发时 **只需一个安装包**，对方无需 Python、无需额外 esptool.exe。

## 功能特点

- 最多 **8 路并行烧录**
- 自动检测芯片类型与 MAC 地址（ESP32 / S2 / S3 / C3 / C6 / P4 等）
- 支持多固件分区烧录，可导入 ESP-IDF `flash_args`
- 可选擦除 Flash、高速烧录（最高 2000000 波特率）
- 内置串口助手（ANSI 颜色、发送队列、DTR 复位）
- 烧录记录导出 CSV

## 环境要求

| 组件 | 版本 |
|------|------|
| Node.js | 18+ |
| Rust | 1.95+（[rustup.rs](https://rustup.rs)，espflash 4.6 要求） |
| Windows | 10/11 |

## 开发运行

```bat
cd tauri-app
npm install
dev_tauri.bat
```

## 打包分发

```bat
cd tauri-app
build_tauri.bat
```

安装包：`tauri-app/src-tauri/target/release/bundle/nsis/*_setup.exe`

**分发给他人**：直接发送 `setup.exe`，安装后即可使用，无需任何额外文件。

## 技术说明

| 组件 | 说明 |
|------|------|
| `flasher.rs` | espflash 烧录封装，复位时序参考 esptool |
| 参考源码 | `F:\Github\esptool`（官方 esptool 5.x） |
| Rust 实现 | [esp-rs/espflash](https://github.com/esp-rs/espflash) 4.6 |

P4 v3.2（ECO7）关键逻辑在 esptool `targets/esp32p4.py` 的 `power_on_flash()`；espflash 4.5+ 已内置对应处理。

## 清理编译产物

```bat
clean.bat
```

## License

MIT
