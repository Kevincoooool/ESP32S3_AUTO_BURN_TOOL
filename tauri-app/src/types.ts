export interface AppConfig {
  firmwarePaths: string[];
  firmwareAddresses: string[];
  firmwareEnables: boolean[];
  portEnables: boolean[];
  autoFlash: boolean;
  baudrate: number;
  eraseFlash: boolean;
  flashMode: string;
  flashFreq: string;
}

export interface FirmwareItem {
  path: string;
  address: string;
}

export interface FlashRecord {
  time: string;
  port: string;
  chipType: string;
  macAddress: string;
  success: boolean;
  errorMsg: string;
}

export interface FlashLogEvent {
  port: string;
  line: string;
}

export interface FlashCompleteEvent {
  port: string;
  success: boolean;
  chipType: string;
  macAddress: string;
  errorMsg: string;
}

export interface PortsChangedEvent {
  ports: string[];
}

export const BAUD_RATES = [
  "115200",
  "230400",
  "460800",
  "921600",
  "1500000",
  "2000000",
  "4000000",
];

export const FLASH_MODES = ["keep", "dio", "dout", "qio", "qout"];
export const FLASH_FREQS = ["keep", "40m", "80m", "120m"];

export const DEFAULT_CONFIG: AppConfig = {
  firmwarePaths: Array(8).fill(""),
  firmwareAddresses: Array(8).fill("0x0"),
  firmwareEnables: Array(8).fill(false),
  portEnables: Array(8).fill(true),
  autoFlash: false,
  baudrate: 4000000,
  eraseFlash: false,
  flashMode: "keep",
  flashFreq: "keep",
};
