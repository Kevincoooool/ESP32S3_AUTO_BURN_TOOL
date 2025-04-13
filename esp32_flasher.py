import tkinter as tk
from tkinter import filedialog, ttk
import serial.tools.list_ports
import threading
import time
import json
import os
import locale
font_size = 12
# 添加自定义样式和主题
def set_modern_style(root):
    # 创建自定义样式
    style = ttk.Style()
    
    # 尝试使用Windows 10主题
    try:
        style.theme_use('vista')  # vista主题在Windows上接近Win10风格
    except:
        try:
            style.theme_use('winnative')
        except:
            pass  # 如果没有可用的主题，使用默认主题
    
    # 自定义按钮样式
    style.configure('TButton', font=('Microsoft YaHei UI', font_size))
    style.configure('Accent.TButton', font=('Microsoft YaHei UI', font_size))
    
    # 自定义标签框样式
    style.configure('TLabelframe', font=('Microsoft YaHei UI', font_size))
    style.configure('TLabelframe.Label', font=('Microsoft YaHei UI', font_size, 'bold'))
    
    # 自定义标签样式
    style.configure('TLabel', font=('Microsoft YaHei UI', font_size))
    
    # 自定义输入框样式
    style.configure('TEntry', font=('Microsoft YaHei UI', font_size))
    
    # 自定义下拉框样式
    style.configure('TCombobox', font=('Microsoft YaHei UI', font_size))
    
    # 自定义复选框样式
    style.configure('TCheckbutton', font=('Microsoft YaHei UI', font_size))
    
    # 设置窗口默认字体
    root.option_add('*Font', ('Microsoft YaHei UI', font_size))
    
    # 设置窗口DPI感知
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass

class LogRedirector:
    def __init__(self, callback):
        self.callback = callback

    def write(self, text):
        if text.strip():  # 只处理非空文本
            self.callback(text.strip())

    def flush(self):
        pass

class LogWindow:
    def __init__(self, port):
        self.window = tk.Toplevel()
        self.window.title(f"端口 {port} 烧录日志")
        self.window.geometry("600x450")  # 调整窗口大小
        
        # 设置窗口图标
        try:
            self.window.iconbitmap("icon.ico")  # 如果有图标文件的话
        except:
            pass
        
        # 创建日志工具栏
        log_toolbar = ttk.Frame(self.window)
        log_toolbar.pack(fill="x", pady=(5, 5))
        
        # 添加清除日志按钮
        clear_button = ttk.Button(log_toolbar, text="清除日志", command=self.clear_log, style='Accent.TButton')
        clear_button.pack(side="right", padx=5)
        
        # 创建滚动条和文本框
        scrollbar = ttk.Scrollbar(self.window)
        scrollbar.pack(side="right", fill="y")
        
        # 使用自定义字体和颜色
        self.log_text = tk.Text(
            self.window, 
            height=font_size, 
            yscrollcommand=scrollbar.set,
            font=('Consolas', font_size),
            background='#f9f9f9',
            foreground='#333333',
            borderwidth=1,
            relief="solid"
        )
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        
        scrollbar.config(command=self.log_text.yview)
        
    def log(self, message):
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        
    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
        
    def destroy(self):
        self.window.destroy()

