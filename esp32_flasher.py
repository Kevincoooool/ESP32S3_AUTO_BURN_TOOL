import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import serial.tools.list_ports
import threading
import time
import json
import os
import locale
import subprocess
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
        self.config = {'firmware_paths': [''] * 8, 'firmware_addresses': ['0x0'] * 8}  # 修改为8个
        self.port_enables = []  # 添加串口启用状态列表
        
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
                    # 使用一个函数处理所有端口变化
                    self.root.after(0, lambda: self.handle_port_changes(old_ports, current_ports))
                    old_ports = current_ports
                
                # 增加睡眠时间，减少CPU使用
                time.sleep(1.5)
            except Exception:
                time.sleep(1.5)
                continue

    def handle_port_changes(self, old_ports, current_ports):
        """统一处理端口变化"""
        # 处理移除的端口
        for port in (old_ports - current_ports):
            if port in self.log_windows:
                self.close_log_window(port)
        
        # 处理新增的端口
        new_ports = current_ports - old_ports
        if new_ports:
            self.log(f"检测到新端口: {new_ports}")
            if self.auto_flash.get():
                self.log("自动烧录已启用，开始烧录...")
                # 添加短暂延迟，等待设备初始化
                self.root.after(1000, lambda: self.handle_new_ports(new_ports))
            else:
                self.log("自动烧录未启用")
        
        # 更新端口列表
        self.refresh_ports()

    def handle_new_ports(self, new_ports):
        """处理新增端口"""
        self.log(f"处理新端口: {new_ports}")
        selected_firmwares = []
        
        # 检查启用的固件
        for i in range(8):
            if self.firmware_enables[i].get():
                firmware = self.firmware_paths[i].get()
                address = self.firmware_addresses[i].get()
                if firmware and os.path.exists(firmware):
                    selected_firmwares.append((firmware, address))
                    self.log(f"已选择固件: {firmware} 地址: {address}")
                elif self.firmware_enables[i].get():
                    self.log(f"警告: 固件 #{i+1} 已启用但路径无效: {firmware}")
        
        if not selected_firmwares:
            self.log("错误: 没有选择有效的固件，无法执行自动烧录")
            return
        
        # 过滤出启用的端口
        enabled_ports = []
        for port in new_ports:
            # 查找端口在comboboxes中的索引
            for i, cb in enumerate(self.port_comboboxes):
                if cb.get() == port and self.port_enables[i].get():
                    enabled_ports.append(port)
                    break
        
        if not enabled_ports:
            self.log("没有启用的端口可用于自动烧录")
            return
        
        self.log(f"开始为 {len(enabled_ports)} 个启用的端口烧录 {len(selected_firmwares)} 个固件")
        
        # 为每个启用的端口创建烧录线程
        for port in enabled_ports:
            thread = threading.Thread(
                target=self.flash_process_multi,
                args=(port, selected_firmwares),
                daemon=True
            )
            thread.start()

    def create_ui(self):
        # 创建主框架，添加内边距
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill="both", expand=True)
        
        # 串口选择
        self.port_frame = ttk.LabelFrame(main_frame, text="串口设置", padding=10)
        self.port_frame.pack(fill="x", pady=5)
        
        # 创建左右布局框架
        port_left_frame = ttk.Frame(self.port_frame)
        port_left_frame.pack(side="left", fill="both", expand=True)
        
        port_right_frame = ttk.Frame(self.port_frame)
        port_right_frame.pack(side="right", fill="both", expand=True)
        
        # 创建8个串口选择组
        self.port_comboboxes = []
        self.port_labels = []
        
        # 创建左侧串口1-4
        for i in range(4):
            frame = ttk.Frame(port_left_frame)
            frame.pack(fill="x", pady=4)  # 增加垂直间距
             # 添加启用复选框
            enable_var = tk.BooleanVar(value=True)  # 默认启用
            enable_check = ttk.Checkbutton(
                frame, 
                variable=enable_var,
                command=lambda: self.save_config()
            )
            enable_check.pack(side="left")
            self.port_enables.append(enable_var)
            label = ttk.Label(frame, text=f"串口{i+1}:")
            label.pack(side="left")
            self.port_labels.append(label)
            
            combobox = ttk.Combobox(frame, width=30)
            combobox.pack(side="left", padx=5)
            self.port_comboboxes.append(combobox)
            
        # 创建右侧串口5-8
        for i in range(4, 8):
            frame = ttk.Frame(port_right_frame)
            frame.pack(fill="x", pady=4)  # 增加垂直间距
            
            # 添加启用复选框
            enable_var = tk.BooleanVar(value=True)  # 默认启用
            enable_check = ttk.Checkbutton(
                frame, 
                variable=enable_var,
                command=lambda: self.save_config()
            )
            enable_check.pack(side="left")
            self.port_enables.append(enable_var)
            label = ttk.Label(frame, text=f"串口{i+1}:")
            label.pack(side="left")
            self.port_labels.append(label)
            
            combobox = ttk.Combobox(frame, width=30)
            combobox.pack(side="left", padx=5)
            self.port_comboboxes.append(combobox)
        
        # 刷新按钮放在底部中间，使用强调样式
        self.refresh_button = ttk.Button(
            self.port_frame, 
            text="刷新", 
            command=self.refresh_ports,
            style='Accent.TButton'
        )
        self.refresh_button.pack(pady=8)  # 增加垂直间距
        
        # 固件选择
        self.firmware_frame = ttk.LabelFrame(main_frame, text="固件设置", padding=10)
        self.firmware_frame.pack(fill="x", pady=8)  # 增加垂直间距
        
        # 创建固件选择组
        self.firmware_paths = []
        self.firmware_entries = []
        self.firmware_addresses = []
        self.firmware_enables = []
        
        # 修改为8个固件选择
        for i in range(8):  # 修改循环次数为8
            frame = ttk.Frame(self.firmware_frame)
            frame.pack(fill="x", pady=4)
            
            # 启用选择框，添加回调函数
            enable_var = tk.BooleanVar(value=False)
            enable_check = ttk.Checkbutton(
                frame, 
                variable=enable_var,
                command=lambda: self.save_config()
            )
            enable_check.pack(side="left")
            self.firmware_enables.append(enable_var)
            
            # 固件路径
            path_var = tk.StringVar()
            entry = ttk.Entry(frame, textvariable=path_var, width=50)
            entry.pack(side="left", padx=5)
            
            # 修复显示尾部的方法
            def scroll_to_end(var, entry=None):
                if entry:
                    self.root.after(10, lambda: entry.xview_moveto(1.0))
            
            # 绑定变量变化事件
            path_var.trace_add("write", lambda name, index, mode, e=entry: scroll_to_end(None, e))
            
            self.firmware_paths.append(path_var)
            self.firmware_entries.append(entry)
            
            # 地址输入框
            addr_entry = ttk.Entry(frame, width=10)
            addr_entry.insert(0, "0x0")
            addr_entry.pack(side="left", padx=5)
            self.firmware_addresses.append(addr_entry)
            
            # 浏览按钮
            browse_btn = ttk.Button(
                frame, 
                text="浏览", 
                command=lambda idx=i: self.browse_firmware(idx)
            )
            browse_btn.pack(side="left", padx=5)
        
        # 地址设置
        self.address_frame = ttk.LabelFrame(main_frame, text="烧录设置", padding=10)
        self.address_frame.pack(fill="x", pady=8)  # 增加垂直间距
        
        # 第一行设置
        settings_row1 = ttk.Frame(self.address_frame)
        settings_row1.pack(fill="x", pady=2)
        
        # 添加波特率选择
        self.baud_label = ttk.Label(settings_row1, text="波特率:")
        self.baud_label.pack(side="left", padx=5)
        
        self.baud_rates = ['115200', '230400', '460800', '921600', '1152000', '1500000', '2000000']
        self.baud_combobox = ttk.Combobox(settings_row1, width=10, values=self.baud_rates, state='readonly')
        self.baud_combobox.set('921600')  # 默认值改为更稳定的921600
        self.baud_combobox.bind('<<ComboboxSelected>>', lambda e: self.save_config())
        self.baud_combobox.pack(side="left", padx=5)
        
        # 擦除Flash选项
        self.erase_flash = tk.BooleanVar(value=False)
        self.erase_flash_check = ttk.Checkbutton(
            settings_row1, 
            text="擦除Flash", 
            variable=self.erase_flash,
            command=lambda: self.save_config()
        )
        self.erase_flash_check.pack(side="left", padx=15)
        
        # 在波特率选择后添加自动烧录选项
        self.auto_flash = tk.BooleanVar(value=False)
        self.auto_flash_check = ttk.Checkbutton(
            settings_row1, 
            text="自动烧录", 
            variable=self.auto_flash,
            command=lambda: self.save_config()
        )
        self.auto_flash_check.pack(side="left", padx=15)  # 增加水平间距
        
        # 烧录按钮，使用强调样式
        self.flash_button = ttk.Button(
            main_frame, 
            text="开始烧录", 
            command=self.start_flash,
            style='Accent.TButton'
        )
        self.flash_button.pack(pady=12)  # 增加垂直间距
        
        # 日志显示
        self.log_frame = ttk.LabelFrame(main_frame, text="日志", padding=10)
        self.log_frame.pack(fill="both", expand=True, pady=8)  # 增加垂直间距
        
        # 创建日志工具栏
        log_toolbar = ttk.Frame(self.log_frame)
        log_toolbar.pack(fill="x", pady=(0, 5))
        
        # 添加清除日志按钮
        clear_button = ttk.Button(
            log_toolbar, 
            text="清除日志", 
            command=self.clear_log,
            style='Accent.TButton'
        )
        clear_button.pack(side="right")
        
        # 创建滚动条
        scrollbar = ttk.Scrollbar(self.log_frame)
        scrollbar.pack(side="right", fill="y")
        
        # 创建文本框并关联滚动条，使用更现代的样式
        self.log_text = tk.Text(
            self.log_frame, 
            height=font_size,  # 增加高度
            yscrollcommand=scrollbar.set,
            font=('Consolas', font_size),  # 使用等宽字体
            background='#f9f9f9',  # 浅灰色背景
            foreground='#333333',  # 深灰色文字
            borderwidth=1,
            relief="solid"
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        
        # 设置滚动条的命令
        scrollbar.config(command=self.log_text.yview)
        
        # 初始化串口列表
        self.refresh_ports()

    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        
        # 清空所有下拉框
        for combobox in self.port_comboboxes:
            combobox.set('')
            combobox['values'] = []
        
        # 为每个检测到的端口设置对应的下拉框
        for i, port in enumerate(ports[:8]):  # 修改为8个端口
            self.port_comboboxes[i]['values'] = [port]
            self.port_comboboxes[i].set(port)

    def load_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                    # 加载多个固件路径
                    if 'firmware_paths' in self.config:
                        for i, path in enumerate(self.config['firmware_paths']):
                            if i < len(self.firmware_paths):
                                if os.path.exists(path):
                                    self.firmware_paths[i].set(path)
                                    self.root.after(100, lambda idx=i: self.firmware_entries[idx].xview_moveto(1.0))
                                else:
                                    self.firmware_paths[i].set('')
                    # 加载固件地址
                    if 'firmware_addresses' in self.config:
                        for i, addr in enumerate(self.config['firmware_addresses']):
                            if i < len(self.firmware_addresses):
                                self.firmware_addresses[i].delete(0, tk.END)
                                self.firmware_addresses[i].insert(0, addr or '0x0')
                    # 加载固件启用状态
                    if 'firmware_enables' in self.config:
                        for i, enabled in enumerate(self.config['firmware_enables']):
                            if i < len(self.firmware_enables):
                                self.firmware_enables[i].set(enabled)
                    # 加载串口启用状态
                    if 'port_enables' in self.config:
                        for i, enabled in enumerate(self.config['port_enables']):
                            if i < len(self.port_enables):
                                self.port_enables[i].set(enabled)
                    # 加载自动烧录设置
                    if 'auto_flash' in self.config:
                        self.auto_flash.set(self.config['auto_flash'])
                    # 加载波特率设置
                    if 'baudrate' in self.config:
                        self.baud_combobox.set(str(self.config['baudrate']))
                    # 加载擦除Flash设置
                    if 'erase_flash' in self.config:
                        self.erase_flash.set(self.config['erase_flash'])
            else:
                self.config = {
                    'firmware_paths': [''] * 8,
                    'firmware_addresses': ['0x0'] * 8,
                    'firmware_enables': [False] * 8,
                    'port_enables': [True] * 8,
                    'auto_flash': False,
                    'baudrate': 921600,
                    'erase_flash': False
                }
        except Exception as e:
            self.log(f"加载配置失败: {str(e)}")
            self.config = {
                'firmware_paths': [''] * 8,
                'firmware_addresses': ['0x0'] * 8,
                'firmware_enables': [False] * 8,
                'port_enables': [True] * 8,
                'auto_flash': False,
                'baudrate': 921600,
                'erase_flash': False
            }

    def save_config(self):
        try:
            self.config['firmware_paths'] = [path.get() for path in self.firmware_paths]
            self.config['firmware_addresses'] = [addr.get() for addr in self.firmware_addresses]
            self.config['firmware_enables'] = [enable.get() for enable in self.firmware_enables]
            self.config['port_enables'] = [enable.get() for enable in self.port_enables]
            self.config['auto_flash'] = self.auto_flash.get()
            self.config['baudrate'] = int(self.baud_combobox.get())
            self.config['erase_flash'] = self.erase_flash.get()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
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
            # 使用延迟确保在文本更新后滚动到尾部
            self.root.after(50, lambda: self.firmware_entries[index].xview_moveto(1.0))
            self.save_config()

    def start_flash(self):
    # 获取启用的串口
        selected_ports = []
        for i, cb in enumerate(self.port_comboboxes):
            if cb.get() and self.port_enables[i].get():  # 只选择启用的串口
                selected_ports.append(cb.get())
        
        if not selected_ports:
            self.log("错误: 请选择并启用至少一个串口")
            return
        
        # 获取选中的固件和地址
        selected_firmwares = []
        for i in range(8):  # 修改为8个
            if self.firmware_enables[i].get():
                firmware = self.firmware_paths[i].get()
                address = self.firmware_addresses[i].get()
                if firmware and os.path.exists(firmware):
                    selected_firmwares.append((firmware, address))
        
        if not selected_firmwares:
            self.log("错误: 请选择至少一个固件")
            return
        
        # 为每个选中的端口创建烧录线程
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
        # 确保日志窗口显示在前台
        log_window.window.lift()
        log_window.window.focus_force()
        
        # 记录开始信息
        log_window.log(f"开始为端口 {port} 烧录固件...")
        self.log(f"开始为端口 {port} 烧录固件...")
        try:
            # 创建输出重定向类
            class ThreadSafeOutput:
                def __init__(self, log_window):
                    self._log_window = log_window
                
                def write(self, text):
                    if text and text.strip():
                        # 使用after方法确保在主线程中更新UI
                        self._log_window.window.after(0, lambda: self._log_window.log(text.strip()))
                
                def flush(self):
                    pass
            
            # 检测芯片类型
            log_window.log(f"检测芯片类型...")
            
            # 使用子进程执行芯片检测，避免输出重定向冲突
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
            
            # 从输出中解析芯片类型
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
                log_window.log("未能识别芯片类型")
                return
            
            log_window.log(f"检测到芯片类型: {chip_type}")
            
            # 获取对应的芯片参数
            chip_param = self.get_chip_param(chip_type)
            if not chip_param:
                log_window.log(f"不支持的芯片类型: {chip_type}")
                return

            # 根据芯片类型设置烧录参数
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

            # 如果需要擦除Flash，先执行擦除操作
            if self.erase_flash.get():
                log_window.log("正在擦除Flash...")
                erase_cmd = [
                    "python", "-m", "esptool",
                    "--port", port,
                    "--baud", self.baud_combobox.get(),
                    "erase_flash"
                ]
                
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                erase_process = subprocess.Popen(
                    " ".join(erase_cmd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    startupinfo=startupinfo,
                    shell=True
                )
                
                for line in erase_process.stdout:
                    log_window.log(line.strip())
                erase_process.wait()
                
                if erase_process.returncode != 0:
                    log_window.log(f"擦除Flash失败，返回码: {erase_process.returncode}")
                    raise Exception(f"擦除Flash失败，返回码: {erase_process.returncode}")
                
                log_window.log("Flash擦除完成!")

            # 为每个固件创建命令并执行烧录
            for firmware, address in firmwares:
                # 构建烧录命令
                flash_cmd = [
                    "python", "-m", "esptool",
                    "--port", port,
                    "--baud", self.baud_combobox.get(),
                    "--before", "default_reset",
                    "--after", "hard_reset",
                    "write_flash",
                    "-z",  # 添加压缩选项，加快烧录速度
                    "--flash_mode", params['flash_mode'],
                    "--flash_freq", params['flash_freq'],
                    address, firmware
                ]
                
                log_window.log(f"执行命令: {' '.join(flash_cmd)}")
                
                # 使用子进程执行烧录，确保正确处理中文路径
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                # 获取系统默认编码
                system_encoding = locale.getpreferredencoding()
                log_window.log(f"系统编码: {system_encoding}")
                
                # 使用shell=True来处理中文路径问题
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
                
        except Exception as e:
            log_window.log(f"端口 {port} 烧录错误: {str(e)}")
            self.log(f"错误: {str(e)}")


    def close_log_window(self, port):
        """安全地关闭日志窗口"""
        if port in self.log_windows:
            try:
                self.log_windows[port].destroy()
                del self.log_windows[port]
            except Exception as e:
                self.log(f"关闭日志窗口失败: {str(e)}")

    def log(self, message):
        """线程安全的日志记录方法"""
        def _log():
            try:
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
            except Exception:
                pass
        
        # 检查是否在主线程
        try:
            self.root.after(0, _log)
        except Exception:
            # 如果after失败，直接调用（可能在主线程中）
            _log()

    def clear_log(self):
        """清除日志内容"""
        self.log_text.delete(1.0, tk.END)

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
        """检查必要的依赖"""
        try:
            # 只检查serial库，esptool通过命令行调用
            import serial
            import subprocess
            return True
        except ImportError as e:
            messagebox.showerror("依赖错误", f"缺少必要的依赖: {str(e)}\n请安装所需的依赖后重试。")
            return False

if __name__ == "__main__":
    root = tk.Tk()
    app = ESP32Flasher(root)
    root.mainloop()