class ESP32Flasher:
    def __init__(self, root):
        self.root = root
        self.config_file = 'config.json'
        self.root.title("ESP32烧录工具")
        self.root.geometry("700x900")  # 调整主窗口大小
        
        # 检查并安装必要的依赖
        if not self.check_dependencies():
            self.root.withdraw()  # 隐藏主窗口
            self.root.quit()  # 退出程序
            return
            
        # 设置窗口图标
        try:
            self.root.iconbitmap("icon.ico")  # 如果有图标文件的话
        except:
            pass
        
        # 应用现代风格
        set_modern_style(root)
        
        # 初始化基本变量
        self.log_windows = {}
        self.config = {'firmware_paths': [''] * 8, 'firmware_addresses': ['0x0'] * 8, 'firmware_enables': [False] * 8}
        
        # 创建UI
        self.create_ui()
        
        # 延迟加载配置和启动监控
        self.root.after(100, self.delayed_init)

    def delayed_init(self):
        """延迟初始化，提高启动速度"""
        # 加载配置
        self.load_config()
        
        # 初始化串口列表
        self.refresh_ports()
        
        # 启动串口监控
        self.port_monitor_thread = threading.Thread(target=self.monitor_ports, daemon=True)
        self.port_monitor_thread.start()
        
        # 重定向标准输出到日志框
        import sys
        sys.stdout = LogRedirector(self.log)
        sys.stderr = LogRedirector(self.log)

    def monitor_ports(self):
        """优化串口监控逻辑"""
        old_ports = set()
        while True:
            try:
                current_ports = set(port.device for port in serial.tools.list_ports.comports())
                
                if current_ports != old_ports:
                    self.root.after(0, lambda: self.handle_port_changes(old_ports, current_ports))
                    old_ports = current_ports
                time.sleep(1.5)
            except Exception:
                time.sleep(1.5)
                continue

    def handle_port_changes(self, old_ports, current_ports):
        """统一处理端口变化"""
        for port in (old_ports - current_ports):
            if port in self.log_windows:
                self.close_log_window(port)
        
        new_ports = current_ports - old_ports
        if new_ports and self.auto_flash.get():
            self.handle_new_ports(new_ports)
        self.refresh_ports()

    def handle_new_ports(self, new_ports):
        """处理新增端口"""
        selected_firmwares = []
        for i in range(4):
            if self.firmware_enables[i].get():
                firmware = self.firmware_paths[i].get()
                address = self.firmware_addresses[i].get()
                if firmware and os.path.exists(firmware):
                    selected_firmwares.append((firmware, address))
        
        if selected_firmwares:
            for port in new_ports:
                thread = threading.Thread(
                    target=self.flash_process_multi,
                    args=(port, selected_firmwares),
                    daemon=True
                )
                thread.start()

    def create_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill="both", expand=True)
        
        self.port_frame = ttk.LabelFrame(main_frame, text="串口设置", padding=10)
        self.port_frame.pack(fill="x", pady=5)
        
        port_left_frame = ttk.Frame(self.port_frame)
        port_left_frame.pack(side="left", fill="both", expand=True)
        port_right_frame = ttk.Frame(self.port_frame)
        port_right_frame.pack(side="right", fill="both", expand=True)
        
        self.port_comboboxes = []
        self.port_labels = []
        for i in range(4):
            frame = ttk.Frame(port_left_frame)
            frame.pack(fill="x", pady=4)
            label = ttk.Label(frame, text=f"串口{i+1}:")
            label.pack(side="left")
            self.port_labels.append(label)
            combobox = ttk.Combobox(frame, width=30)
            combobox.pack(side="left", padx=5)
            self.port_comboboxes.append(combobox)
        for i in range(4, 8):
            frame = ttk.Frame(port_right_frame)
            frame.pack(fill="x", pady=4)
            label = ttk.Label(frame, text=f"串口{i+1}:")
            label.pack(side="left")
            self.port_labels.append(label)
            combobox = ttk.Combobox(frame, width=30)
            combobox.pack(side="left", padx=5)
            self.port_comboboxes.append(combobox)
        
        self.refresh_button = ttk.Button(
            self.port_frame, 
            text="刷新", 
            command=self.refresh_ports,
            style='Accent.TButton'
        )
        self.refresh_button.pack(pady=8)
        
        self.firmware_frame = ttk.LabelFrame(main_frame, text="固件设置", padding=10)
        self.firmware_frame.pack(fill="x", pady=8)
        
        self.firmware_paths = []
        self.firmware_entries = []
        self.firmware_addresses = []
        self.firmware_enables = []
        
        for i in range(8):
            frame = ttk.Frame(self.firmware_frame)
            frame.pack(fill="x", pady=4)
            enable_var = tk.BooleanVar(value=False)
            enable_check = ttk.Checkbutton(
                frame, 
                variable=enable_var,
                command=lambda: self.save_config()
            )
            enable_check.pack(side="left")
            self.firmware_enables.append(enable_var)
            path_var = tk.StringVar()
            entry = ttk.Entry(frame, textvariable=path_var, width=50)
            entry.pack(side="left", padx=5)
            def scroll_to_end(var, entry=None):
                if entry:
                    self.root.after(10, lambda: entry.xview_moveto(1.0))
            path_var.trace_add("write", lambda name, index, mode, e=entry: scroll_to_end(None, e))
            self.firmware_paths.append(path_var)
            self.firmware_entries.append(entry)
            addr_entry = ttk.Entry(frame, width=10)
            addr_entry.insert(0, "0x0")
            addr_entry.pack(side="left", padx=5)
            self.firmware_addresses.append(addr_entry)
            browse_btn = ttk.Button(
                frame, 
                text="浏览", 
                command=lambda idx=i: self.browse_firmware(idx)
            )
            browse_btn.pack(side="left", padx=5)
        
        self.address_frame = ttk.LabelFrame(main_frame, text="烧录设置", padding=10)
        self.address_frame.pack(fill="x", pady=8)
        self.baud_label = ttk.Label(self.address_frame, text="波特率:")
        self.baud_label.pack(side="left", padx=5)
        self.baud_rates = ['115200', '230400', '460800', '921600', '1152000', '1500000', '2000000']
        self.baud_combobox = ttk.Combobox(self.address_frame, width=10, values=self.baud_rates)
        self.baud_combobox.set('2000000')
        self.baud_combobox.pack(side="left", padx=5)
        self.auto_flash = tk.BooleanVar(value=False)
        self.auto_flash_check = ttk.Checkbutton(
            self.address_frame, 
            text="自动烧录", 
            variable=self.auto_flash
        )
        self.auto_flash_check.pack(side="left", padx=15)
        
        self.flash_button = ttk.Button(
            main_frame, 
            text="开始烧录", 
            command=self.start_flash,
            style='Accent.TButton'
        )
        self.flash_button.pack(pady=12)
        
        self.log_frame = ttk.LabelFrame(main_frame, text="日志", padding=10)
        self.log_frame.pack(fill="both", expand=True, pady=8)
        log_toolbar = ttk.Frame(self.log_frame)
        log_toolbar.pack(fill="x", pady=(0, 5))
        clear_button = ttk.Button(
            log_toolbar, 
            text="清除日志", 
            command=self.clear_log,
            style='Accent.TButton'
        )
        clear_button.pack(side="right")
        scrollbar = ttk.Scrollbar(self.log_frame)
        scrollbar.pack(side="right", fill="y")
        self.log_text = tk.Text(
            self.log_frame, 
            height=font_size,
            yscrollcommand=scrollbar.set,
            font=('Consolas', font_size),
            background='#f9f9f9',
            foreground='#333333',
            borderwidth=1,
            relief="solid"
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.log_text.yview)
        
        self.refresh_ports()

    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        for combobox in self.port_comboboxes:
            combobox.set('')
            combobox['values'] = []
        for i, port in enumerate(ports[:8]):
            self.port_comboboxes[i]['values'] = [port]
            self.port_comboboxes[i].set(port)
        if self.config.get('last_firmware'):
            self.firmware_path.set(self.config['last_firmware'])

    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                    if 'firmware_paths' in self.config:
                        for i, path in enumerate(self.config['firmware_paths']):
                            if i < len(self.firmware_paths):
                                if os.path.exists(path):
                                    self.firmware_paths[i].set(path)
                                    self.root.after(100, lambda idx=i: self.firmware_entries[idx].xview_moveto(1.0))
                                else:
                                    self.firmware_paths[i].set('')
                    if 'firmware_addresses' in self.config:
                        for i, addr in enumerate(self.config['firmware_addresses']):
                            if i < len(self.firmware_addresses):
                                self.firmware_addresses[i].delete(0, tk.END)
                                self.firmware_addresses[i].insert(0, addr or '0x0')
                    if 'firmware_enables' in self.config:
                        for i, enabled in enumerate(self.config['firmware_enables']):
                            if i < len(self.firmware_enables):
                                self.firmware_enables[i].set(enabled)
            else:
                self.config = {
                    'firmware_paths': [''] * 8,
                    'firmware_addresses': ['0x0'] * 8,
                    'firmware_enables': [False] * 8
                }
        except Exception as e:
            self.log(f"加载配置失败: {str(e)}")
            self.config = {
                'firmware_paths': [''] * 8,
                'firmware_addresses': ['0x0'] * 8,
                'firmware_enables': [False] * 8
            }

    def save_config(self):
        try:
            self.config['firmware_paths'] = [path.get() for path in self.firmware_paths]
            self.config['firmware_addresses'] = [addr.get() for addr in self.firmware_addresses]
            self.config['firmware_enables'] = [enable.get() for enable in self.firmware_enables]
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f)
        except Exception as e:
            self.log(f"保存配置失败: {str(e)}")

    def browse_firmware(self, index):
        initial_dir = os.path.dirname(self.firmware_paths[index].get()) or os.getcwd()
        filename = filedialog.askopenfilename(
            initialdir=initial_dir,
            filetypes=[("二进制文件", "*.bin"), ("所有文件", "*.*")]
        )
        if filename:
            self.firmware_paths[index].set(filename)
            self.root.after(50, lambda: self.firmware_entries[index].xview_moveto(1.0))
            self.save_config()

    def start_flash(self):
        selected_ports = [cb.get() for cb in self.port_comboboxes if cb.get()]
        if not selected_ports:
            self.log("错误: 请选择至少一个串口")
            return
        selected_firmwares = []
        for i in range(8):
            if self.firmware_enables[i].get():
                firmware = self.firmware_paths[i].get()
                address = self.firmware_addresses[i].get()
                if firmware and os.path.exists(firmware):
                    selected_firmwares.append((firmware, address))
        if not selected_firmwares:
            self.log("错误: 请选择至少一个固件")
            return
        for port in selected_ports:
            thread = threading.Thread(
                target=self.flash_process_multi,
                args=(port, selected_firmwares),
                daemon=True
            )
            thread.start()

    def flash_process_multi(self, port, firmwares):
        # 创建新的日志窗口
        log_window = LogWindow(port)
        self.log_windows[port] = log_window
        
        try:
            # 输出重定向类
            class ThreadSafeOutput:
                def __init__(self, log_window):
                    self._log_window = log_window
                def write(self, text):
                    if text.strip():
                        self._log_window.log(text.strip())
                def flush(self):
                    pass
            
            log_window.log("检测芯片类型...")
            
            # 使用子进程执行芯片检测
            import subprocess
            cmd = ["python", "-m", "esptool", "--port", port, "chip_id"]
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                startupinfo=startupinfo
            )
            output = ""
            for line in process.stdout:
                log_window.log(line.strip())
                output += line
            process.wait()
            
            # 解析芯片型号
            chip_type = None
            if "Chip is ESP32-S3" in output:
                chip_type = "ESP32-S3"
            elif "Chip is ESP32-S2" in output:
                chip_type = "ESP32-S2"
            elif "Chip is ESP32-C3" in output:
                chip_type = "ESP32-C3"
            elif "Chip is ESP32-C6" in output:
                chip_type = "ESP32-C6"
            elif "Chip is ESP32-P4" in output:
                chip_type = "ESP32-P4"
            elif "Chip is ESP32" in output:
                chip_type = "ESP32"
            
            if not chip_type:
                log_window.log("未能识别芯片类型，当前窗口将关闭")
                self.root.after(500, lambda: self.close_log_window(port))
                return
            
            log_window.log(f"检测到芯片类型: {chip_type}")
            
            # 检查是否支持该芯片型号
            chip_param = self.get_chip_param(chip_type)
            if not chip_param:
                log_window.log(f"不支持的芯片类型: {chip_type}，当前窗口将关闭")
                self.root.after(500, lambda: self.close_log_window(port))
                return

            flash_params = {
                'esp32': {
                    'flash_mode': 'dio',
                    'flash_freq': '40m',
                    'flash_size': 'detect'
                },
                'esp32s3': {
                    'flash_mode': 'dio',
                    'flash_freq': '80m',
                    'flash_size': '16MB'
                },
                'esp32s2': {
                    'flash_mode': 'dio',
                    'flash_freq': '80m',
                    'flash_size': '4MB'
                },
                'esp32c3': {
                    'flash_mode': 'dio',
                    'flash_freq': '80m',
                    'flash_size': '4MB'
                },
                'esp32c6': {
                    'flash_mode': 'dio',
                    'flash_freq': '80m',
                    'flash_size': '4MB'
                }
            }
            params = flash_params.get(chip_param, flash_params['esp32'])
            
            # 对每个固件进行烧录
            for firmware, address in firmwares:
                flash_cmd = [
                    "python", "-m", "esptool",
                    "--port", port,
                    "--baud", self.baud_combobox.get(),
                    "--before", "default_reset",
                    "--after", "hard_reset",
                    "write_flash",
                    address, firmware
                ]
                log_window.log(f"执行命令: {' '.join(flash_cmd)}")
                
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                system_encoding = locale.getpreferredencoding()
                log_window.log(f"系统编码: {system_encoding}")
                cmd_str = " ".join(flash_cmd)
                process = subprocess.Popen(
                    cmd_str, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    text=True,
                    startupinfo=startupinfo,
                    shell=True
                )
                for line in process.stdout:
                    log_window.log(line.strip())
                process.wait()
                
                if process.returncode != 0:
                    log_window.log(f"烧录失败，返回码: {process.returncode}")
                    raise Exception(f"烧录失败，返回码: {process.returncode}")
                
                log_window.log(f"端口 {port} 固件 {firmware} 烧录完成!")

            log_window.log(f"端口 {port} 所有固件烧录完成!")
            
            # 发送复位信号后关闭当前窗口
            self.send_reset_signal(port)
            log_window.log("烧录完成、复位后，窗口即将关闭...")
            self.root.after(500, lambda: self.close_log_window(port))
                
        except Exception as e:
            log_window.log(f"端口 {port} 烧录错误: {str(e)}")
            self.log(f"错误: {str(e)}")

    def send_reset_signal(self, port):
        """发送复位信号给ESP32"""
        try:
            import serial
            reset_baud = 115200
            ser = serial.Serial(port, reset_baud, timeout=1)
            ser.setDTR(False)
            time.sleep(0.1)
            ser.setDTR(True)
            time.sleep(0.1)
            ser.close()
            self.log(f"端口 {port} 复位信号已发送!")
        except Exception as e:
            self.log(f"发送复位信号失败: {str(e)}")

    def monitor_ports(self):
        old_ports = set()
        while True:
            current_ports = set(port.device for port in serial.tools.list_ports.comports())
            removed_ports = old_ports - current_ports
            for port in removed_ports:
                if port in self.log_windows:
                    self.root.after(0, lambda p=port: self.close_log_window(p))
            new_ports = current_ports - old_ports
            if new_ports and self.auto_flash.get():
                selected_firmwares = []
                for i in range(4):
                    if self.firmware_enables[i].get():
                        firmware = self.firmware_paths[i].get()
                        address = self.firmware_addresses[i].get()
                        if firmware and os.path.exists(firmware):
                            selected_firmwares.append((firmware, address))
                if selected_firmwares:
                    for port in new_ports:
                        thread = threading.Thread(
                            target=self.flash_process_multi,
                            args=(port, selected_firmwares),
                            daemon=True
                        )
                        thread.start()
            if current_ports != old_ports:
                self.root.after(0, self.refresh_ports)
                old_ports = current_ports
            time.sleep(1)

    def close_log_window(self, port):
        """安全地关闭日志窗口"""
        if port in self.log_windows:
            self.log_windows[port].destroy()
            del self.log_windows[port]

    def log(self, message):
        """线程安全的日志记录方法"""
        def _log():
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
        self.root.after(0, _log)

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def detect_chip(self, port):
        try:
            cmd = ["--port", port, "chip_id"]
            log_window = self.log_windows.get(port)
            if not log_window:
                return None
            from io import StringIO
            output_buffer = StringIO()
            import sys
            old_stdout = sys.stdout
            class TeeOutput:
                def __init__(self, original, buffer):
                    self.original = original
                    self.buffer = buffer
                def write(self, text):
                    self.original.write(text)
                    self.buffer.write(text)
                def flush(self):
                    self.original.flush()
            sys.stdout = TeeOutput(old_stdout, output_buffer)
            try:
                esptool.main(cmd)
                output = output_buffer.getvalue()
            finally:
                sys.stdout = old_stdout
            if "Chip is ESP32-S3" in output:
                return "ESP32-S3"
            elif "Chip is ESP32-S2" in output:
                return "ESP32-S2"
            elif "Chip is ESP32-C3" in output:
                return "ESP32-C3"
            elif "Chip is ESP32-C6" in output:
                return "ESP32-C6"
            elif "Chip is ESP32-P4" in output:
                return "ESP32-P4"
            elif "Chip is ESP32" in output:
                return "ESP32"
            else:
                log_window.log("未能识别芯片类型")
                return None
        except Exception as e:
            if log_window:
                log_window.log(f"芯片检测失败: {str(e)}")
            return None

    def get_chip_param(self, chip_type):
        """将检测到的芯片类型转换为对应的参数"""
        chip_map = {
            'ESP32': 'esp32',
            'ESP32-S3': 'esp32s3',
            'ESP32-S2': 'esp32s2',
            'ESP32-C3': 'esp32c3',
            'ESP32-C6': 'esp32c6',
            'ESP32-P4': 'esp32p4'
        }
        return chip_map.get(chip_type)

    def check_dependencies(self):
        try:
            import esptool
            return True
        except ImportError:
            import tkinter.messagebox as messagebox
            import subprocess
            import sys
            result = messagebox.askyesno(
                "依赖检查",
                "未安装必要的依赖 esptool，是否立即安装？"
            )
            if result:
                try:
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    subprocess.check_call(
                        [sys.executable, "-m", "pip", "install", "esptool"],
                        startupinfo=startupinfo
                    )
                    messagebox.showinfo("安装成功", "esptool 安装成功！请重新启动程序。")
                except Exception as e:
                    messagebox.showerror(
                        "安装失败",
                        f"安装 esptool 失败: {str(e)}\n请手动执行命令: pip install esptool"
                    )
                return False
            else:
                messagebox.showwarning(
                    "依赖缺失",
                    "程序无法继续运行，请先安装 esptool。\n安装命令: pip install esptool"
                )
                return False

if __name__ == "__main__":
    root = tk.Tk()
    app = ESP32Flasher(root)
    root.mainloop()
